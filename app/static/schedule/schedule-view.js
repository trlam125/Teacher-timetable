/* Schedule rendering, conflict display, generation and tray UI. */
function renderScheduleSelectors() {
  const type = $("#viewType"),
    entity = $("#viewEntity");
  if (!type || !entity) return;

  const updateEntity = (preserveValue = true) => {
    const previousValue = preserveValue ? entity.value : "";
    const filterType = type.value;
    let rows = [];
    if (filterType === "grade") rows = data.grades || [];
    else if (filterType === "class") rows = data.classes || [];
    else if (filterType === "teacher") rows = data.teachers || [];
    else if (filterType === "subject") rows = data.subjects || [];

    const needsEntity = filterType !== "overview";
    entity.hidden = !needsEntity;
    entity.disabled = !needsEntity;
    const entityLabel = entity.closest("label");
    if (entityLabel) entityLabel.hidden = !needsEntity;

    entity.innerHTML = needsEntity ? opts(rows) : "";
    if (
      needsEntity &&
      previousValue &&
      [...entity.options].some((option) => option.value === previousValue)
    ) {
      entity.value = previousValue;
    }
  };

  const rerender = () => {
    renderSchedule(true);
    renderScheduleCoverage();
  };

  updateEntity(true);
  type.onchange = () => {
    if (typeof clearTapAssign === "function") clearTapAssign();
    updateEntity(false);
    rerender();
  };
  entity.onchange = () => {
    if (typeof clearTapAssign === "function") clearTapAssign();
    rerender();
  };
  rerender();
}

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

async function generateSchedule(confirmedRebuildLessonIds = null, confirmationAttempt = 0) {
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
  renderScheduleAttemptDetails(null);

  if (modal && typeof modal.showModal === "function") {
    modal.showModal();
    setProgress(
      "running",
      "Đang ưu tiên xếp đủ tiết, sau đó tối ưu cách phân bố lịch. Lịch có nhiều lớp và giáo viên có thể cần thêm thời gian...",
    );
  }

  try {
    const allowRebuild = Array.isArray(confirmedRebuildLessonIds);
    const r = await fetch(`/api/projects/${PROJECT_ID}/generate`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        allow_rebuild: allowRebuild,
        confirmed_rebuild_lesson_ids: confirmedRebuildLessonIds,
      }),
    });
    const j = await readApiResponse(r);
    if (!r.ok) {
      renderScheduleAttemptDetails(j);
      if (typeof activateWorkspaceTab === "function") await activateWorkspaceTab("schedule");
    }

    if (r.ok) {
      const partial = Boolean(j.partial);
      setProgress("complete", partial
        ? "Đã lưu các tiết xếp được. Đang cập nhật thời khóa biểu và phần còn thiếu..."
        : "Đã xếp xong. Đang đồng bộ thời khóa biểu...");
      setTimeout(async () => {
        if (modal) modal.close();
        const refreshed = await refreshAfterSuccessfulMutation(
          ["lessons"],
          "Máy chủ đã xếp lịch thành công nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ thời khóa biểu.",
        );
        if (partial) renderScheduleAttemptDetails(j);
        setScheduleActionState("success", refreshed ? 1400 : 2600);
        setScheduleFeedback(
          refreshed
            ? j.message || "Đã xếp thời khóa biểu thành công."
            : "Đã xếp thời khóa biểu trên máy chủ. Hãy tải lại trang để xem dữ liệu mới.",
          refreshed && !partial ? "success" : "warning",
          partial ? 0 : refreshed ? 2600 : 6500,
        );
        if (refreshed && !partial) {
          launchConfetti();
        }
      }, 400);
    } else if (j.requires_confirmation) {
      if (modal) modal.close();
      setScheduleActionState("idle");
      const affectedLessonIds = Array.isArray(j.affected_lesson_ids)
        ? j.affected_lesson_ids
          .map(Number)
          .filter((id) => Number.isInteger(id) && id > 0)
        : [];
      const movedCount = Number(j.moved_count) || 0;
      if (movedCount > 0 && affectedLessonIds.length !== movedCount) {
        setScheduleActionState("error", 1800);
        setScheduleFeedback(
          "Máy chủ không trả về đầy đủ danh sách tiết cần xác nhận. Hãy tải lại trang và thử lại.",
          "error",
          5200,
        );
        return;
      }
      if (confirmationAttempt >= 3) {
        setScheduleActionState("error", 1800);
        setScheduleFeedback(
          "Lịch thay đổi liên tục trong lúc xác nhận. Hãy tải lại dữ liệu và thử lại.",
          "error",
          5200,
        );
        return;
      }
      if (
        await confirmAction(
          `${apiErrorMessage(j, "Lịch hiện tại cần được xếp lại.")}\n\nBạn có đồng ý xếp lại phần không cố định không?`,
          {
            title: "Xếp lại thời khóa biểu",
            confirmText: "Xếp lại",
          },
        )
      ) {
        return generateSchedule(affectedLessonIds, confirmationAttempt + 1);
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
let partialScheduleRebuildIds = null;
function scheduleRebuildLessonIds() {
  return [...new Set((data.lessons || [])
    .filter((lesson) => !lesson.locked)
    .map((lesson) => Number(lesson.id))
    .filter((id) => Number.isInteger(id) && id > 0))];
}
function updateScheduleRebuildButton() {
  const button = $("#scheduleRebuildBtn");
  if (!button) return;
  const scheduledCounts = new Map();
  for (const lesson of data.lessons || []) {
    const id = Number(lesson.assignment_id);
    scheduledCounts.set(id, (scheduledCounts.get(id) || 0) + 1);
  }
  const hasMissing = (data.assignments || []).some((assignment) =>
    Number(assignment.periods_per_week || 0) > (scheduledCounts.get(Number(assignment.id)) || 0));
  const running = Boolean(document.querySelector('[data-schedule-action][data-schedule-state="loading"]'));
  const movableCount = scheduleRebuildLessonIds().length;
  button.disabled = running || !movableCount || !hasMissing;
  button.setAttribute("aria-busy", running ? "true" : "false");
  button.title = running ? "Đang xếp thời khóa biểu."
    : !movableCount ? "Chưa có tiết không cố định trên lịch để xếp lại."
    : !hasMissing ? "Lịch đã đủ tiết."
    : `Dùng lịch hiện có để tìm chỗ cho phần còn thiếu; có thể dời tối đa ${movableCount} tiết không cố định.`;
}
async function confirmPartialScheduleRebuild() {
  if (document.querySelector('[data-schedule-action][data-schedule-state="loading"]')) return;
  const ids = scheduleRebuildLessonIds();
  if (!ids.length) {
    setScheduleFeedback("Chưa có tiết không cố định trên lịch để xếp lại.", "info", 4200);
    return;
  }
  if (await confirmAction(
    `Hệ thống sẽ dùng lịch hiện có làm điểm xuất phát để tìm chỗ cho phần còn thiếu, có thể dời tối đa ${ids.length} tiết không cố định. Các tiết cố định sẽ được giữ nguyên. Tiếp tục?`,
    { title: "Xếp lại phần không cố định", confirmText: "Xếp lại" },
  )) await generateSchedule(ids);
}
function renderScheduleAttemptDetails(payload) {
  partialScheduleRebuildIds = payload?.can_rebuild && Array.isArray(payload.affected_lesson_ids)
    ? payload.affected_lesson_ids.map(Number).filter(id => Number.isInteger(id) && id > 0)
    : null;
  const box = $("#scheduleAttemptDetails");
  if (!box) return;
  if (!payload) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const input = payload.integrity?.input_validation || payload;
  const rows = [];
  const assignmentById = new Map((data.assignments || []).map((row) => [Number(row.id), row]));
  const add = (issue, message) => {
    const assignment = assignmentById.get(Number(issue.assignment_id)) || {};
    rows.push({ ...assignment, ...issue, message });
  };
  for (const issue of payload.unscheduled_assignments || [])
    add(issue, `Cần ${issue.required_periods} tiết; ${payload.saved ? "đã lưu" : "xếp được trong lần thử"} ${issue.scheduled_periods} tiết, còn thiếu ${issue.missing_periods} tiết.`);
  for (const issue of input.teacher_subject_issues || [])
    add(issue, "Giáo viên chưa được cấu hình dạy môn này. Hãy sửa chuyên môn hoặc đổi giáo viên.");
  for (const issue of input.grade_requirement_issues || [])
    add(issue, issue.issue_type === "missing" ? `Chưa có giáo viên phụ trách; định mức ${issue.required_periods} tiết/tuần.`
      : issue.issue_type === "extra" ? "Môn không thuộc chương trình của khối."
      : `Phân công chưa khớp định mức ${issue.required_periods} tiết/tuần hoặc chế độ xếp của khối.`);
  for (const issue of input.assignment_availability_issues || []) add(issue, issue.message);
  for (const issue of input.assignment_reference_issues || [])
    add(issue, "Phân công tham chiếu lớp, môn hoặc giáo viên không còn tồn tại hoặc thuộc bộ thời khóa biểu khác.");
  for (const issue of input.fixed_definition_issues || []) add(issue, issue.message);
  for (const issue of input.duplicate_assignment_issues || [])
    add(issue, "Một lớp–môn đang có nhiều phân công. Hãy giữ lại một giáo viên phụ trách.");
  for (const issue of input.class_capacity_issues || [])
    add(issue, `Lớp cần ${issue.assigned} tiết nhưng chỉ còn ${issue.capacity} ô khả dụng.`);
  for (const issue of payload.integrity?.count_errors || [])
    add(issue, `Lịch hiện có ${issue.actual}/${issue.expected} tiết.`);
  for (const assignmentId of payload.integrity?.required_double_errors || [])
    add({assignment_id: assignmentId}, "Cấu trúc tiết đôi không khớp các block bắt buộc của phân công.");
  for (const issue of payload.integrity?.fixed_errors || [])
    add(issue, `Cụm cố định đang thiếu ${issue.missing_slots?.length || 0} tiết. Hãy xếp bổ sung hoặc bỏ ghim liên quan.`);
  const lessonById = new Map((data.lessons || []).map(row => [Number(row.id), row]));
  const invalidDetails = payload.integrity?.invalid_lesson_conflicts || [];
  const describedLessons = new Set(invalidDetails.map(row => Number(row.lesson_id)));
  for (const issue of invalidDetails) {
    const lesson = lessonById.get(Number(issue.lesson_id));
    add({assignment_id: issue.assignment_id ?? lesson?.assignment_id}, issue.message || "Tiết học vi phạm ràng buộc.");
  }
  for (const lessonId of payload.integrity?.invalid_lesson_ids || []) {
    if (describedLessons.has(Number(lessonId))) continue;
    const lesson = lessonById.get(Number(lessonId));
    add({assignment_id: lesson?.assignment_id}, "Tiết học vi phạm khóa lịch, tiết tránh hoặc bị trùng lịch.");
  }
  box.hidden = false;
  box.innerHTML = `<h2>Chi tiết phân công cần kiểm tra</h2><p>${esc(payload.message || "Chưa xếp được thời khóa biểu.")}</p>${rows.length
    ? `<p>${rows.length} mục cần kiểm tra.${payload.unscheduled_assignments?.length ? (payload.saved ? " Các tiết xếp được đã có trên thời khóa biểu; phần còn thiếu nằm trong khay để xếp tiếp." : " Số tiết xếp được dưới đây thuộc lần thử vừa rồi; lịch đang lưu vẫn được giữ nguyên. Các phân công có thể ảnh hưởng lẫn nhau.") : ""}</p><div class="schedule-details-scroll" tabindex="0" aria-label="Chi tiết phân công chưa xếp được"><table class="data-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Giáo viên</th><th>Chi tiết</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${esc(row.class_name || "—")}</td><td>${esc(row.subject_name || "—")}</td><td>${esc(row.teacher_name || row.assigned_teacher_name || "Chưa phân công")}</td><td>${esc(row.message || "Kiểm tra lại dữ liệu phân công.")}</td></tr>`).join("")}</tbody></table></div>` : ""}<button class="btn ghost" type="button" onclick="goToAssignments()">Đến mục Phân công</button>${partialScheduleRebuildIds?.length ? ' <button class="btn" type="button" onclick="confirmPartialScheduleRebuild()">Thử xếp lại phần không cố định</button>' : ""}`;
}
function goToAssignments() {
  document.querySelector('.nav[data-tab="assignments"]')?.click();
}
// A grade can contain any number of classes. Use the project's real
// class.grade_id relationships; do not guess the grade from class names.
function scheduleGradeClassIds(gradeId) {
  return new Set(
    (data.classes || [])
      .filter((schoolClass) => Number(schoolClass.grade_id) === Number(gradeId))
      .map((schoolClass) => Number(schoolClass.id)),
  );
}

function renderScheduleCoverage() {
  const coverageBox = $("#assignmentCoverage");
  if (!coverageBox) return;
  const coverage = data.coverage || {};
  const duplicates = coverage.duplicate_assignments || [];
  const overloadedClasses = coverage.over_capacity_classes || [];
  const groups = [
    ["Giáo viên chưa phân công", coverage.unassigned_teachers || []],
    ["Môn chưa phân công", coverage.unassigned_subjects || []],
    ["Lớp chưa phân công", coverage.unassigned_classes || []],
  ].filter(([, rows]) => rows.length);
  const duplicateHtml = duplicates.length
    ? `<div><b>Không thể xếp do phân công lớp–môn bị trùng</b><p>${duplicates.map((row) => `${esc(row.class_name)} – ${esc(row.subject_name)}: ID ${(row.assignment_ids || []).join(", ")}`).join("; ")}. Hãy xóa hoặc chuyển để mỗi lớp–môn chỉ còn một giáo viên.</p></div>`
    : "";
  const classOverloadHtml = overloadedClasses.length
    ? `<div><b>Không thể xếp đầy đủ do lớp vượt số ô học</b><p>${overloadedClasses.map((row) => `${esc(row.class_name)}: ${row.assigned}/${row.capacity} tiết (dư ${row.excess})`).join("; ")}. Hãy giảm phân công hoặc bỏ bớt khóa/tiết tránh của lớp.</p></div>`
    : "";
  const gapsHtml = groups.length
    ? `<div><b>Một số dữ liệu chưa được phân công</b><p>Giáo viên, môn hoặc lớp chỉ xuất hiện trên thời khóa biểu sau khi được tạo ở mục Phân công.</p>${groups.map(([label, rows]) => `<div><strong>${label}:</strong> ${rows.map((row) => esc(row.name)).join(", ")}</div>`).join("")}</div>`
    : "";
  const coverageHtml =
    duplicateHtml || classOverloadHtml || gapsHtml
      ? `<div class="coverage-warning">${duplicateHtml}${classOverloadHtml}${gapsHtml}<button class="btn ghost" onclick="goToAssignments()">Đến mục Phân công</button></div>`
      : "";
  if (coverageBox && coverageBox.innerHTML !== coverageHtml) {
    coverageBox.innerHTML = coverageHtml;
  }
  renderCompactUnscheduledTray();
}


function renderCompactUnscheduledTray() {
  const tray = $("#unscheduledTray");
  const countEl = $("#unscheduledTrayCount");
  if (!tray || !countEl) return;
  const viewType = $("#viewType")?.value || "overview";
  const selectedId = Number($("#viewEntity")?.value);
  const scheduledCounts = new Map();
  for (const lesson of data.lessons || []) {
    const id = Number(lesson.assignment_id);
    scheduledCounts.set(id, (scheduledCounts.get(id) || 0) + 1);
  }
  const gradeClasses = viewType === "grade" ? scheduleGradeClassIds(selectedId) : null;
  const assignments = (data.assignments || []).filter((assignment) => {
    if (viewType === "grade") return gradeClasses.has(Number(assignment.class_id));
    if (viewType === "class") return Number(assignment.class_id) === selectedId;
    if (viewType === "teacher") return Number(assignment.teacher_id) === selectedId;
    if (viewType === "subject") return Number(assignment.subject_id) === selectedId;
    return true;
  });
  const pending = assignments.map((assignment) => ({
    ...assignment,
    remaining: Math.max(0, Number(assignment.periods_per_week || 0) - (scheduledCounts.get(Number(assignment.id)) || 0)),
  })).filter((assignment) => assignment.remaining > 0);
  const total = pending.reduce((sum, assignment) => sum + assignment.remaining, 0);
  countEl.textContent = `${total} tiết chưa xếp`;
  const pool = pending.length
    ? pending.map((item) => `<div class="tray-lesson" data-tap-payload="assignment:${Number(item.id)}" role="button" tabindex="0" title="Chọn tiết để xếp vào thời khóa biểu"><div><b>${esc(item.subject_short || item.subject_name || "Môn học")}</b><small>${esc(item.class_name || "")} · ${esc(item.teacher_short || item.teacher_name || "")}</small></div><span>Còn ${item.remaining}</span></div>`).join("")
    : '<div class="empty-state">Không có tiết chưa xếp trong phạm vi đang xem.</div>';
  const markup = '<div class="tray-action-hint">Chọn một thẻ tiết, sau đó chọn ô hợp lệ trên thời khóa biểu để xếp.</div>' + pool;
  if (tray.innerHTML !== markup) tray.innerHTML = markup;
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
  updateScheduleRebuildButton();
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
  const selectedGradeClassIds = vt.value === "grade"
    ? scheduleGradeClassIds(selectedEntityId)
    : null;
  const matchesCurrentView = (assignment) => {
    if (!assignment) return false;
    if (vt.value === "overview") return true;
    if (vt.value === "grade") return selectedGradeClassIds.has(Number(assignment.class_id));
    if (vt.value === "class") return assignment.class_id === selectedEntityId;
    if (vt.value === "subject") return assignment.subject_id === selectedEntityId;
    return assignment.teacher_id === selectedEntityId;
  };
  // Natural, deterministic class order (6A2 before 6A10) across every day/slot.
  const scheduleCollator = new Intl.Collator("vi", { numeric: true, sensitivity: "base" });
  const sortLessons = (left, right) => {
    const a = assignmentById.get(left.assignment_id);
    const b = assignmentById.get(right.assignment_id);
    return scheduleCollator.compare(a?.class_name || "", b?.class_name || "") ||
      scheduleCollator.compare(a?.subject_short || a?.subject_name || "", b?.subject_short || b?.subject_name || "") ||
      scheduleCollator.compare(a?.teacher_short || a?.teacher_name || "", b?.teacher_short || b?.teacher_name || "") ||
      Number(left.id) - Number(right.id);
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

  // Excel-style matrix for whole-school and grade views. Every cell means
  // ONE class at ONE slot (the former layout put all classes into one slot).
  // Keep every card as a selectable lesson with the existing pin/remove API.
  if (vt.value === "overview" || vt.value === "grade") {
    const classes = (data.classes || [])
      .filter((schoolClass) => !selectedGradeClassIds || selectedGradeClassIds.has(Number(schoolClass.id)))
      .sort((a, b) => scheduleCollator.compare(String(a.name || ""), String(b.name || "")));
    if (!classes.length) {
      box.innerHTML = legend + '<div class="empty-state">Chưa có lớp trong phạm vi đang xem.</div>';
      return;
    }

    const matrixKey = classes.map((schoolClass) => Number(schoolClass.id)).join(",");
    const lessonsByClassSlot = new Map();
    for (const [slot, lessons] of lessonsBySlot) {
      for (const lesson of lessons) {
        const assignment = assignmentById.get(lesson.assignment_id);
        if (!assignment) continue;
        const key = `${Number(assignment.class_id)}:${slot}`;
        if (!lessonsByClassSlot.has(key)) lessonsByClassSlot.set(key, []);
        lessonsByClassSlot.get(key).push(lesson);
      }
    }
    const matrixCellContent = (slot, classId) => {
      const cellLessons = lessonsByClassSlot.get(`${classId}:${slot}`) || [];
      const reasons = [...new Set(cellLessons.flatMap((lesson) =>
        conflicts.conflictsByLessonId.get(lesson.id) || []))];
      return {
        conflictTitle: reasons.join("; "),
        hasConflict: reasons.length > 0,
        html: cellLessons.map((lesson) => lessonHtml(
          lesson, "matrix", clustered.has(lesson.id),
          conflicts.conflictsByLessonId.get(lesson.id) || [],
          assignmentById.get(lesson.assignment_id),
        )).join(""),
      };
    };
    const oldMatrix = box.querySelector(".class-matrix-timetable");
    if (oldMatrix && oldMatrix.dataset.matrixKey === matrixKey &&
      oldMatrix.querySelectorAll(".matrix-class-slot").length === days * sessions * pps * classes.length) {
      for (const cell of oldMatrix.querySelectorAll(".matrix-class-slot")) {
        const result = matrixCellContent(Number(cell.dataset.slot), Number(cell.dataset.classId));
        cell.classList.toggle("has-conflict", result.hasConflict);
        cell.dataset.conflictTitle = result.conflictTitle;
        if (cell.title !== result.conflictTitle) cell.title = result.conflictTitle;
        if (cell.innerHTML !== result.html) cell.innerHTML = result.html;
      }
      applyScheduleHighlight();
      return;
    }

    const scrollState = preserveScroll ? captureRefreshScrollState() : null;
    const columns = `64px 46px 46px repeat(${classes.length}, minmax(144px, 1fr))`;
    let html = `<div class="timetable class-matrix-timetable" data-matrix-key="${matrixKey}" style="grid-template-columns:${columns}; --matrix-class-count:${classes.length}">`;
    for (const [label, column] of [["Thứ", 1], ["Buổi", 2], ["Tiết", 3]]) {
      html += `<div class="cell head matrix-corner matrix-corner-${column}" style="grid-column:${column};grid-row:1">${label}</div>`;
    }
    classes.forEach((schoolClass, index) => {
      html += `<div class="cell head matrix-class-head" style="grid-column:${index + 4};grid-row:1" title="${esc(schoolClass.name)}">${esc(schoolClass.name)}</div>`;
    });
    for (let day = 0; day < days; day++) {
      const firstDayRow = day * sessions * pps + 2;
      const dayLabel = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][day] || `Ngày ${day + 1}`;
      html += `<div class="cell matrix-day" style="grid-column:1;grid-row:${firstDayRow}/span ${sessions * pps}">${dayLabel}</div>`;
      for (let session = 0; session < sessions; session++) {
        const firstSessionRow = firstDayRow + session * pps;
        html += `<div class="cell matrix-session" style="grid-column:2;grid-row:${firstSessionRow}/span ${pps}">${sessions > 1 ? (session === 0 ? "S" : "C") : "—"}</div>`;
        for (let period = 0; period < pps; period++) {
          const row = firstSessionRow + period;
          const slot = day * (sessions * pps) + session * pps + period;
          html += `<div class="cell matrix-period" style="grid-column:3;grid-row:${row}">${period + 1}</div>`;
          classes.forEach((schoolClass, index) => {
            const classId = Number(schoolClass.id);
            const content = matrixCellContent(slot, classId);
            html += `<div class="cell available matrix-class-slot ${content.hasConflict ? "has-conflict" : ""}" data-class-id="${classId}" data-slot="${slot}" data-conflict-title="${esc(content.conflictTitle)}" title="${esc(content.conflictTitle)}" style="grid-column:${index + 4};grid-row:${row}">${content.html}</div>`;
          });
        }
      }
    }
    html += "</div>";
    box.innerHTML = legend + html;
    applyScheduleHighlight();
    if (scrollState) restoreRefreshScrollState(scrollState);
    return;
  }

  const currentTable = box.querySelector(".timetable");
  const totalSlots = days * sessions * pps;
  const isOverview = ["overview", "grade", "subject"].includes(vt.value);
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
    applyScheduleHighlight();
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
  applyScheduleHighlight();

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
  const detail = `${a.class_name || ""} · ${a.teacher_short || a.teacher_name || ""}`;
  const compact = ["overview", "grade", "subject", "matrix"].includes(view);
  const matrix = view === "matrix";
  const className = String(a.class_name || "");
  const subjectName = String(a.subject_short || a.subject_name || "Môn học");
  const teacherName = String(a.teacher_short || a.teacher_name || "");
  const lessonTitle = `${className} · ${a.subject_name || subjectName} · ${a.teacher_name || teacherName}`;
  const searchText = `${className} ${subjectName} ${a.subject_name || ""} ${teacherName} ${a.teacher_name || ""}`;
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
  const content = compact
    ? `<b class="lesson-primary">${matrix ? esc(subjectName) : `${esc(className)} · ${esc(subjectName)}`}</b><small class="lesson-secondary">${esc(teacherName)}</small>`
    : `<b>${esc(subjectName)}</b><small>${esc(detail)}</small>`;
  const title = conflictText ? `${lessonTitle} | ${conflictText}` : lessonTitle;
  return `<div class="lesson ${compact ? "lesson-overview lesson-compact" : ""} ${inCluster ? "lesson-cluster" : ""} ${conflictText ? "has-conflict" : ""} ${l.locked ? "lesson-is-locked" : ""} ${actions ? "lesson-has-actions" : ""}" data-search-text="${esc(searchText)}"${tapPayload} title="${esc(title)}">${content}${l.locked ? ` <span class="lesson-lock-status" title="Tiết cố định" aria-label="Tiết cố định">${lessonActionIcon("lock")}</span>` : ""}${conflictBadge}${actions}</div>`;
}

// Highlight matching lessons without filtering the dataset or changing placement actions.
// The control is deliberately outside #scheduleGrid, which is replaced on refresh.
function normalizeScheduleSearch(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[đĐ]/g, "d")
    .toLocaleLowerCase("vi")
    .trim();
}

function applyScheduleHighlight() {
  const input = document.getElementById("scheduleHighlightQuery");
  const status = document.getElementById("scheduleHighlightCount");
  const table = document.querySelector("#scheduleGrid .timetable");
  if (!table) return;
  const query = normalizeScheduleSearch(input?.value);
  const terms = query.split(/\s+/).filter(Boolean);
  const cards = table.querySelectorAll(".lesson[data-search-text]");
  let matching = 0;
  table.classList.toggle("schedule-search-active", terms.length > 0);
  cards.forEach((card) => {
    const text = normalizeScheduleSearch(card.dataset.searchText);
    const match = !terms.length || terms.every((term) => text.includes(term));
    card.classList.toggle("schedule-search-match", terms.length > 0 && match);
    card.classList.toggle("schedule-search-dimmed", terms.length > 0 && !match);
    if (terms.length && match) matching++;
  });
  if (status) {
    status.textContent = terms.length
      ? `${matching} tiết phù hợp${matching ? " · Các tiết khác vẫn hiển thị" : ""}`
      : "Tìm theo lớp, giáo viên hoặc môn; các tiết khác sẽ chỉ mờ đi.";
  }
  const clear = document.getElementById("scheduleHighlightClear");
  if (clear) clear.hidden = !query;
}

function clearScheduleHighlight() {
  const input = document.getElementById("scheduleHighlightQuery");
  if (!input) return;
  input.value = "";
  applyScheduleHighlight();
  input.focus({ preventScroll: true });
}

document.addEventListener("input", (event) => {
  if (event.target?.id === "scheduleHighlightQuery") applyScheduleHighlight();
});

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
  let icon = "";
  if (type === "success") {
    icon = `<img class="app-toast-img" src="/static/tick.gif?v=1&play=${Date.now()}-${Math.random().toString(36).slice(2)}" width="20" height="20" alt="✓">`;
  } else if (type === "error" || type === "delete") {
    icon = `<img class="app-toast-img" src="/static/x-popup.gif?v=1&play=${Date.now()}-${Math.random().toString(36).slice(2)}" width="22" height="22" alt="✕">`;
  } else if (type === "warning") {
    icon = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
  } else {
    icon = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  }
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



// Expand only the scheduling workspace; the tray, search and editor remain
// accessible. Fallback supports browsers without element requestFullscreen.
function syncScheduleFullscreenButton() {
  const section = document.getElementById("schedule");
  const button = document.getElementById("scheduleFullscreenBtn");
  if (!section || !button) return;
  const active = document.fullscreenElement === section || section.classList.contains("schedule-faux-fullscreen");
  button.setAttribute("aria-pressed", String(active));
  button.setAttribute("aria-label", active ? "Thu nhỏ thời khóa biểu" : "Phóng to thời khóa biểu toàn màn hình");
  button.title = active ? "Thu nhỏ thời khóa biểu" : "Phóng to thời khóa biểu toàn màn hình";
  const text = button.querySelector(".schedule-fullscreen-label");
  if (text) text.textContent = active ? "Thu nhỏ" : "Phóng to";
}
async function toggleScheduleFullscreen() {
  const section = document.getElementById("schedule");
  if (!section) return;
  if (document.fullscreenElement === section) {
    try { await document.exitFullscreen(); } catch (error) { showToast("Không thể thoát toàn màn hình.", "warning"); }
  } else if (section.classList.contains("schedule-faux-fullscreen")) {
    section.classList.remove("schedule-faux-fullscreen");
  } else if (typeof section.requestFullscreen === "function" && document.fullscreenEnabled !== false) {
    try { await section.requestFullscreen(); }
    catch (error) { section.classList.add("schedule-faux-fullscreen"); }
  } else {
    section.classList.add("schedule-faux-fullscreen");
  }
  syncScheduleFullscreenButton();
}
document.addEventListener("fullscreenchange", syncScheduleFullscreenButton);
document.addEventListener("keydown", (event) => {
  const section = document.getElementById("schedule");
  if (event.key === "Escape" && section?.classList.contains("schedule-faux-fullscreen")) {
    section.classList.remove("schedule-faux-fullscreen");
    syncScheduleFullscreenButton();
  }
});
