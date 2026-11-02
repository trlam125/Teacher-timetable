/* Constraint editor and global/session lock handling. */
let constraintSaveInFlight = false;
let globalSaveInFlight = false;
let globalLockGradeId = null;
function selectedLockSlots() {
  return globalLockGradeId == null
    ? data.project.blocked_slots || []
    : (data.grades || []).find((grade) => grade.id === globalLockGradeId)?.blocked_slots || [];
}
async function changeLockScope(select) {
  if (globalSaveInFlight || constraintSaveInFlight) {
    select.value = globalLockGradeId == null ? "all" : String(globalLockGradeId);
    return;
  }
  if (globalLocksDraftDirty && !(await confirmAction(
    "Bạn có thay đổi khóa lịch chưa lưu. Đổi phạm vi sẽ bỏ các thay đổi đó.",
    { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
  ))) {
    select.value = globalLockGradeId == null ? "all" : String(globalLockGradeId);
    return;
  }
  globalLockGradeId = select.value === "all" ? null : Number(select.value);
  globalLocksDraftDirty = false;
  renderGlobalSessionLocks();
}
function constraintStateMarkup(blocked, label) {
  const icon = blocked
    ? '<svg class="constraint-state-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>'
    : '<svg class="constraint-state-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>';
  return `${icon}<span>${esc(label)}</span>`;
}
function animateConstraintState(host, blocked, label) {
  if (!host) return;
  let stage = host.querySelector(":scope > .constraint-state-stage");
  if (!stage) {
    stage = document.createElement("span");
    stage.className = "constraint-state-stage";
    host.textContent = "";
    host.appendChild(stage);
  }
  stage
    .querySelectorAll(".constraint-state-content.constraint-state-leaving")
    .forEach((node) => node.remove());
  const current = stage.querySelector(".constraint-state-content");
  const next = document.createElement("span");
  next.className = `constraint-state-content constraint-state-enter ${blocked ? "is-blocked" : "is-allowed"}`;
  next.innerHTML = constraintStateMarkup(blocked, label);
  if (current) {
    current.classList.add("constraint-state-leaving");
    const cleanup = () => current.remove();
    current.addEventListener("animationend", cleanup, { once: true });
    setTimeout(cleanup, 360);
  }
  stage.appendChild(next);
}
function setGlobalSlotLockState(button, locked, animate = true) {
  if (!button) return;
  button.classList.toggle("is-locked", locked);
  if (button.disabled) return;
  if (animate)
    animateConstraintState(button, locked, locked ? "Đã khóa" : "Cho phép");
  else
    button.innerHTML = `<span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, locked ? "Đã khóa" : "Cho phép")}</span></span>`;
}
function setSessionLockState(button, locked, animate = true) {
  if (!button) return;
  button.classList.toggle("is-locked", locked);
  const label = button.dataset.inherited === "true"
    ? `${button.dataset.label} · Khóa chung` : button.dataset.label;
  let host = button.querySelector(".session-lock-state");
  if (!host) {
    const old = button.querySelector("span");
    host = document.createElement("span");
    host.className = "session-lock-state";
    if (old) old.replaceWith(host);
    else button.appendChild(host);
  }
  if (animate) animateConstraintState(host, locked, label);
  else
    host.innerHTML = `<span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, label)}</span></span>`;
}
function numberSetsEqual(left, right) {
  if (left.size !== right.size) return false;
  for (const value of left) if (!right.has(value)) return false;
  return true;
}
function syncConstraintDraftDirty() {
  const type = $("#constraintType"),
    ent = $("#constraintEntity");
  if (!type || !ent?.value) {
    constraintDraftDirty = false;
    return constraintDraftDirty;
  }
  const obj = (type.value === "teacher" ? data.teachers : data.classes).find(
    (item) => item.id === Number(ent.value),
  ),
    saved = new Set((obj?.unavailable || []).map(Number)),
    current = new Set(
      [...document.querySelectorAll("[data-cslot].blocked")].map((cell) =>
        Number(cell.dataset.cslot),
      ),
    );
  constraintDraftDirty = !numberSetsEqual(saved, current);
  return constraintDraftDirty;
}
function syncGlobalLocksDraftDirty() {
  const saved = new Set(selectedLockSlots().map(Number)),
    current = new Set(
      [...document.querySelectorAll("[data-global-slot].is-locked")].map(
        (button) => Number(button.dataset.globalSlot),
      ),
    );
  globalLocksDraftDirty = !numberSetsEqual(saved, current);
  return globalLocksDraftDirty;
}
function toggleConstraintCell(cell) {
  // A school-wide lock is authoritative. It can only be changed in the
  // school-wide lock editor, not by the teacher/class availability grid.
  if (constraintSaveInFlight || cell.classList.contains("global-locked")) return;
  const blocked = !cell.classList.contains("blocked");
  cell.classList.toggle("blocked", blocked);
  cell.setAttribute("aria-pressed", blocked ? "true" : "false");
  animateConstraintState(cell, blocked, blocked ? "Tiết tránh" : "Có thể xếp");
  syncConstraintDraftDirty();
}
function ensureGlobalSessionLockPanel() {
  const section = $("#constraints");
  if (!section) return null;
  let panel = $("#globalSessionLocks");
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "globalSessionLocks";
  panel.className = "global-session-locks";
  panel.innerHTML =
    '<h2>Khóa lịch toàn trường / theo khối</h2><p>Chọn phạm vi để khóa nguyên buổi hoặc từng tiết. Khóa theo khối áp dụng cho mọi lớp thuộc khối, kể cả lớp thêm sau này. Khóa toàn trường luôn có hiệu lực với tất cả các khối.</p><div class="constraint-toolbar"><label for="lockScope">Phạm vi khóa</label><select id="lockScope" onchange="changeLockScope(this)"></select></div><div id="sessionLockGrid" class="session-lock-grid"></div><div class="global-slot-lock-title"><h3>Khóa từng tiết</h3></div><div id="globalSlotLockGrid" class="global-slot-lock-grid"></div><div class="row end"><button class="btn" type="button" onclick="saveGlobalSessionLocks(this)">Lưu khóa lịch</button></div>';
  const toolbar = section.querySelector(".constraint-toolbar");
  section.insertBefore(panel, toolbar);
  return panel;
}
function toggleSessionLock(button) {
  if (globalSaveInFlight || button.disabled) return;
  const locked = !button.classList.contains("is-locked"),
    key = Number(button.dataset.sessionLock);
  document
    .querySelectorAll(`[data-global-session="${key}"]`)
    .forEach((slot) => setGlobalSlotLockState(slot, locked));
  syncSessionLockButton(button);
  syncGlobalLocksDraftDirty();
}
function syncSessionLockButton(button) {
  if (!button) return;
  const slots = [...document.querySelectorAll(`[data-global-session="${Number(button.dataset.sessionLock)}"]`)];
  const inherited = slots.length > 0 && slots.every(slot => slot.disabled);
  button.dataset.ownLocked = String(slots.length > 0 && slots.every(slot => slot.classList.contains("is-locked")));
  button.dataset.inherited = String(inherited);
  button.disabled = inherited;
  button.title = inherited ? "Buổi đã khóa toàn trường; chọn phạm vi Toàn trường để mở khóa" : "Khóa hoặc mở các tiết của phạm vi đang chọn";
  setSessionLockState(button, slots.length > 0 && slots.every(slot => slot.disabled || slot.classList.contains("is-locked")));
}
function toggleGlobalSlotLock(button) {
  if (globalSaveInFlight || button.disabled) return;
  const selected = !button.classList.contains("is-locked");
  setGlobalSlotLockState(button, selected);
  syncSessionLockButton(document.querySelector(`[data-session-lock="${Number(button.dataset.globalSession)}"]`));
  syncGlobalLocksDraftDirty();
}
function renderGlobalSessionLocks() {
  if (!ensureGlobalSessionLockPanel()) return;
  const scope = $("#lockScope"), grades = data.grades || [];
  if (globalLockGradeId != null && !grades.some((grade) => grade.id === globalLockGradeId)) {
    globalLockGradeId = null;
    globalLocksDraftDirty = false;
  }
  scope.innerHTML = '<option value="all">Toàn trường</option>' + grades
    .map((grade) => `<option value="${grade.id}">Theo khối: ${esc(grade.name)}</option>`).join("");
  scope.value = globalLockGradeId == null ? "all" : String(globalLockGradeId);
  scope.disabled = globalSaveInFlight || constraintSaveInFlight;
  const grid = $("#sessionLockGrid"),
    slotGrid = $("#globalSlotLockGrid"),
    blocked = new Set(selectedLockSlots().map(Number)),
    inherited = new Set(globalLockGradeId == null ? [] : (data.project.blocked_slots || []).map(Number)),
    days = data.project.days,
    sessions = data.project.sessions,
    pps = data.project.periods,
    ppd = sessions * pps,
    dayNames = [
      "Thứ 2",
      "Thứ 3",
      "Thứ 4",
      "Thứ 5",
      "Thứ 6",
      "Thứ 7",
      "Chủ nhật",
    ];
  let html = "";
  for (let day = 0; day < days; day++)
    for (let session = 0; session < sessions; session++) {
      const key = day * sessions + session,
        start = day * ppd + session * pps,
        locked = Array.from({ length: pps }, (_, index) => start + index).every(
          (slot) => blocked.has(slot) || inherited.has(slot),
        ),
        sessionName =
          sessions === 1
            ? "Cả buổi"
            : session === 0
              ? "Buổi sáng"
              : "Buổi chiều";
      html += `<button type="button" class="session-lock ${locked ? "is-locked" : ""}" data-session-lock="${key}" data-label="${sessionName}" onclick="toggleSessionLock(this)"><b>${dayNames[day]}</b><span class="session-lock-state"><span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, sessionName)}</span></span></span></button>`;
    }
  grid.innerHTML = html;
  slotGrid.style.gridTemplateColumns = `90px repeat(${days},minmax(90px,1fr))`;
  let slotHtml =
    '<div class="slot-head">Tiết</div>' +
    dayNames
      .slice(0, days)
      .map((day) => `<div class="slot-head">${day}</div>`)
      .join("");
  for (let session = 0; session < sessions; session++)
    for (let period = 0; period < pps; period++) {
      slotHtml += `<div class="slot-period">${sessions > 1 ? (session === 0 ? "S" : "C") + " " : ""}${period + 1}</div>`;
      for (let day = 0; day < days; day++) {
        const slot = day * ppd + session * pps + period,
          key = day * sessions + session,
          locked = blocked.has(slot), isInherited = inherited.has(slot);
        slotHtml += `<button type="button" class="global-slot-lock ${locked ? "is-locked" : ""}" ${isInherited ? 'disabled title="Tiết đã khóa toàn trường; chọn phạm vi Toàn trường để mở khóa"' : ""} data-global-slot="${slot}" data-global-session="${key}" onclick="toggleGlobalSlotLock(this)"><span class="constraint-state-stage"><span class="constraint-state-content ${locked || isInherited ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked || isInherited, isInherited ? "Khóa chung" : locked ? "Đã khóa" : "Cho phép")}</span></span></button>`;
      }
    }
  slotGrid.innerHTML = slotHtml;
  grid.querySelectorAll("[data-session-lock]").forEach(syncSessionLockButton);
}
async function saveGlobalSessionLocks(button) {
  if (constraintSaveInFlight || globalSaveInFlight) {
    showInlineActionFeedback(button, "Đang lưu thay đổi. Vui lòng chờ một chút.", "info", 2400);
    return;
  }
  const sessions = [
    ...document.querySelectorAll('[data-session-lock][data-own-locked="true"]'),
  ].map((button) => Number(button.dataset.sessionLock)),
    slots = [...document.querySelectorAll("[data-global-slot].is-locked")].map(
      (button) => Number(button.dataset.globalSlot),
    );
  setInlineActionState(button, "loading", {
    idle: "Lưu khóa lịch",
    loading: "Đang lưu...",
  });
  globalSaveInFlight = true;
  $("#lockScope").disabled = true;
  try {
    const { response: r, result, cancelled } =
      await postJsonWithDisplacementConfirmation(
        `/api/projects/${PROJECT_ID}/session-locks`,
        { grade_id: globalLockGradeId, sessions, slots },
        { title: "Xác nhận khóa lịch", confirmText: "Lưu và đưa về khay" },
      );
    if (cancelled) {
      setInlineActionState(button, "idle", { idle: "Lưu khóa lịch" });
      showInlineActionFeedback(
        button,
        "Đã hủy. Lịch hiện tại chưa bị thay đổi.",
        "info",
        3200,
      );
      return;
    }
    if (r.ok) {
      globalLocksDraftDirty = false;
      try {
        await refresh(true);
      } catch {
        setInlineActionState(
          button,
          "success",
          { idle: "Lưu khóa lịch", success: "Đã lưu" },
          2200,
        );
        showInlineActionFeedback(
          button,
          "Khóa lịch đã được lưu trên máy chủ nhưng chưa tải lại được dữ liệu mới. Hãy tải lại trang nếu lịch chưa cập nhật đầy đủ.",
          "warning",
          6500,
        );
        return;
      }
      setInlineActionState(
        button,
        "success",
        { idle: "Lưu khóa lịch", success: "Đã lưu" },
        1700,
      );
      showInlineActionFeedback(
        button,
        result.removed
          ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.`
          : "Khóa lịch đã được lưu.",
        "success",
        2800,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: "Lưu khóa lịch", error: "Chưa lưu được" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể lưu khóa lịch."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Lưu khóa lịch", error: "Chưa lưu được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  } finally {
    globalSaveInFlight = false;
    if ($("#lockScope")) $("#lockScope").disabled = false;
  }
}
function renderConstraintSelectors({ force = false } = {}) {
  if (!force && constraintDraftDirty) return;
  if (!globalLocksDraftDirty || !$("#globalSessionLocks"))
    renderGlobalSessionLocks();
  const type = $("#constraintType"),
    ent = $("#constraintEntity");
  if (!type || !ent) return;
  const rows = type.value === "teacher" ? data.teachers : data.classes;
  const old = ent.value;
  ent.innerHTML = opts(rows);
  if ([...ent.options].some((o) => o.value === old)) ent.value = old;
  type.dataset.previousValue = type.value;
  ent.dataset.previousValue = ent.value;
  type.onchange = async () => {
    const previous = type.dataset.previousValue || "teacher";
    if (constraintDraftDirty) {
      const confirmed = await confirmAction(
        "Bạn có thay đổi tiết tránh chưa lưu. Đổi loại đối tượng sẽ bỏ các thay đổi đó.",
        { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
      );
      if (!confirmed) {
        type.value = previous;
        return;
      }
      constraintDraftDirty = false;
    }
    type.dataset.previousValue = type.value;
    renderConstraintSelectors({ force: true });
  };
  ent.onchange = async () => {
    const previous = ent.dataset.previousValue || "";
    if (constraintDraftDirty) {
      const confirmed = await confirmAction(
        "Bạn có thay đổi tiết tránh chưa lưu. Đổi giáo viên/lớp sẽ bỏ các thay đổi đó.",
        { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
      );
      if (!confirmed) {
        ent.value = previous;
        return;
      }
      constraintDraftDirty = false;
    }
    ent.dataset.previousValue = ent.value;
    renderConstraintGrid();
  };
  renderConstraintGrid();
}
function renderConstraintGrid() {
  const box = $("#constraintGrid"),
    type = $("#constraintType"),
    ent = $("#constraintEntity");
  if (!box) return;
  if (!ent?.value) {
    box.innerHTML =
      '<div class="empty-state">Hãy thêm giáo viên hoặc lớp học trước khi thiết lập tiết tránh.</div>';
    return;
  }
  const obj = (type.value === "teacher" ? data.teachers : data.classes).find(
    (x) => x.id === Number(ent.value),
  );
  const blocked = new Set((obj?.unavailable || []).map(Number)),
    globalBlocked = new Set((data.project.blocked_slots || []).map(Number)),
    gradeBlocked = new Set(type.value === "class"
      ? ((data.grades || []).find((grade) => grade.id === obj?.grade_id)?.blocked_slots || []).map(Number)
      : []),
    days = data.project.days,
    pps = data.project.periods,
    sessions = data.project.sessions;
  let h = `<p class="constraint-global-lock-note">Ô <b>Khóa chung</b> và <b>Khóa khối</b> được kế thừa từ bảng khóa lịch phía trên. Muốn mở, chọn phạm vi tương ứng ở bảng phía trên rồi bấm <b>Lưu khóa lịch</b>.</p><div class="timetable constraint-timetable" style="grid-template-columns:90px repeat(${days},minmax(110px,1fr))"><div class="cell head">Tiết</div>`;
  for (let d = 0; d < days; d++)
    h += `<div class="cell head">${["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][d]}</div>`;
  for (let s = 0; s < sessions; s++)
    for (let p = 0; p < pps; p++) {
      h += `<div class="cell period">${sessions > 1 ? (s ? "C" : "S") + " " : ""}${p + 1}</div>`;
      for (let d = 0; d < days; d++) {
        const slot = d * (sessions * pps) + s * pps + p,
          isBlocked = blocked.has(slot),
          isGlobal = globalBlocked.has(slot), isGrade = gradeBlocked.has(slot),
          isInherited = isGlobal || isGrade,
          label = isGlobal ? "Khóa chung" : isGrade ? "Khóa khối" : (isBlocked ? "Tiết tránh" : "Có thể xếp"),
          interactive = isInherited ? 'aria-disabled="true" tabindex="-1" title="Tiết đã khóa theo phạm vi; mở khóa ở bảng phía trên"' :
            `role="button" tabindex="0" aria-pressed="${isBlocked ? "true" : "false"}" onclick="toggleConstraintCell(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();toggleConstraintCell(this)}"`;
        // Keep the entity-specific .blocked flag even when a global lock
        // overlaps it, so saving does not erase existing teacher/class rules.
        h += `<div ${interactive} data-cslot="${slot}" class="cell available constraint-state-cell ${isBlocked ? "blocked" : ""} ${isInherited ? "global-locked" : ""}"><span class="constraint-state-stage"><span class="constraint-state-content ${isInherited || isBlocked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(isInherited || isBlocked, label)}</span></span></div>`;
      }
    }
  h += "</div>";
  box.innerHTML = h;
}
async function saveConstraints(button) {
  if (constraintSaveInFlight || globalSaveInFlight) {
    showInlineActionFeedback(button, "Đang lưu thay đổi. Vui lòng chờ một chút.", "info", 2400);
    return;
  }
  const entity = $("#constraintEntity");
  if (!entity?.value) {
    setInlineActionState(
      button,
      "error",
      { idle: "Lưu ràng buộc", error: "Chọn đối tượng" },
      1800,
    );
    showInlineActionFeedback(
      button,
      "Hãy chọn giáo viên hoặc lớp học trước.",
      "error",
      4200,
    );
    return;
  }
  const slots = [...document.querySelectorAll("[data-cslot].blocked")].map(
    (x) => Number(x.dataset.cslot),
  );
  setInlineActionState(button, "loading", {
    idle: "Lưu ràng buộc",
    loading: "Đang lưu...",
  });
  constraintSaveInFlight = true;
  [$("#constraintType"), $("#constraintEntity")].forEach((el) => { if (el) el.disabled = true; });
  try {
    const { response: r, result, cancelled } =
      await postJsonWithDisplacementConfirmation(
        `/api/projects/${PROJECT_ID}/constraints`,
        {
          entity_type: $("#constraintType").value,
          entity_id: Number(entity.value),
          slots,
        },
        { title: "Xác nhận tiết tránh", confirmText: "Lưu và đưa về khay" },
      );
    if (cancelled) {
      setInlineActionState(button, "idle", { idle: "Lưu ràng buộc" });
      showInlineActionFeedback(
        button,
        "Đã hủy. Lịch hiện tại chưa bị thay đổi.",
        "info",
        3200,
      );
      return;
    }
    if (r.ok) {
      constraintDraftDirty = false;
      try {
        await refresh(true);
      } catch {
        setInlineActionState(
          button,
          "success",
          { idle: "Lưu ràng buộc", success: "Đã lưu" },
          2200,
        );
        showInlineActionFeedback(
          button,
          "Tiết tránh đã được lưu trên máy chủ nhưng chưa tải lại được dữ liệu mới. Hãy tải lại trang nếu lịch chưa cập nhật đầy đủ.",
          "warning",
          6500,
        );
        return;
      }
      setInlineActionState(
        button,
        "success",
        { idle: "Lưu ràng buộc", success: "Đã lưu" },
        1700,
      );
      showInlineActionFeedback(
        button,
        result.removed
          ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.`
          : "Đã lưu tiết tránh.",
        "success",
        2800,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: "Lưu ràng buộc", error: "Chưa lưu được" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể lưu tiết tránh."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Lưu ràng buộc", error: "Chưa lưu được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  } finally {
    constraintSaveInFlight = false;
    [$("#constraintType"), $("#constraintEntity")].forEach((el) => { if (el) el.disabled = false; });
  }
}
