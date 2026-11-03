/* Constraint editor and grade/session lock handling. */
let constraintSaveInFlight = false;
let globalSaveInFlight = false;
let globalLockGradeId = null;
function syncConstraintSaveControls() {
  const scope = $("#lockScope");
  const lockDisabled = globalSaveInFlight || constraintSaveInFlight || globalLockGradeId == null;
  if (scope) scope.disabled = lockDisabled;
  [$("#gradeLockSaveButton"), $("#gradeLockResetButton")].forEach((button) => {
    if (button) button.disabled = lockDisabled;
  });
  [$("#constraintType"), $("#constraintEntity")].forEach((el) => {
    if (el) el.disabled = constraintSaveInFlight;
  });
}
async function resetConstraintSection(section, button) {
  if (constraintSaveInFlight || globalSaveInFlight) {
    showToast("Đang lưu thay đổi. Vui lòng chờ hoàn tất.", "info");
    return;
  }
  const isEntity = section === "entity",
    entityType = $("#constraintType")?.value,
    entityId = $("#constraintEntity")?.value,
    gradeId = globalLockGradeId;
  if (isEntity && !entityId) {
    showToast("Hãy chọn giáo viên hoặc lớp học trước.", "warning");
    return;
  }
  if (!isEntity && gradeId == null) {
    showToast("Hãy thêm và chọn khối lớp trước khi đặt lại khóa lịch.", "warning");
    return;
  }
  const name = isEntity
    ? (entityType === "teacher" ? data.teachers : data.classes).find(row => row.id === Number(entityId))?.name
    : (data.grades || []).find(row => row.id === gradeId)?.name;
  const confirmed = await confirmAction(
    isEntity
      ? `Xóa toàn bộ ngày nghỉ / tiết tránh của ${entityType === "teacher" ? "giáo viên" : "lớp"} ${name}? Khóa khối vẫn có hiệu lực. Thay đổi sẽ được lưu ngay.`
      : `Xóa toàn bộ khóa buổi / tiết trong phạm vi ${name}? Khóa ở các phạm vi khác được giữ nguyên. Thay đổi sẽ được lưu ngay.`,
    { title: isEntity ? "Reset tiết tránh" : "Reset khóa lịch", confirmText: "Reset" },
  );
  if (!confirmed) return;
  // Never apply consent to a different selector or scope after the dialog closes.
  if ((isEntity && (entityType !== $("#constraintType")?.value || entityId !== $("#constraintEntity")?.value))
      || (!isEntity && gradeId !== globalLockGradeId)) {
    showToast("Phạm vi đã thay đổi. Hãy chọn lại và bấm Reset.", "info");
    return;
  }
  if (isEntity) await saveConstraints(button, { reset: true });
  else await saveGlobalSessionLocks(button, { reset: true });
}
function selectedLockSlots() {
  return (data.grades || []).find((grade) => grade.id === globalLockGradeId)?.blocked_slots || [];
}
async function changeLockScope(select) {
  if (globalSaveInFlight || constraintSaveInFlight) {
    select.value = globalLockGradeId == null ? "" : String(globalLockGradeId);
    return;
  }
  if (globalLocksDraftDirty && !(await confirmAction(
    "Bạn có thay đổi khóa lịch chưa lưu. Đổi phạm vi sẽ bỏ các thay đổi đó.",
    { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
  ))) {
    select.value = globalLockGradeId == null ? "" : String(globalLockGradeId);
    return;
  }
  const gradeId = Number(select.value);
  if (!(data.grades || []).some(grade => grade.id === gradeId)) return;
  globalLockGradeId = gradeId;
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
  const label = button.dataset.label;
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
  // Inherited grade locks are changed in the grade lock editor.
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
    '<h2>Khóa lịch theo khối</h2><p>Chọn khối để khóa nguyên buổi hoặc từng tiết. Khóa áp dụng cho mọi lớp thuộc khối đã chọn, kể cả lớp thêm sau này.</p><div class="constraint-toolbar"><label for="lockScope">Khối lớp</label><select id="lockScope" onchange="changeLockScope(this)"></select></div><div id="sessionLockGrid" class="session-lock-grid"></div><div class="global-slot-lock-title"><h3>Khóa từng tiết</h3></div><div id="globalSlotLockGrid" class="global-slot-lock-grid"></div><div class="row end"><button id="gradeLockResetButton" class="btn btn-danger" type="button" onclick="resetConstraintSection(\'locks\',this)">Reset khóa lịch</button><button id="gradeLockSaveButton" class="btn" type="button" onclick="saveGlobalSessionLocks(this)">Lưu khóa lịch</button></div>';
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
  button.dataset.ownLocked = String(slots.length > 0 && slots.every(slot => slot.classList.contains("is-locked")));
  button.title = "Khóa hoặc mở các tiết của khối đang chọn";
  setSessionLockState(button, button.dataset.ownLocked === "true");
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
  if (!grades.some((grade) => grade.id === globalLockGradeId)) {
    globalLockGradeId = grades[0]?.id ?? null;
    globalLocksDraftDirty = false;
  }
  scope.innerHTML = grades.length ? grades
    .map((grade) => `<option value="${grade.id}">Theo khối: ${esc(grade.name)}</option>`).join("")
    : '<option value="">Chưa có khối lớp</option>';
  scope.value = globalLockGradeId == null ? "" : String(globalLockGradeId);
  syncConstraintSaveControls();
  const grid = $("#sessionLockGrid"),
    slotGrid = $("#globalSlotLockGrid"),
    blocked = new Set(selectedLockSlots().map(Number)),
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
  if (globalLockGradeId == null) {
    grid.innerHTML = '<div class="empty-state">Hãy thêm khối lớp ở mục Khối / nhóm trước khi khóa lịch.</div>';
    slotGrid.innerHTML = "";
    return;
  }
  let html = "";
  for (let day = 0; day < days; day++)
    for (let session = 0; session < sessions; session++) {
      const key = day * sessions + session,
        start = day * ppd + session * pps,
        locked = Array.from({ length: pps }, (_, index) => start + index).every(
          (slot) => blocked.has(slot),
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
          locked = blocked.has(slot);
        slotHtml += `<button type="button" class="global-slot-lock ${locked ? "is-locked" : ""}" data-global-slot="${slot}" data-global-session="${key}" onclick="toggleGlobalSlotLock(this)"><span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, locked ? "Đã khóa" : "Cho phép")}</span></span></button>`;
      }
    }
  slotGrid.innerHTML = slotHtml;
  grid.querySelectorAll("[data-session-lock]").forEach(syncSessionLockButton);
}
async function saveGlobalSessionLocks(button, { reset = false } = {}) {
  if (constraintSaveInFlight || globalSaveInFlight) {
    showInlineActionFeedback(button, "Đang lưu thay đổi. Vui lòng chờ một chút.", "info", 2400);
    return;
  }
  if (globalLockGradeId == null) {
    showInlineActionFeedback(button, "Hãy thêm và chọn khối lớp trước.", "warning", 3000);
    return;
  }
  const idleLabel = reset ? "Reset khóa lịch" : "Lưu khóa lịch";
  const sessions = reset ? [] : [
    ...document.querySelectorAll('[data-session-lock][data-own-locked="true"]'),
  ].map((button) => Number(button.dataset.sessionLock)),
    slots = reset ? [] : [...document.querySelectorAll("[data-global-slot].is-locked")].map(
      (button) => Number(button.dataset.globalSlot),
    );
  setInlineActionState(button, "loading", {
    idle: idleLabel,
    loading: "Đang lưu...",
  });
  globalSaveInFlight = true;
  syncConstraintSaveControls();
  try {
    const { response: r, result, cancelled } =
      await postJsonWithDisplacementConfirmation(
        `/api/projects/${PROJECT_ID}/session-locks`,
        { grade_id: globalLockGradeId, sessions, slots },
        { title: "Xác nhận khóa lịch", confirmText: "Lưu và đưa về khay" },
      );
    if (cancelled) {
      setInlineActionState(button, "idle", { idle: idleLabel });
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
          { idle: idleLabel, success: "Đã lưu" },
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
        { idle: idleLabel, success: "Đã lưu" },
        1700,
      );
      showInlineActionFeedback(
        button,
        result.removed
          ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.`
          : reset ? "Đã reset khóa lịch trong phạm vi đang chọn." : "Khóa lịch đã được lưu.",
        "success",
        2800,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: idleLabel, error: "Chưa lưu được" },
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
      { idle: idleLabel, error: "Chưa lưu được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  } finally {
    globalSaveInFlight = false;
    syncConstraintSaveControls();
  }
}
function renderConstraintSelectors({ force = false } = {}) {
  // Each editor owns its draft; unsaved availability must not hide saved locks.
  if (!globalLocksDraftDirty || !$("#globalSessionLocks"))
    renderGlobalSessionLocks();
  if (!force && constraintDraftDirty) {
    renderConstraintGrid({ preserveDraft: true });
    return;
  }
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
function renderConstraintGrid({ preserveDraft = false } = {}) {
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
  const blocked = preserveDraft
    ? new Set([...box.querySelectorAll("[data-cslot].blocked")].map((cell) => Number(cell.dataset.cslot)))
    : new Set((obj?.unavailable || []).map(Number)),
    gradeBlocked = new Set(type.value === "class"
      ? ((data.grades || []).find((grade) => grade.id === obj?.grade_id)?.blocked_slots || []).map(Number)
      : []),
    days = data.project.days,
    pps = data.project.periods,
    sessions = data.project.sessions;
  let h = `<p class="constraint-global-lock-note">Ô <b>Khóa khối</b> của lớp được kế thừa từ bảng khóa lịch phía trên. Muốn mở, chọn khối tương ứng rồi bấm <b>Lưu khóa lịch</b>.</p><div class="timetable constraint-timetable" style="grid-template-columns:90px repeat(${days},minmax(110px,1fr))"><div class="cell head">Tiết</div>`;
  for (let d = 0; d < days; d++)
    h += `<div class="cell head">${["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][d]}</div>`;
  for (let s = 0; s < sessions; s++)
    for (let p = 0; p < pps; p++) {
      h += `<div class="cell period">${sessions > 1 ? (s ? "C" : "S") + " " : ""}${p + 1}</div>`;
      for (let d = 0; d < days; d++) {
        const slot = d * (sessions * pps) + s * pps + p,
          isBlocked = blocked.has(slot),
          isInherited = gradeBlocked.has(slot),
          label = isInherited ? "Khóa khối" : (isBlocked ? "Tiết tránh" : "Có thể xếp"),
          interactive = isInherited ? 'aria-disabled="true" tabindex="-1" title="Tiết đã khóa theo phạm vi; mở khóa ở bảng phía trên"' :
            `role="button" tabindex="0" aria-pressed="${isBlocked ? "true" : "false"}" onclick="toggleConstraintCell(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();toggleConstraintCell(this)}"`;
        // Keep the entity-specific .blocked flag even when a grade lock
        // overlaps it, so saving does not erase existing teacher/class rules.
        h += `<div ${interactive} data-cslot="${slot}" class="cell available constraint-state-cell ${isBlocked ? "blocked" : ""} ${isInherited ? "global-locked" : ""}"><span class="constraint-state-stage"><span class="constraint-state-content ${isInherited || isBlocked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(isInherited || isBlocked, label)}</span></span></div>`;
      }
    }
  h += "</div>";
  box.innerHTML = h;
}
async function saveConstraints(button, { reset = false } = {}) {
  const idleLabel = reset ? "Reset tiết tránh" : "Lưu ràng buộc";
  if (constraintSaveInFlight || globalSaveInFlight) {
    showInlineActionFeedback(button, "Đang lưu thay đổi. Vui lòng chờ một chút.", "info", 2400);
    return;
  }
  const entity = $("#constraintEntity");
  if (!entity?.value) {
    setInlineActionState(
      button,
      "error",
      { idle: idleLabel, error: "Chọn đối tượng" },
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
  const slots = reset ? [] : [...document.querySelectorAll("[data-cslot].blocked")].map(
    (x) => Number(x.dataset.cslot),
  );
  setInlineActionState(button, "loading", {
    idle: idleLabel,
    loading: "Đang lưu...",
  });
  constraintSaveInFlight = true;
  syncConstraintSaveControls();
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
      setInlineActionState(button, "idle", { idle: idleLabel });
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
          { idle: idleLabel, success: "Đã lưu" },
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
        { idle: idleLabel, success: "Đã lưu" },
        1700,
      );
      showInlineActionFeedback(
        button,
        result.removed
          ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.`
          : reset ? "Đã reset tiết tránh của đối tượng đang chọn." : "Đã lưu tiết tránh.",
        "success",
        2800,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: idleLabel, error: "Chưa lưu được" },
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
      { idle: idleLabel, error: "Chưa lưu được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  } finally {
    constraintSaveInFlight = false;
    syncConstraintSaveControls();
  }
}
