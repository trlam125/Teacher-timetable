/* Schedule rendering, conflict display, generation and tray UI. */
function computeScheduleConflicts() {
  const conflictsByLessonId = new Map();
  const validation = data?.schedule_validation || {};

  const addLessonConflict = (lessonId, reason) => {
    const id = Number(lessonId);
    if (!Number.isFinite(id)) return;
    if (!conflictsByLessonId.has(id)) conflictsByLessonId.set(id, []);
    const reasons = conflictsByLessonId.get(id);
    const message = String(reason || "Tiết học vi phạm ràng buộc thời khóa biểu.");
    if (!reasons.includes(message)) reasons.push(message);
  };

  // Backend is authoritative for all hard constraints. In particular, aggregate
  // limits such as max periods/day and max consecutive periods are evaluated as
  // a minimal invalid subset, so the browser must not recompute and over-mark
  // the whole day/run.
  const detailed = validation.invalid_lesson_conflicts || [];
  if (detailed.length) {
    for (const issue of detailed) {
      addLessonConflict(issue.lesson_id, issue.message);
    }
  } else {
    // Backward-compatible fallback for a response that only contains ids.
    for (const lessonId of validation.invalid_lesson_ids || []) {
      addLessonConflict(lessonId, "Tiết học vi phạm ràng buộc thời khóa biểu.");
    }
  }

  for (const issue of validation.required_double_conflicts || []) {
    const reason =
      issue.message || "Phân công chưa đúng mẫu bắt buộc tiết đôi.";
    for (const lessonId of issue.lesson_ids || []) {
      addLessonConflict(lessonId, reason);
    }
  }

  return { conflictsByLessonId };
}

async function generateSchedule(allowRebuild = false) {
  const modal = $("#aiProgressModal");
  const bar = $("#aiProgressBar");
  const subtitle = $("#aiProgressSubtitle");

  function setProgress(state, statusText) {
    if (bar) {
      const running = state === "running";
      bar.classList.toggle("is-indeterminate", running);
      if (running) {
        bar.style.width = "34%";
        bar.removeAttribute("aria-valuenow");
      } else {
        bar.style.width = state === "complete" ? "100%" : "0%";
        if (state === "complete") bar.setAttribute("aria-valuenow", "100");
        else bar.removeAttribute("aria-valuenow");
      }
    }
    if (subtitle && statusText) subtitle.textContent = statusText;
  }

  setScheduleActionState("loading");
  setScheduleFeedback("", "info", 0);

  if (modal && typeof modal.showModal === "function") {
    modal.showModal();
    setProgress(
      "running",
      "Đang kiểm tra ràng buộc và chạy solver. Thời gian xử lý phụ thuộc độ phức tạp của lịch...",
    );
  }

  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/generate`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ allow_rebuild: allowRebuild }),
    });
    const j = await readApiResponse(r);

    if (r.ok) {
      setProgress("complete", "Đã xếp xong. Đang đồng bộ thời khóa biểu...");
      setTimeout(async () => {
        if (modal) modal.close();
        const refreshed = await refreshAfterSuccessfulMutation(
          ["lessons"],
          "Máy chủ đã xếp lịch thành công nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ thời khóa biểu.",
        );
        setScheduleActionState("success", refreshed ? 1400 : 2600);
        setScheduleFeedback(
          refreshed
            ? j.message || "Đã xếp thời khóa biểu thành công."
            : "Đã xếp thời khóa biểu trên máy chủ. Hãy tải lại trang để xem dữ liệu mới.",
          refreshed ? "success" : "warning",
          refreshed ? 2600 : 6500,
        );
        if (refreshed) {
          launchConfetti();
        }
      }, 400);
    } else if (j.requires_confirmation && !allowRebuild) {
      if (modal) modal.close();
      setScheduleActionState("idle");
      if (
        await confirmAction(
          `${apiErrorMessage(j, "Lịch hiện tại cần được xếp lại.")}\n\nBạn có đồng ý xếp lại phần không cố định không?`,
          {
            title: "Xếp lại thời khóa biểu",
            confirmText: "Xếp lại",
          },
        )
      ) {
        return generateSchedule(true);
      }
    } else {
      if (modal) modal.close();
      setScheduleActionState("error", 1800);
      setScheduleFeedback(
        apiErrorMessage(j, "Xếp thời khóa biểu thất bại; lịch hiện tại được giữ nguyên."),
        "error",
        5200,
      );

    }
  } catch (error) {
    if (modal) modal.close();
    setScheduleActionState("error", 1800);
    const message = requestFailureMessage(
      error,
      "Mất kết nối tới máy chủ. Không thể xếp thời khóa biểu.",
    );
    setScheduleFeedback(message, "error", 5200);
  }
}
function goToAssignments() {
  document.querySelector('.nav[data-tab="assignments"]')?.click();
}
function renderManualTray() {
  const tray = $("#unscheduledTray"),
    scheduledBox = $("#scheduledAssignmentTray"),
    coverageBox = $("#assignmentCoverage"),
    vt = $("#viewType"),
    ve = $("#viewEntity");
  if (!tray) return;
  const coverage = data.coverage || {};
  const duplicates = coverage.duplicate_assignments || [];
  const overloaded = coverage.over_capacity_teachers || [];
  const overloadedClasses = coverage.over_capacity_classes || [];
  const groups = [
    ["Giáo viên chưa phân công", coverage.unassigned_teachers || []],
    ["Môn chưa phân công", coverage.unassigned_subjects || []],
    ["Lớp chưa phân công", coverage.unassigned_classes || []],
  ].filter(([, rows]) => rows.length);
  const duplicateHtml = duplicates.length
    ? `<div><b>Không thể xếp do phân công lớp–môn bị trùng</b><p>${duplicates.map((row) => `${esc(row.class_name)} – ${esc(row.subject_name)}: ID ${(row.assignment_ids || []).join(", ")}`).join("; ")}. Hãy xóa hoặc chuyển để mỗi lớp–môn chỉ còn một giáo viên.</p></div>`
    : "";
  const overloadHtml = overloaded.length
    ? `<div><b>Không thể xếp đầy đủ do giáo viên quá tải</b><p>${overloaded.map((row) => `${esc(row.teacher_name)}: ${row.assigned}/${row.capacity} tiết (dư ${row.excess})`).join("; ")}. Hãy giảm/chuyển phân công, tăng giới hạn tiết/ngày hoặc bỏ bớt tiết tránh.</p></div>`
    : "";
  const classOverloadHtml = overloadedClasses.length
    ? `<div><b>Không thể xếp đầy đủ do lớp vượt số ô học</b><p>${overloadedClasses.map((row) => `${esc(row.class_name)}: ${row.assigned}/${row.capacity} tiết (dư ${row.excess})`).join("; ")}. Hãy giảm phân công hoặc bỏ bớt khóa/tiết tránh của lớp.</p></div>`
    : "";
  const gapsHtml = groups.length
    ? `<div><b>Một số dữ liệu chưa được phân công</b><p>Giáo viên, môn hoặc lớp chỉ xuất hiện trên thời khóa biểu sau khi được tạo ở mục Phân công.</p>${groups.map(([label, rows]) => `<div><strong>${label}:</strong> ${rows.map((row) => esc(row.name)).join(", ")}</div>`).join("")}</div>`
    : "";
  const coverageHtml =
    duplicateHtml || overloadHtml || classOverloadHtml || gapsHtml
      ? `<div class="coverage-warning">${duplicateHtml}${overloadHtml}${classOverloadHtml}${gapsHtml}<button class="btn ghost" onclick="goToAssignments()">Đến mục Phân công</button></div>`
      : "";
  if (coverageBox && coverageBox.innerHTML !== coverageHtml) {
    coverageBox.innerHTML = coverageHtml;
  }
  const counts = {};
  data.lessons.forEach(
    (lesson) =>
      (counts[lesson.assignment_id] = (counts[lesson.assignment_id] || 0) + 1),
  );
  let rows = data.assignments.map((item) => ({
    ...item,
    scheduled: counts[item.id] || 0,
    remaining: Math.max(0, item.periods_per_week - (counts[item.id] || 0)),
  }));
  if (vt && ve && vt.value === "class")
    rows = rows.filter((item) => item.class_id === Number(ve.value));
  if (vt && ve && vt.value === "teacher")
    rows = rows.filter((item) => item.teacher_id === Number(ve.value));
  if (vt && ve && vt.value === "subject")
    rows = rows.filter((item) => item.subject_id === Number(ve.value));
  if (!rows.length) {
    if (scheduledBox && scheduledBox.innerHTML !== "") scheduledBox.innerHTML = "";
    const filtered =
      vt &&
      ve &&
      (vt.value === "class" || vt.value === "teacher" || vt.value === "subject");
    const filterLabel =
      vt?.value === "class"
        ? "lớp"
        : vt?.value === "teacher"
          ? "giáo viên"
          : "môn học";
    const emptyHtml = `<div class="empty-state">${filtered ? "Không có phân công cho " + filterLabel + " đang chọn." : "Chưa có phân công để xếp. Hãy tạo phân công lớp – môn – giáo viên – số tiết/tuần."}</div>`;
    if (tray.innerHTML !== emptyHtml) tray.innerHTML = emptyHtml;
    return;
  }
  const scheduled = rows.filter((item) => item.scheduled > 0),
    pending = rows.filter((item) => item.remaining > 0);
  const scheduledHtml = scheduled.length
    ? `<div class="scheduled-label">Đang có trên lịch · bấm thẻ rồi bấm vào khay để thu hồi các tiết chưa cố định của phân công. Các tiết đã cố định luôn được giữ nguyên.</div><div class="scheduled-cards">${scheduled.map((item) => `<div class="scheduled-assignment" data-tap-payload="scheduled-assignment:${item.id}"><div><b>${esc(item.subject_short)}</b><small>${esc(item.class_name)} · ${esc(item.teacher_short)}</small></div><span>${item.scheduled}/${item.periods_per_week} tiết</span></div>`).join("")}</div>`
    : "";
  if (scheduledBox && scheduledBox.innerHTML !== scheduledHtml) {
    scheduledBox.innerHTML = scheduledHtml;
  }
  const hint =
    '<div class="tray-action-hint">Bấm một tiết trên thời khóa biểu hoặc thẻ “đang có trên lịch”, sau đó bấm vào khay này để đưa về khay</div>';
  const pendingHtml = pending.length
    ? pending
      .map(
        (item) =>
          `<div class="tray-lesson" data-tap-payload="assignment:${item.id}"><div><b>${esc(item.subject_short)}</b><small>${esc(item.class_name)} · ${esc(item.teacher_short)}</small></div><span>Còn ${item.remaining}</span></div>`,
      )
      .join("")
    : '<div class="empty-state">Đã xếp đủ tất cả phân công. Nếu muốn chỉnh lại, chọn một tiết trên lịch hoặc thẻ “Đang có trên lịch”, rồi bấm vào khay để thu hồi.</div>';
  const trayHtml = hint + pendingHtml;
  if (tray.innerHTML !== trayHtml) {
    tray.innerHTML = trayHtml;
  }
}

function requiredDoubleBlockLessons(lessonId) {
  const selected = data.lessons.find(
    (lesson) => Number(lesson.id) === Number(lessonId),
  );
  if (!selected) return [];
  const assignment = data.assignments.find(
    (item) => Number(item.id) === Number(selected.assignment_id),
  );
  if (!assignment || assignment.block_mode !== "required_double") {
    return [selected];
  }
  if (!selected.block_id) return [selected];
  return data.lessons
    .filter(
      (lesson) =>
        Number(lesson.assignment_id) === Number(selected.assignment_id) &&
        lesson.block_id === selected.block_id,
    )
    .sort((left, right) => Number(left.slot) - Number(right.slot));
}

function clusteredLessonIds() {
  const marked = new Set();
  const modes = new Map(
    data.assignments.map((item) => [item.id, item.block_mode || "free"]),
  );

  // required_double uses persisted block identity; never infer a pair from
  // neighboring periods. Only true two-lesson blocks get the cluster style.
  const requiredBlocks = new Map();
  for (const lesson of data.lessons) {
    if (modes.get(lesson.assignment_id) !== "required_double" || !lesson.block_id) continue;
    if (!requiredBlocks.has(lesson.block_id)) requiredBlocks.set(lesson.block_id, []);
    requiredBlocks.get(lesson.block_id).push(lesson);
  }
  for (const lessons of requiredBlocks.values()) {
    if (lessons.length === 2) lessons.forEach((lesson) => marked.add(lesson.id));
  }

  // preferred_double remains a visual preference inferred from an isolated
  // adjacent pair because it is deliberately not a hard/persisted block.
  const groups = new Map(),
    pps = data.project.periods,
    ppd = data.project.sessions * pps;
  for (const lesson of data.lessons) {
    if (modes.get(lesson.assignment_id) !== "preferred_double") continue;
    const day = Math.floor(lesson.slot / ppd),
      inside = lesson.slot % ppd,
      session = Math.floor(inside / pps),
      key = `${lesson.assignment_id}:${day}:${session}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(lesson);
  }
  for (const lessons of groups.values()) {
    lessons.sort((left, right) => left.slot - right.slot);
    let run = [];
    const markRun = () => {
      if (run.length === 2) run.forEach((lesson) => marked.add(lesson.id));
      run = [];
    };
    for (const lesson of lessons) {
      if (run.length && lesson.slot !== run[run.length - 1].slot + 1) markRun();
      run.push(lesson);
    }
    markRun();
  }
  return marked;
}

function renderSchedule(preserveScroll = false) {
  const box = $("#scheduleGrid"),
    vt = $("#viewType"),
    ve = $("#viewEntity");
  if (!box || !vt || !ve) return;

  if (vt.value !== "overview" && !ve.value) {
    box.innerHTML =
      '<div class="empty-state">Không tìm thấy đối tượng phù hợp với bộ lọc hiện tại.</div>';
    return;
  }

  const days = data.project.days,
    pps = data.project.periods,
    sessions = data.project.sessions;
  const clustered = clusteredLessonIds();
  const conflicts = computeScheduleConflicts();
  const legend =
    '<div class="schedule-color-legend"><b>Chú thích màu</b><span><i class="schedule-color-swatch"></i>Tiết đơn</span><span><i class="schedule-color-swatch cluster"></i>Block tiết đôi / cặp ưu tiên</span><span><i class="schedule-color-swatch conflict"></i>Ô vi phạm ràng buộc</span></div>';

  // Lập chỉ mục một lần cho mỗi lần render để tránh quét toàn bộ assignments/lessons
  // ở từng ô thời khóa biểu.
  const assignmentById = new Map(
    data.assignments.map((assignment) => [assignment.id, assignment]),
  );
  const selectedEntityId = Number(ve.value);
  const matchesCurrentView = (assignment) => {
    if (!assignment) return false;
    if (vt.value === "overview") return true;
    if (vt.value === "class") return assignment.class_id === selectedEntityId;
    if (vt.value === "subject") return assignment.subject_id === selectedEntityId;
    return assignment.teacher_id === selectedEntityId;
  };
  const sortLessons = (left, right) => {
    const a = assignmentById.get(left.assignment_id);
    const b = assignmentById.get(right.assignment_id);
    return (a?.class_name || "").localeCompare(b?.class_name || "", "vi");
  };
  const lessonsBySlot = new Map();
  for (const lesson of data.lessons) {
    const assignment = assignmentById.get(lesson.assignment_id);
    if (!matchesCurrentView(assignment)) continue;
    if (!lessonsBySlot.has(lesson.slot)) lessonsBySlot.set(lesson.slot, []);
    lessonsBySlot.get(lesson.slot).push(lesson);
  }
  for (const lessons of lessonsBySlot.values()) lessons.sort(sortLessons);

  const renderLessonsForSlot = (slot) => {
    const lessons = lessonsBySlot.get(slot) || [];
    const visibleConflictReasons = [
      ...new Set(
        lessons.flatMap((lesson) =>
          conflicts.conflictsByLessonId.get(lesson.id) || [],
        ),
      ),
    ];
    const slotConflictText = visibleConflictReasons.join("; ");
    const lessonMarkup = lessons
      .map((lesson) =>
        lessonHtml(
          lesson,
          vt.value,
          clustered.has(lesson.id),
          conflicts.conflictsByLessonId.get(lesson.id) || [],
          assignmentById.get(lesson.assignment_id),
        ),
      )
      .join("");
    return {
      hasConflict: visibleConflictReasons.length > 0,
      slotConflictText,
      lessonMarkup,
    };
  };

  const currentTable = box.querySelector(".timetable");
  const totalSlots = days * sessions * pps;
  const isOverview = ["overview", "subject"].includes(vt.value);
  const canUpdateInPlace =
    currentTable &&
    currentTable.classList.contains("overview-timetable") === isOverview &&
    currentTable.querySelectorAll(".cell.available[data-slot]").length ===
    totalSlots;

  if (canUpdateInPlace) {
    for (let slot = 0; slot < totalSlots; slot++) {
      const cell = currentTable.querySelector(
        `.cell.available[data-slot="${slot}"]`,
      );
      if (!cell) continue;
      const { hasConflict, slotConflictText, lessonMarkup } =
        renderLessonsForSlot(slot);

      cell.classList.toggle("has-conflict", hasConflict);
      cell.dataset.conflictTitle = slotConflictText;
      if (cell.title !== slotConflictText) cell.title = slotConflictText;
      if (cell.innerHTML !== lessonMarkup) cell.innerHTML = lessonMarkup;
    }
    return;
  }

  const scrollState = preserveScroll ? captureRefreshScrollState() : null;

  let html = `<div class="timetable ${isOverview ? "overview-timetable" : ""}" style="grid-template-columns:90px repeat(${days},minmax(135px,1fr))"><div class="cell head">Tiết</div>`;
  for (let d = 0; d < days; d++)
    html += `<div class="cell head">${["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][d]}</div>`;
  for (let s = 0; s < sessions; s++) {
    for (let p = 0; p < pps; p++) {
      html += `<div class="cell period">${sessions > 1 ? (s === 0 ? "S" : "C") + " " : ""}${p + 1}</div>`;
      for (let d = 0; d < days; d++) {
        const slot = d * (sessions * pps) + s * pps + p;
        const { hasConflict, slotConflictText, lessonMarkup } =
          renderLessonsForSlot(slot);
        html += `<div class="cell available ${hasConflict ? "has-conflict" : ""}" data-slot="${slot}" data-conflict-title="${esc(slotConflictText)}" title="${esc(slotConflictText)}">${lessonMarkup}</div>`;
      }
    }
  }
  html += "</div>";
  box.innerHTML = legend + html;

  if (scrollState) {
    restoreRefreshScrollState(scrollState);
  }
}

function lessonActionIcon(type) {
  const icons = {
    pin: '<svg class="lesson-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 17v5"></path><path d="M5 3h14"></path><path d="M6 3l2 7-3 4h14l-3-4 2-7"></path></svg>',
    unlock: '<svg class="lesson-action-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2"></rect><path d="M9 10V7a4 4 0 0 1 7.5-2"></path></svg>',
    lock: '<svg class="lesson-lock-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path></svg>',
    close: '<svg class="lesson-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12"></path><path d="M18 6 6 18"></path></svg>',
  };
  return icons[type] || "";
}

function lessonHtml(
  l,
  view,
  inCluster = false,
  conflictReasons = [],
  assignment = null,
) {
  const a = assignment || data.assignments.find((x) => x.id === l.assignment_id);
  if (!a) return "";
  const detail = `${a.class_name} · ${a.teacher_short}`;
  const fixesWholeBlock = a.block_mode === "required_double" && inCluster;
  const fixTitle = fixesWholeBlock
    ? "Cố định cả block tiết đôi"
    : "Cố định tiết này";
  const unfixTitle = fixesWholeBlock
    ? "Bỏ cố định cả block tiết đôi"
    : "Bỏ cố định tiết này";
  const actions =
    window.READ_ONLY
      ? ""
      : l.locked
        ? `<button class="lesson-remove" title="${unfixTitle}" aria-label="${unfixTitle}" onclick="event.stopPropagation();unfixGroup(${a.id},${l.slot},this)">${lessonActionIcon("unlock")}</button>`
        : `<button class="lesson-pin" title="${fixTitle}" aria-label="${fixTitle}" onclick="event.stopPropagation();setFixed(${a.id},${l.slot},this)">${lessonActionIcon("pin")}</button><button class="lesson-remove" title="${fixesWholeBlock ? "Gỡ cả block tiết đôi" : "Gỡ tiết"}" aria-label="${fixesWholeBlock ? "Gỡ cả block tiết đôi khỏi thời khóa biểu" : "Gỡ tiết khỏi thời khóa biểu"}" onclick="event.stopPropagation();removeLesson(${l.id})">${lessonActionIcon("close")}</button>`;
  const tapPayload =
    !window.READ_ONLY && !l.locked
      ? ` data-tap-payload="${l.id}"`
      : "";
  const normalizedConflictReasons = Array.isArray(conflictReasons)
    ? conflictReasons.filter(Boolean)
    : conflictReasons
      ? [String(conflictReasons)]
      : [];
  const conflictText = [...new Set(normalizedConflictReasons)].join("; ");
  const conflictBadge = conflictText
    ? `<button type="button" class="conflict-badge" title="${esc(conflictText)}" aria-label="Xem ${normalizedConflictReasons.length} xung đột" data-conflict-message="${esc(conflictText)}">!</button>`
    : "";
  return `<div class="lesson ${["overview", "subject"].includes(view) ? "lesson-overview" : ""} ${inCluster ? "lesson-cluster" : ""} ${conflictText ? "has-conflict" : ""} ${actions ? "lesson-has-actions" : ""}"${tapPayload} title="${esc(conflictText)}"><b>${esc(a.subject_short)}</b><small>${esc(detail)}</small>${l.locked ? ` <span class="lesson-lock-status" title="Tiết cố định" aria-label="Tiết cố định">${lessonActionIcon("lock")}</span>` : ""}${conflictBadge}${actions}</div>`;
}

function showToast(message, type = "info", duration = 3200) {
  if (!message) return;
  if (
    window.OperationStatus &&
    typeof window.OperationStatus.notify === "function"
  ) {
    window.OperationStatus.notify(message, type);
    return;
  }
  let container = document.getElementById("appToastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "appToastContainer";
    container.className = "app-toast-container";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  toast.className = `app-toast is-${type}`;
  const icon =
    type === "error" || type === "warning"
      ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
      : type === "success"
        ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>'
        : '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  toast.innerHTML = `<span class="app-toast-icon">${icon}</span><span class="app-toast-text">${esc(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("is-hiding");
    setTimeout(() => {
      if (toast.isConnected) toast.remove();
    }, 300);
  }, duration);
}

document.addEventListener("click", (event) => {
  const badge = event.target.closest(".conflict-badge[data-conflict-message]");
  if (!badge) return;
  event.preventDefault();
  event.stopPropagation();
  showToast(
    badge.dataset.conflictMessage || "Xung đột thời khóa biểu.",
    "warning",
  );
});

