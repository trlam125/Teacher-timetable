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
function teacherLoadStats(teacher, projected = null) {
  const current = Number(teacher?.assigned_periods || 0),
    capacity =
      teacher?.week_capacity == null ? null : Number(teacher.week_capacity),
    maxDay = Number(teacher?.max_periods_day || 0);
  const next =
    projected == null || !Number.isFinite(Number(projected))
      ? current
      : Math.max(0, Number(projected));
  const remaining =
    capacity == null || !Number.isFinite(capacity) ? null : capacity - next;
  return {
    current,
    capacity,
    maxDay,
    projected: next,
    remaining,
    over: remaining != null && remaining < 0,
  };
}
function teacherLoadCardHtml(teacher, projected = null) {
  if (!teacher) return "";
  const load = teacherLoadStats(teacher, projected),
    capacityText = load.capacity == null ? "—" : load.capacity;
  return `<div class="assignment-load-card assignment-load-card-live"><div class="assignment-load-metric ${load.over ? "over" : ""}"><small>Tải giáo viên</small><b>${load.projected}/${capacityText} tiết/tuần</b></div><div class="assignment-load-metric"><small>Tối đa/ngày</small><b>${load.maxDay || "—"} tiết/ngày</b></div></div>`;
}
function teacherLoadCellHtml(teacher) {
  if (!teacher) return '<span class="muted">—</span>';
  const load = teacherLoadStats(teacher),
    capacityText = load.capacity == null ? "—" : load.capacity;
  return `<div class="assignment-load-cell ${load.over ? "over" : ""}"><b>${load.current}/${capacityText} tiết/tuần</b><small>Tối đa ${load.maxDay || "—"} tiết/ngày</small></div>`;
}
function updateAssignmentEditLoad(form) {
  if (!form) return;
  const assignmentId = Number(
    form.querySelector('[name="assignment_id"]')?.value || 0,
  ),
    item = data.assignments.find((row) => row.id === assignmentId),
    box = form.querySelector("[data-assignment-edit-load]");
  if (!item || !box) return;
  const teacher = data.teachers.find((row) => row.id === item.teacher_id),
    nextPeriods = Number(
      form.querySelector('[name="periods_per_week"]')?.value || 0,
    ),
    currentTeacherLoad = Number(teacher?.assigned_periods || 0),
    oldPeriods = Number(item.periods_per_week || 0),
    projected = Math.max(0, currentTeacherLoad - oldPeriods + nextPeriods);
  box.innerHTML = teacherLoadCardHtml(teacher, projected);
}
function updateAssignmentEditPreview(form) {
  updateBlockModePreview(form);
  updateAssignmentEditLoad(form);
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
  const tableHtml = `<table class="data-table"><thead><tr>${bulkEntityHeader("assignment")}<th>Lớp</th><th>Môn</th><th>Giáo viên</th><th>Tiết/tuần</th><th>Tải giáo viên</th><th>Chế độ xếp</th><th class="entity-actions-col"></th></tr></thead><tbody>${rows
    .map((item) => {
      const teacher = data.teachers.find((row) => row.id === item.teacher_id);
      return `<tr>${bulkEntityCell("assignment", item.id)}<td>${esc(item.class_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(item.teacher_name)}</td><td><b>${item.periods_per_week}</b></td><td>${teacherLoadCellHtml(teacher)}</td><td>${esc(describeBlockMode(item.block_mode, item.periods_per_week))}</td><td class="entity-actions-cell"><div class="entity-row-actions"><button class="action-link" title="Sửa phân công" onclick="openAssignmentEdit(${item.id})">Sửa</button><button class="danger-link" title="Xóa phân công" onclick="delEntity('assignment',${item.id},this)">Xóa</button></div></td></tr>`;
    })
    .join("")}</tbody></table>`;
  return bulkEntityTableShell("assignment", tableHtml);
}
function renderAssignmentTable() {
  const summary = $("#assignmentCompletenessSummary"),
    table = $("#assignmentTable");
  if (summary) summary.innerHTML = assignmentSummaryHtml();
  if (table) table.innerHTML = assignmentTable();
}
