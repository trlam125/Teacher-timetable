let assignmentResetInFlight = false;
async function resetAssignments(button) {
  if (assignmentResetInFlight || autoAssignmentSaves.size) {
    showToast("Đang lưu phân công. Vui lòng chờ hoàn tất.", "info");
    return;
  }
  assignmentResetInFlight = true;
  const idle = "Reset phân công";
  setInlineActionState(button, "loading", { idle, loading: "Đang kiểm tra..." });
  try {
    let confirmation = {};
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await fetch(`/api/projects/${PROJECT_ID}/assignments/reset`, {
        method: "POST",
        headers: operationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(confirmation),
      });
      const result = await readApiResponse(response);
      if (!response.ok && result?.requires_confirmation) {
        if (!(await confirmAction(result.message, {
          title: "Reset toàn bộ phân công",
          confirmText: `Reset ${result.assignment_count} phân công`,
        }))) {
          setInlineActionState(button, "idle", { idle });
          return;
        }
        confirmation = {
          confirm_assignment_cascade: true,
          confirmed_assignment_ids: result.assignment_ids,
          confirmed_lesson_ids: result.lesson_ids,
          confirmed_fixed_lesson_ids: result.fixed_lesson_ids,
        };
        setInlineActionState(button, "loading", { idle, loading: "Đang đặt lại..." });
        continue;
      }
      if (!response.ok) throw new Error(apiErrorMessage(result, "Không thể reset phân công."));
      autoAssignmentDrafts.clear();
      setInlineActionState(button, "success", { idle, success: "Đã đặt lại" }, 1800);
      showToast(result.message || "Đã đặt lại phân công.", "success");
      await refreshAfterSuccessfulMutation();
      return;
    }
    throw new Error("Phân công đã thay đổi trong lúc xác nhận. Hãy thử Reset lại.");
  } catch (error) {
    setInlineActionState(button, "error", { idle, error: "Chưa đặt lại được" }, 2200);
    showToast(error?.message || requestFailureMessage(error), "error", 5000);
  } finally {
    assignmentResetInFlight = false;
  }
}
function describeBlockMode(mode, total) {
  if (mode === "required_double") {
    const pairs = Math.floor(total / 2),
      single = total % 2;
    return `Bắt buộc tiết đôi · ${pairs ? `${pairs} cặp × 2 tiết` : ""}${pairs && single ? " + " : ""}${single ? "1 tiết đơn" : ""}`;
  }
  if (mode === "preferred_double")
    return "Ưu tiên tiết đôi · có thể tách khi cần";
  return "Tự do · xếp riêng hoặc liền nhau";
}
function updateAssignmentEditPreview(form) {
  updateBlockModePreview(form);
}
function assignmentFilterState() {
  return {
    classId: Number($("#assignmentFilterClass")?.value || 0),
    subjectId: Number($("#assignmentFilterSubject")?.value || 0),
    teacherId: Number($("#assignmentFilterTeacher")?.value || 0),
    status: $("#assignmentFilterStatus")?.value || "all",
  };
}
function assignmentMissingRows() {
  const assignments = data.assignments || [],
    classes = data.classes || [],
    subjects = data.subjects || [],
    grades = data.grades || [],
    requirements = data.grade_requirements || [];
  const assignmentByPair = new Map(
    assignments.map((item) => [`${item.class_id}:${item.subject_id}`, item]),
  );
  const assignmentsByClass = new Map();
  assignments.forEach((item) => {
    const key = Number(item.class_id);
    if (!assignmentsByClass.has(key)) assignmentsByClass.set(key, []);
    assignmentsByClass.get(key).push(item);
  });
  const requirementsByGrade = new Map();
  requirements.forEach((item) => {
    const key = Number(item.grade_id);
    if (!requirementsByGrade.has(key)) requirementsByGrade.set(key, []);
    requirementsByGrade.get(key).push(item);
  });
  const result = [];
  for (const schoolClass of classes) {
    if (schoolClass.grade_id == null) continue;
    const gradeId = Number(schoolClass.grade_id),
      grade = grades.find((item) => item.id === gradeId),
      gradeRequirements = requirementsByGrade.get(gradeId) || [];
    // Không có chương trình chuẩn cho khối => không thể kết luận môn nào là dư.
    if (!gradeRequirements.length) continue;
    const requiredSubjectIds = new Set(
      gradeRequirements.map((item) => Number(item.subject_id)),
    );
    for (const requirement of gradeRequirements) {
      const subject = subjects.find(
        (item) => item.id === requirement.subject_id,
      ),
        assignment = assignmentByPair.get(
          `${schoolClass.id}:${requirement.subject_id}`,
        );
      if (!assignment) {
        result.push({
          issue_type: "missing",
          class_id: schoolClass.id,
          class_name: schoolClass.name,
          subject_id: requirement.subject_id,
          subject_name: subject?.name || "?",
          grade_id: gradeId,
          grade_name: grade?.name || "?",
          required_periods: requirement.periods_per_week,
          required_mode: requirement.block_mode,
        });
        continue;
      }
      if (
        Number(assignment.periods_per_week) !==
        Number(requirement.periods_per_week) ||
        String(assignment.block_mode || "free") !==
        String(requirement.block_mode || "free")
      ) {
        result.push({
          issue_type: "mismatch",
          assignment_id: assignment.id,
          assigned_teacher_id: assignment.teacher_id,
          assigned_teacher_name: assignment.teacher_name || "",
          class_id: schoolClass.id,
          class_name: schoolClass.name,
          subject_id: requirement.subject_id,
          subject_name: subject?.name || "?",
          grade_id: gradeId,
          grade_name: grade?.name || "?",
          required_periods: requirement.periods_per_week,
          required_mode: requirement.block_mode,
          assigned_periods: assignment.periods_per_week,
          assigned_mode: assignment.block_mode || "free",
        });
      }
    }
    for (const assignment of assignmentsByClass.get(schoolClass.id) || []) {
      if (requiredSubjectIds.has(Number(assignment.subject_id))) continue;
      const subject = subjects.find((item) => item.id === assignment.subject_id);
      result.push({
        issue_type: "extra",
        assignment_id: assignment.id,
        assigned_teacher_id: assignment.teacher_id,
        assigned_teacher_name: assignment.teacher_name || "",
        class_id: schoolClass.id,
        class_name: schoolClass.name,
        subject_id: assignment.subject_id,
        subject_name: subject?.name || assignment.subject_name || "?",
        grade_id: gradeId,
        grade_name: grade?.name || "?",
        assigned_periods: assignment.periods_per_week,
        assigned_mode: assignment.block_mode || "free",
      });
    }
  }
  return result.sort(
    (a, b) =>
      String(a.class_name).localeCompare(String(b.class_name), "vi") ||
      String(a.subject_name).localeCompare(String(b.subject_name), "vi") ||
      String(a.issue_type).localeCompare(String(b.issue_type)),
  );
}
function assignmentUnassignedClasses() {
  const assigned = new Set(
    (data.assignments || []).map((item) => item.class_id),
  );
  return (data.classes || []).filter((item) => !assigned.has(item.id));
}
function assignmentEligibleTeachers() {
  // Tài khoản đăng ký và hồ sơ giáo viên dùng cho xếp lịch là hai khái niệm
  // tách biệt. Chỉ giáo viên đã được quản trị viên cấu hình ít nhất một môn dạy
  // mới có thể xuất hiện trong form tạo phân công.
  return (data.teachers || []).filter(
    (teacher) => Array.isArray(teacher.subject_ids) && teacher.subject_ids.length > 0,
  );
}
function assignmentFilterTeachers() {
  // Bộ lọc chỉ cần các giáo viên thực sự đang có phân công trong project.
  const usedIds = new Set(
    (data.assignments || []).map((item) => Number(item.teacher_id)),
  );
  return (data.teachers || []).filter((teacher) => usedIds.has(Number(teacher.id)));
}
function renderAssignmentFilters() {
  const classEl = $("#assignmentFilterClass"),
    subjectEl = $("#assignmentFilterSubject"),
    teacherEl = $("#assignmentFilterTeacher"),
    statusEl = $("#assignmentFilterStatus");
  if (!classEl || !subjectEl || !teacherEl || !statusEl) return;
  const current = {
    classId: classEl.value,
    subjectId: subjectEl.value,
    teacherId: teacherEl.value,
    status: statusEl.value || "all",
  };
  classEl.innerHTML =
    '<option value="">Tất cả lớp</option>' + opts(data.classes);
  subjectEl.innerHTML =
    '<option value="">Tất cả môn</option>' + opts(data.subjects);
  teacherEl.innerHTML =
    '<option value="">Tất cả giáo viên</option>' + opts(assignmentFilterTeachers());
  if ([...classEl.options].some((o) => o.value === current.classId))
    classEl.value = current.classId;
  if ([...subjectEl.options].some((o) => o.value === current.subjectId))
    subjectEl.value = current.subjectId;
  if ([...teacherEl.options].some((o) => o.value === current.teacherId))
    teacherEl.value = current.teacherId;
  statusEl.value = current.status;
  const applyStatusUi = () => {
    const unassignedOnly = statusEl.value === "unassigned_class",
      checkingProgram = statusEl.value === "missing";
    subjectEl.disabled = unassignedOnly;
    teacherEl.disabled = unassignedOnly;
    subjectEl.title = unassignedOnly
      ? "Bộ lọc môn không áp dụng cho lớp chưa có phân công."
      : "";
    teacherEl.title = unassignedOnly
      ? "Bộ lọc giáo viên không áp dụng cho lớp chưa có phân công."
      : checkingProgram
        ? "Trong chế độ kiểm tra chương trình, bộ lọc giáo viên chỉ áp dụng cho các phân công hiện có; dòng chưa phân công chưa có giáo viên để lọc."
        : "";
  };
  applyStatusUi();
  statusEl.onchange = () => {
    if (statusEl.value === "unassigned_class") {
      subjectEl.value = "";
      teacherEl.value = "";
    }
    applyStatusUi();
    renderAssignmentTable();
  };
}
function resetAssignmentFilters() {
  [
    "assignmentFilterClass",
    "assignmentFilterSubject",
    "assignmentFilterTeacher",
  ].forEach((id) => {
    const el = $("#" + id);
    if (el) el.value = "";
  });
  if ($("#assignmentFilterStatus")) $("#assignmentFilterStatus").value = "all";
  renderAssignmentFilters();
  renderAssignmentTable();
}
function assignmentSummaryHtml() {
  const issues = assignmentMissingRows(),
    unassigned = assignmentUnassignedClasses(),
    requirements = data.grade_requirements || [],
    classes = data.classes || [],
    grades = data.grades || [];
  const missing = issues.filter((item) => item.issue_type === "missing"),
    mismatch = issues.filter((item) => item.issue_type === "mismatch"),
    extra = issues.filter((item) => item.issue_type === "extra"),
    affected = new Set(issues.map((item) => item.class_id));
  const configuredGrades = new Set(
    requirements.map((item) => Number(item.grade_id)),
  ),
    classesWithoutGrade = classes.filter((item) => item.grade_id == null),
    gradesWithoutProgram = grades.filter(
      (item) => !configuredGrades.has(item.id),
    );
  if (!requirements.length) {
    return '<div class="assignment-filter-summary has-gap"><b>Kiểm tra phân công:</b> Chưa có chương trình môn chuẩn cho khối. Vào <b>Khối / nhóm lớp → Sửa</b> để chọn môn và số tiết/tuần; sau đó hệ thống mới có thể phát hiện thiếu chính xác.</div>';
  }
  const parts = [];
  if (missing.length)
    parts.push(`<b>${missing.length}</b> cặp lớp–môn còn thiếu`);
  if (mismatch.length)
    parts.push(`<b>${mismatch.length}</b> phân công lệch số tiết/chế độ chuẩn`);
  if (extra.length)
    parts.push(`<b>${extra.length}</b> phân công môn không thuộc chương trình khối`);
  if (unassigned.length)
    parts.push(`<b>${unassigned.length}</b> lớp chưa có phân công nào`);
  if (classesWithoutGrade.length)
    parts.push(`<b>${classesWithoutGrade.length}</b> lớp chưa gán khối`);
  if (gradesWithoutProgram.length)
    parts.push(
      `<b>${gradesWithoutProgram.length}</b> khối chưa cấu hình chương trình`,
    );
  if (!parts.length)
    return '<div class="assignment-filter-summary"><b>Kiểm tra phân công:</b> Phân công hiện tại khớp với chương trình môn đã cấu hình cho các khối.</div>';
  return `<div class="assignment-filter-summary has-gap"><b>Kiểm tra phân công:</b> ${parts.join(" · ")}.${affected.size ? ` Có <b>${affected.size} lớp</b> cần kiểm tra.` : ""}</div>`;
}
function assignmentTable() {
  const state = assignmentFilterState();
  if (state.status === "missing") {
    let rows = assignmentMissingRows();
    if (state.classId)
      rows = rows.filter((item) => item.class_id === state.classId);
    if (state.subjectId)
      rows = rows.filter((item) => item.subject_id === state.subjectId);
    if (state.teacherId) {
      rows = rows.filter(
        (item) =>
          (item.issue_type === "mismatch" || item.issue_type === "extra") &&
          Number(item.assigned_teacher_id) === state.teacherId,
      );
    }
    if (!rows.length)
      return '<div class="assignment-filter-empty">Không có cặp lớp–môn nào lệch chương trình với bộ lọc hiện tại.</div>';
    return `<table class="data-table"><thead><tr><th>Lớp</th><th>Khối</th><th>Môn</th><th>Giáo viên hiện tại</th><th>Chương trình chuẩn</th><th>Trạng thái</th><th class="entity-actions-col"></th></tr></thead><tbody>${rows
      .map((item) => {
        if (item.issue_type === "extra") {
          const current = `${item.assigned_periods} tiết/tuần · ${describeBlockMode(item.assigned_mode, item.assigned_periods)}`;
          return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(item.assigned_teacher_name || "—")}</td><td>Không thuộc chương trình khối</td><td><span class="assignment-gap-badge">Môn dư: ${esc(current)}</span></td><td class="entity-actions-cell"><div class="entity-row-actions"><span class="action-link-placeholder"></span><button class="danger-link" title="Xóa phân công" onclick="delEntity('assignment',${item.assignment_id},this)">Xóa</button></div></td></tr>`;
        }
        const required = `${item.required_periods} tiết/tuần · ${describeBlockMode(item.required_mode, item.required_periods)}`;
        if (item.issue_type === "mismatch") {
          const current = `${item.assigned_periods} tiết/tuần · ${describeBlockMode(item.assigned_mode, item.assigned_periods)}`;
          return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(item.assigned_teacher_name || "—")}</td><td>${esc(required)}</td><td><span class="assignment-gap-badge">Đang có: ${esc(current)}</span></td><td class="entity-actions-cell"><div class="entity-row-actions"><button class="action-link" title="Sửa phân công" onclick="openAssignmentEdit(${item.assignment_id})">Sửa</button><span class="action-link-placeholder"></span></div></td></tr>`;
        }
        return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>—</td><td>${esc(required)}</td><td><span class="assignment-gap-badge">Chưa phân công</span></td><td class="entity-actions-cell"><div class="entity-row-actions"><button class="action-link" style="width:auto" onclick="openEntity('assignment',{classId:${item.class_id},subjectId:${item.subject_id}})">+ Thêm</button></div></td></tr>`;
      })
      .join("")}</tbody></table>`;
  }
  if (state.status === "unassigned_class") {
    let rows = assignmentUnassignedClasses();
    if (state.classId) rows = rows.filter((item) => item.id === state.classId);
    if (!rows.length)
      return '<div class="assignment-filter-empty">Không có lớp chưa phân công với bộ lọc hiện tại.</div>';
    return `<table class="data-table"><thead><tr><th>Lớp</th><th>Khối</th><th>Trạng thái</th><th class="entity-actions-col"></th></tr></thead><tbody>${rows
      .map((item) => {
        const grade = data.grades.find((g) => g.id === item.grade_id);
        return `<tr><td><b>${esc(item.name)}</b></td><td>${esc(grade?.name || "—")}</td><td><span class="assignment-gap-badge">Chưa có phân công</span></td><td class="entity-actions-cell"><div class="entity-row-actions"><button class="action-link" style="width:auto" onclick="openEntity('assignment',{classId:${item.id}})">+ Thêm</button></div></td></tr>`;
      })
      .join("")}</tbody></table>`;
  }
  let rows = data.assignments || [];
  if (state.classId)
    rows = rows.filter((item) => item.class_id === state.classId);
  if (state.subjectId)
    rows = rows.filter((item) => item.subject_id === state.subjectId);
  if (state.teacherId)
    rows = rows.filter((item) => item.teacher_id === state.teacherId);
  if (!rows.length)
    return `<div class="assignment-filter-empty">${data.assignments?.length ? "Không có phân công phù hợp với bộ lọc hiện tại." : "Chưa có phân công. Hãy gắn lớp – môn – giáo viên và số tiết/tuần trước khi xếp lịch."}</div>`;
  const tableHtml = `<table class="data-table"><thead><tr>${bulkEntityHeader("assignment")}<th>Lớp</th><th>Môn</th><th>Định mức khối</th><th>Giáo viên</th><th>Tiết/tuần</th><th>Chế độ xếp</th><th class="entity-actions-col"></th></tr></thead><tbody>${rows
    .map((item) => {
      const gradeId = (data.classes || []).find((row) => Number(row.id) === Number(item.class_id))?.grade_id || 0;
      return `<tr>${bulkEntityCell("assignment", item.id)}<td>${esc(item.class_name)}</td><td>${esc(item.subject_name)}</td><td data-subject-norm="${item.subject_id}" data-norm-grade="${gradeId}">${assignmentSubjectNormHtml(item.subject_id, gradeId)}</td><td>${esc(item.teacher_name)}</td><td><b>${item.periods_per_week}</b></td><td>${esc(describeBlockMode(item.block_mode, item.periods_per_week))}</td><td class="entity-actions-cell"><div class="entity-row-actions"><button class="action-link" title="Sửa phân công" onclick="openAssignmentEdit(${item.id})">Sửa</button><button class="danger-link" title="Xóa phân công" onclick="delEntity('assignment',${item.id},this)">Xóa</button></div></td></tr>`;
    })
    .join("")}</tbody></table>`;
  return bulkEntityTableShell("assignment", tableHtml);
}
function renderLegacyAssignmentTable() {
  const summary = $("#assignmentCompletenessSummary"),
    table = $("#assignmentTable");
  if (summary) summary.innerHTML = assignmentSummaryHtml();
  if (table) table.innerHTML = assignmentTable();
}


/* One shared Assignment model, two views: curriculum matrix and legacy list.
   The matrix uses the same REST endpoints as automatic timetable generation. */
let autoAssignmentView = "matrix";
let autoAssignmentGrade = "";
const autoAssignmentDrafts = new Map();
const autoGradeDrafts = new Map();
const autoGradeEditTokens = new Map();
const autoAssignmentSaves = new Set();
const autoGradeSaves = new Set();
function autoAssignmentSubjectRank(name) {return schoolSubjectCatalog.rank(name);}

function setAutoAssignmentView(view) {
  autoAssignmentView = view === "list" ? "list" : "matrix";
  renderAssignmentTable();
}
function setAutoAssignmentGrade(value) {
  autoAssignmentGrade = String(value);
  renderAssignmentTable();
}
function autoAssignmentClassNames() {
  return [...(data.classes || [])].sort((a, b) =>
    String(a.name).localeCompare(String(b.name), "vi", {numeric: true}));
}
function autoAssignmentGrades() {
  const present = new Set(autoAssignmentClassNames().map(x => String(x.grade_id || "")));
  return (data.grades || []).filter(g => present.has(String(g.id)));
}
function autoAssignmentTeacherOptions(subjectId, selectedId) {
  const teachers = [...(data.teachers || [])]
    .filter(t => (t.subject_ids || []).map(Number).includes(Number(subjectId)) ||
      Number(t.id) === Number(selectedId))
    .sort((a,b) => String(a.name).localeCompare(String(b.name), "vi"));
  return `<option value="">— Chọn GV —</option>${teachers.map(t =>
    `<option value="${Number(t.id)}" ${Number(t.id) === Number(selectedId) ? "selected" : ""}>${esc(t.short_name || t.name)}</option>`).join("")}`;
}
function autoAssignmentCurriculum(schoolClass, subjectId) {
  const rows = (data.grade_requirements || []).filter(row =>
    Number(row.grade_id) === Number(schoolClass.grade_id));
  return {configured: rows.length > 0, requirement: rows.find(row =>
    Number(row.subject_id) === Number(subjectId)) || null};
}
function assignmentSubjectNormHtml(subjectId, gradeId = null) {
  const classes = autoAssignmentClassNames().filter((row) =>
    autoAssignmentGrade === "all" || String(row.grade_id) === String(autoAssignmentGrade));
  const gradeIds = gradeId == null ? new Set(classes.map((row) => Number(row.grade_id)).filter(Boolean)) : new Set([Number(gradeId)]);
  const grades = (data.grades || []).filter((row) => gradeIds.has(Number(row.id)));
  const showGrade = gradeId == null && autoAssignmentGrade === "all";
  if (!grades.length) return '<span class="muted">Chưa gán khối</span>';
  return grades.map((grade) => {
    const requirement = (data.grade_requirements || []).find((row) =>
      Number(row.grade_id) === Number(grade.id) && Number(row.subject_id) === Number(subjectId));
    const key = `${grade.id}-${subjectId}`;
    const pending = autoGradeDrafts.has(key);
    const raw = pending ? autoGradeDrafts.get(key) : requirement?.periods_per_week;
    const periods = Number(raw);
    const label = String(raw ?? "").trim() && Number.isInteger(periods) && periods > 0
      ? String(periods) : '<span class="muted" title="Chưa quy định">—</span>';
    return `<div class="assignment-subject-norm-row${showGrade ? " is-multi-grade" : ""}">${showGrade ? `<b>${esc(grade.name)}:</b> ` : ""}<span>${label}</span>${pending ? '<small>Chưa lưu</small>' : ""}</div>`;
  }).join("");
}
function refreshAssignmentSubjectNorms() {
  document.querySelectorAll("[data-subject-norm]").forEach((cell) => {
    cell.innerHTML = assignmentSubjectNormHtml(Number(cell.dataset.subjectNorm), cell.dataset.normGrade == null ? null : Number(cell.dataset.normGrade));
  });
}
function autoAssignmentCell(schoolClass, subject, assignment) {
  const c = autoAssignmentCurriculum(schoolClass, subject.id);
  // The grade curriculum is strict when configured. Show an existing extra
  // assignment for correction; do not offer creating a forbidden new one.
  if (!assignment && c.configured && !c.requirement) {
    return `<td colspan="2" class="auto-assignment-not-applicable">—</td>`;
  }
  const draft = autoAssignmentDrafts.get(`${schoolClass.id}-${subject.id}`);
  const teacherId = Number(draft?.teacherId ?? assignment?.teacher_id ?? 0);
  const periods = draft?.periods ?? assignment?.periods_per_week ?? c.requirement?.periods_per_week ?? "";
  const mode = assignment?.block_mode || c.requirement?.block_mode || "free";
  const id = `${schoolClass.id}-${subject.id}`;
  const badge = assignment && c.requirement &&
    Number(assignment.periods_per_week) !== Number(c.requirement.periods_per_week)
    ? " auto-assignment-mismatch" : "";
  const label = `${schoolClass.name} – ${subject.name}`;
  return `<td class="auto-assignment-teacher${badge}">
      <select aria-label="Giáo viên ${esc(label)}" data-matrix-teacher data-matrix-cell="${id}" data-initial="${Number(assignment?.teacher_id || 0)}"
        onchange="autoAssignmentCellChanged('${id}')">${autoAssignmentTeacherOptions(subject.id, teacherId)}</select>
    </td><td class="auto-assignment-periods${badge}">
      <div class="auto-assignment-cell" data-auto-assignment-cell="${id}" data-class="${schoolClass.id}" data-subject="${subject.id}"
        data-assignment="${Number(assignment?.id || 0)}" data-mode="${esc(mode)}" data-edit-token="${esc(draft?.editToken || assignment?.edit_token || "")}">
        <input type="number" min="1" max="40" step="1" aria-label="Số tiết ${esc(label)}"
          data-matrix-periods data-initial="${assignment?.periods_per_week ?? ""}"
          value="${esc(periods)}" oninput="autoAssignmentCellChanged('${id}')">
        <button type="button" class="auto-assignment-save" data-matrix-save
          onclick="saveAutoAssignmentCell('${id}',this)" hidden>Lưu</button>
        ${assignment ? `<button type="button" class="auto-assignment-detail" title="Chi tiết: ${esc(label)}" aria-label="Chi tiết phân công ${esc(label)}" onclick="openAssignmentEdit(${assignment.id})"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg></button>
        <button type="button" class="auto-assignment-delete" title="Xóa phân công ${esc(label)}" aria-label="Xóa phân công ${esc(label)}" onclick="deleteAutoAssignmentCell('${id}',this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m5 4v6m4-6v6"/></svg></button>` : ""}
      </div>
    </td>`;
}
function renderAutoAssignmentMatrix() {
  const table = $("#assignmentTable");
  if (!table) return;
  // A save/delete refresh rebuilds the matrix. Preserve both scroll axes so
  // editing subjects near the bottom (or classes to the right) stays in view.
  const previousScroller = table.querySelector(".auto-assignment-scroller");
  const previousScrollTop = previousScroller?.scrollTop ?? 0;
  const previousScrollLeft = previousScroller?.scrollLeft ?? 0;
  const grades = autoAssignmentGrades();
  const select = $("#autoAssignmentGrade");
  if (select) {
    const chosen = autoAssignmentGrade || (grades.length ? String(grades[0].id) : "all");
    autoAssignmentGrade = chosen;
    select.innerHTML = `<option value="all">Tất cả khối</option>` + grades.map(g =>
      `<option value="${Number(g.id)}">${esc(g.name)}</option>`).join("");
    select.value = grades.some(g => String(g.id) === chosen) || chosen === "all" ? chosen : "all";
    autoAssignmentGrade = select.value;
  }
  const classes = autoAssignmentClassNames().filter(c =>
    autoAssignmentGrade === "all" || String(c.grade_id) === String(autoAssignmentGrade));
  const search = String($("#autoAssignmentSubjectSearch")?.value || "").trim().toLocaleLowerCase("vi");
  const subjects = [...(data.subjects || [])].map(s => ({...s, name:schoolSubjectCatalog.canonical(s.name)})).filter(s =>
    !search || String(s.name || "").toLocaleLowerCase("vi").includes(search))
    .sort((a,b) => autoAssignmentSubjectRank(a.name) - autoAssignmentSubjectRank(b.name)
      || String(a.name).localeCompare(String(b.name), "vi", {numeric:true}));
  if (!classes.length || !subjects.length) {
    table.innerHTML = '<div class="assignment-filter-empty">Chưa có lớp hoặc môn phù hợp. Hãy khai báo lớp, môn và giáo viên trước.</div>';
    return;
  }
  const byPair = new Map((data.assignments || []).map(a =>
    [`${a.class_id}-${a.subject_id}`,a]));
  const headers = classes.map(c => `<th colspan="2" scope="colgroup">${esc(c.name)}</th>`).join("");
  const subheaders = classes.map(() => '<th>GV</th><th>Số tiết</th>').join("");
  const columns = `<colgroup><col class="auto-assignment-col-subject"><col class="auto-assignment-col-norm">${classes.map(() =>
    '<col class="auto-assignment-col-teacher"><col class="auto-assignment-col-periods">').join("")}</colgroup>`;
  const rows = subjects.map((subject, i) => `<tr><th scope="row" class="auto-assignment-subject" title="${esc(subject.name)}">
        <span class="auto-assignment-no">${i + 1}</span> ${esc(subject.name)}</th>
        <td class="auto-assignment-norm" data-subject-norm="${subject.id}">${assignmentSubjectNormHtml(subject.id)}</td>
        ${classes.map(c => autoAssignmentCell(c,subject,byPair.get(`${c.id}-${subject.id}`))).join("")}</tr>`).join("");
  const assigned = (data.assignments || []).length;
  table.innerHTML = `<div class="auto-assignment-stats">${assigned} phân công đang lưu · ${classes.length} lớp · ${subjects.length} môn đang hiển thị</div>
    <div class="auto-assignment-scroller" tabindex="0" aria-label="Bảng phân công giáo viên theo lớp và môn, cuộn ngang để xem các lớp">
      <table class="auto-assignment-matrix" style="--assignment-class-count:${classes.length}">${columns}<thead><tr><th rowspan="2" class="auto-assignment-subject">TT · Môn</th><th rowspan="2" class="auto-assignment-norm" title="Số tiết/tuần cho mỗi lớp, theo cấu hình Khối / nhóm">Tiết/tuần</th>${headers}</tr>
        <tr>${subheaders}</tr></thead><tbody>${rows}</tbody></table>
    </div>
    <p class="auto-assignment-note">Bảng phân công dùng trực tiếp cho bộ xếp tự động. Hiện mỗi cặp lớp–môn chỉ được gán một giáo viên trong bộ xếp tự động. Cột số tiết lấy gợi ý từ chương trình khối nếu đã cấu hình.</p>`;
  const nextScroller = table.querySelector(".auto-assignment-scroller");
  if (nextScroller) {
    nextScroller.scrollTop = previousScrollTop;
    nextScroller.scrollLeft = previousScrollLeft;
  }
  autoAssignmentDrafts.forEach((_, id) => autoAssignmentCellChanged(id));
}
function autoAssignmentCellChanged(id) {
  const cell = document.querySelector(`[data-auto-assignment-cell="${id}"]`),
    teacher = document.querySelector(`[data-matrix-teacher][data-matrix-cell="${id}"]`);
  if (!cell || !teacher) return;
  const periods = cell.querySelector("[data-matrix-periods]"),
    button = cell.querySelector("[data-matrix-save]");
  const changed = Number(teacher.value || 0) !== Number(teacher.dataset.initial || 0)
    || periods.value !== periods.dataset.initial;
  if (button) {
    button.hidden = !changed;
    button.disabled = autoAssignmentSaves.has(id);
    button.textContent = button.disabled ? "Đang lưu..." : !teacher.value && Number(cell.dataset.assignment) ? "Xóa" : "Lưu";
  }
  cell.classList.toggle("is-dirty", changed);
  if (changed || autoAssignmentSaves.has(id)) autoAssignmentDrafts.set(id, {teacherId: Number(teacher.value || 0), periods: periods.value, editToken: cell.dataset.editToken});
  else autoAssignmentDrafts.delete(id);
}
async function saveAutoAssignmentCell(id, button) {
  if (assignmentResetInFlight) return;
  const cell = document.querySelector(`[data-auto-assignment-cell="${id}"]`),
    teacherEl = document.querySelector(`[data-matrix-teacher][data-matrix-cell="${id}"]`);
  if (!cell || !teacherEl || button.disabled || autoAssignmentSaves.has(id)) return;
  const teacherId = Number(teacherEl.value || 0),
    periodsEl = cell.querySelector("[data-matrix-periods]"),
    periods = Number(periodsEl?.value),
    assignmentId = Number(cell.dataset.assignment || 0),
    classId = Number(cell.dataset.class), subjectId = Number(cell.dataset.subject);
  if (!teacherId && assignmentId) {
    await deleteAutoAssignmentCell(id, button);
    return;
  }
  if (!teacherId) { showToast("Hãy chọn giáo viên trước khi lưu.", "warning"); return; }
  if (!Number.isInteger(periods) || periods < 1 || periods > 40 || !String(periodsEl.value).trim()) {
    showToast("Số tiết/tuần phải là số nguyên từ 1 đến 40.", "warning"); return;
  }
  const assigned = (data.assignments || []).find(row => Number(row.id) === assignmentId);
  if (assigned && teacherId === Number(assigned.teacher_id)
      && periods === Number(assigned.periods_per_week)) { autoAssignmentCellChanged(id); return; }
  button.disabled = true;
  button.textContent = "Đang lưu...";
  const submitted = {teacherId, periods: periodsEl.value};
  autoAssignmentSaves.add(id);
  try {
    let response, result, cancelled = false;
    if (assignmentId) {
      const outcome = await updateWithScheduleConfirmation(
        `/api/projects/${PROJECT_ID}/assignments/${assignmentId}`,
        {teacher_id: teacherId, periods_per_week: periods, block_mode: cell.dataset.mode || "free", expected_token: cell.dataset.editToken});
      ({response, result, cancelled} = outcome);
    } else {
      response = await fetch(`/api/projects/${PROJECT_ID}/entity`, {
        method: "POST", headers: operationHeaders({"Content-Type":"application/json"}),
        body: JSON.stringify({type:"assignment", data: {
          teacher_id:teacherId, class_id:classId, subject_id:subjectId,
          periods_per_week:periods, block_mode:cell.dataset.mode || "free"
        }})
      });
      result = await readApiResponse(response);
    }
    if (cancelled) {showToast("Đã hủy. Dữ liệu cũ được giữ nguyên.", "info");return;}
    if (!response.ok) {showToast(apiErrorMessage(result,"Không thể lưu phân công."),"error",6000);return;}
    const liveCell = document.querySelector(`[data-auto-assignment-cell="${id}"]`);
    const liveTeacher = document.querySelector(`[data-matrix-teacher][data-matrix-cell="${id}"]`);
    const latest = liveCell && liveTeacher
      ? {teacherId: Number(liveTeacher.value || 0), periods: liveCell.querySelector("[data-matrix-periods]").value}
      : autoAssignmentDrafts.get(id) || submitted;
    // Keep the visible intent until refresh finishes, including a reversal to
    // the old saved value while either the mutation or reload is in flight.
    latest.editToken = result.edit_token || cell.dataset.editToken;
    autoAssignmentDrafts.set(id, latest);
    showToast("Đã lưu phân công.","success");
    await refreshAfterSuccessfulMutation();
  } catch(err) {
    showToast(err?.message || requestFailureMessage(err),"error",6000);
  } finally {
    autoAssignmentSaves.delete(id);
    autoAssignmentCellChanged(id);
  }
}
// Shared delete flow for the visible Xóa button and the former "clear GV → Xóa" shortcut.
// Confirm even when the assignment has no scheduled lessons; the backend will
// request a second, impact-specific confirmation if removing lessons is necessary.
async function deleteAutoAssignmentCell(id, button) {
  const cell = document.querySelector(`[data-auto-assignment-cell="${id}"]`);
  const assignmentId = Number(cell?.dataset.assignment || 0);
  const assignment = (data.assignments || []).find(item => Number(item.id) === assignmentId);
  if (!assignment || !button || button.disabled) return;
  const confirmed = await confirmAction(
    `Xóa phân công ${assignment.subject_name} của lớp ${assignment.class_name} (${assignment.teacher_name})? Thao tác này không thể hoàn tác.`,
    {title: "Xác nhận xóa phân công", confirmText: "Xóa phân công"}
  );
  if (!confirmed) return;
  await delEntity("assignment", assignmentId, button);
  // Only discard an unsaved matrix draft after the API has actually removed
  // the assignment. Keep it intact if the user cancels or the request fails.
  if (!(data.assignments || []).some(item => Number(item.id) === assignmentId)) {
    autoAssignmentDrafts.delete(id);
    renderAssignmentTable();
  }
}
function renderAssignmentTable() {
  const matrix = autoAssignmentView === "matrix";
  const filters = $("#autoAssignmentLegacyFilters"),
    controls = $("#autoAssignmentMatrixControls"),
    help = $("#autoAssignmentMatrixHelp");
  if (filters) filters.hidden = matrix;
  if (controls) controls.hidden = !matrix;
  if (help) help.hidden = !matrix;
  $("#autoAssignmentMatrixTab")?.classList.toggle("ghost", !matrix);
  $("#autoAssignmentListTab")?.classList.toggle("ghost", matrix);
  if (matrix) {
    const summary = $("#assignmentCompletenessSummary");
    if (summary) summary.innerHTML = assignmentSummaryHtml();
    renderAutoAssignmentMatrix();
  } else {
    renderLegacyAssignmentTable();
  }
}


function renderAutoGradeMatrix() {
  const box = $("#autoGradeProgramTable");
  if (!box) return;
  const previousScroller = box.querySelector(".auto-grade-scroller");
  const previousTop = previousScroller?.scrollTop ?? 0;
  const previousLeft = previousScroller?.scrollLeft ?? 0;
  const grades = [...(data.grades || [])];
  const subjects = [...(data.subjects || [])].map(s => ({...s, name:schoolSubjectCatalog.canonical(s.name)})).sort((a,b) =>
    autoAssignmentSubjectRank(a.name) - autoAssignmentSubjectRank(b.name)
      || a.name.localeCompare(b.name,"vi",{numeric:true}));
  if (!grades.length || !subjects.length) {
    box.innerHTML = '<div class="assignment-filter-empty">Hãy thêm khối và môn học trước.</div>';
    return;
  }
  const byPair = new Map((data.grade_requirements || []).map(x =>
    [`${x.grade_id}-${x.subject_id}`, x]));
  const header = grades.map(g => `<th scope="col">${esc(g.name)}</th>`).join("");
  const body = subjects.map((s,i) => `<tr><th scope="row" class="auto-grade-subject"><span class="auto-assignment-no">${i+1}</span> ${esc(s.name)}</th>${grades.map(g=>{
    const item = byPair.get(`${g.id}-${s.id}`);
    const key = `${g.id}-${s.id}`;
    const shown = autoGradeDrafts.has(key) ? autoGradeDrafts.get(key) : (item?.periods_per_week ?? '');
    return `<td><input type="number" min="1" max="40" step="1" placeholder="—" data-grade-id="${g.id}"
      data-subject-id="${s.id}" data-mode="${esc(item?.block_mode || 'free')}"
      data-original="${item?.periods_per_week ?? ''}" value="${shown}" data-edit-token="${esc(autoGradeEditTokens.get(Number(g.id)) || g.edit_token || '')}"
      oninput="autoGradeMatrixChanged(${g.id})" aria-label="${esc(g.name)} ${esc(s.name)}"></td>`;
  }).join("")}</tr>`).join("");
  const footer=grades.map(g => `<td><button type="button" class="btn ghost auto-grade-save" data-grade-save="${g.id}"
    onclick="saveAutoGradeColumn(${g.id},this)" disabled>Lưu ${esc(g.name)}</button></td>`).join("");
  box.innerHTML=`<div class="auto-assignment-scroller auto-grade-scroller" tabindex="0" aria-label="Bảng số tiết môn theo khối">
    <table class="auto-grade-matrix"><thead><tr><th>Môn</th>${header}</tr></thead>
    <tbody>${body}</tbody><tfoot><tr><th>Lưu định mức</th>${footer}</tr></tfoot></table>
  </div>`;
  const nextScroller = box.querySelector(".auto-grade-scroller");
  if (nextScroller) {
    nextScroller.scrollTop = previousTop;
    nextScroller.scrollLeft = previousLeft;
  }
  for (const grade of grades) autoGradeMatrixChanged(grade.id);
}
function autoGradeMatrixChanged(gradeId) {
  const box = $("#autoGradeProgramTable"), button=box?.querySelector(`[data-grade-save="${gradeId}"]`);
  if (!box || !button) return;
  const inputs = [...box.querySelectorAll(`[data-grade-id="${gradeId}"]`)];
  for (const x of inputs) {
    const key = `${gradeId}-${x.dataset.subjectId}`;
    if (autoGradeSaves.has(Number(gradeId)) || String(x.value).trim() !== String(x.dataset.original).trim()) autoGradeDrafts.set(key, x.value);
    else autoGradeDrafts.delete(key);
  }
  const changed=inputs.some(x=>String(x.value).trim()!==String(x.dataset.original).trim());
  if (changed && !autoGradeEditTokens.has(Number(gradeId))) autoGradeEditTokens.set(Number(gradeId), inputs[0]?.dataset.editToken || "");
  if (!changed && !autoGradeSaves.has(Number(gradeId))) autoGradeEditTokens.delete(Number(gradeId));
  button.disabled = autoGradeSaves.has(Number(gradeId)) || !changed;
  button.textContent = autoGradeSaves.has(Number(gradeId)) ? "Đang lưu..." : `Lưu ${(data.grades || []).find(row => Number(row.id) === Number(gradeId))?.name || "khối"}`;
  button.classList.toggle('is-changed',changed);
  refreshAssignmentSubjectNorms();
}
async function saveAutoGradeColumn(gradeId,button) {
  const grade=(data.grades || []).find(x => Number(x.id) === Number(gradeId)),
    box=$("#autoGradeProgramTable");
  if (!grade || !box || button.disabled || autoGradeSaves.has(Number(gradeId))) return;
  const items=[...box.querySelectorAll(`[data-grade-id="${gradeId}"]`)];
  const configs=[];
  for (const input of items) {
    const raw=String(input.value).trim();
    if (!raw) continue;
    const n=Number(raw);
    if (!Number.isInteger(n) || n < 1 || n > 40) {
      showToast(`Số tiết phải là số nguyên từ 1 đến 40.`,"warning");
      input.focus(); return;
    }
    configs.push({subject_id:Number(input.dataset.subjectId), periods_per_week:n,
      block_mode:input.dataset.mode || "free"});
  }
  button.disabled=true;
  button.textContent='Đang lưu...';
  const submitted = new Map(items.map(input => [String(input.dataset.subjectId), input.value]));
  autoGradeSaves.add(Number(gradeId));
  try {
    const {response,result,cancelled}=await updateWithScheduleConfirmation(
      `/api/projects/${PROJECT_ID}/entity/grade/${grade.id}`,
      {type:'grade', data:{name:grade.name,subject_requirements:configs}, expected_token:autoGradeEditTokens.get(Number(gradeId)) || items[0]?.dataset.editToken});
    if (cancelled) {showToast('Đã hủy. Chương trình hiện tại được giữ nguyên.','info');return;}
    if (!response.ok) {showToast(apiErrorMessage(result,'Không thể lưu chương trình khối.'),'error',6000);return;}
    autoGradeEditTokens.set(Number(gradeId), result.edit_token || autoGradeEditTokens.get(Number(gradeId)));
    const live = new Map([...box.querySelectorAll(`[data-grade-id="${gradeId}"]`)].map(input => [String(input.dataset.subjectId), input.value]));
    for (const [subjectId, value] of submitted) {
      const key = `${gradeId}-${subjectId}`;
      const latest = live.has(subjectId) ? live.get(subjectId) : autoGradeDrafts.get(key) ?? value;
      autoGradeDrafts.set(key, latest);
    }
    showToast(`Đã lưu định mức ${grade.name}.`,'success');
    await refreshAfterSuccessfulMutation();
  } catch(error) {
    showToast(error?.message || requestFailureMessage(error),'error',6000);
  } finally {
    autoGradeSaves.delete(Number(gradeId));
    autoGradeMatrixChanged(gradeId);
  }
}
