function renderAll() {
  if ($("#subjectTable")) {
    $("#subjectTable").innerHTML = table(
      data.subjects,
      [
        ["Tên", "name"],
        ["Tên rút gọn", "short_name"],
        ["Tiết liên tiếp tối đa", "max_consecutive"],
      ],
      "subject",
    );
    $("#departmentTable").innerHTML = table(
      data.departments,
      [["Tên tổ", "name"]],
      "department",
    );
    $("#teacherTable").innerHTML = table(
      data.teachers,
      [
        ["Họ tên", "name"],
        ["Tên ngắn", "short_name"],
        [
          "Môn dạy",
          (r) =>
            (r.subject_ids || [])
              .map((id) => data.subjects.find((x) => x.id === id)?.name)
              .filter(Boolean)
              .join(", ") || "—",
        ],
        [
          "Tổ",
          (r) =>
            data.departments.find((x) => x.id === r.department_id)?.name || "—",
        ],
        [
          "Tải tuần",
          (r) => `${r.assigned_periods || 0}/${r.week_capacity ?? "—"} tiết`,
        ],
        ["Tối đa tiết/ngày", "max_periods_day"],
      ],
      "teacher",
    );
    $("#gradeTable").innerHTML = table(
      data.grades,
      [
        ["Tên khối/nhóm", "name"],
        [
          "Chương trình",
          (r) => {
            const rows = (data.grade_requirements || []).filter(
              (item) => item.grade_id === r.id,
            );
            return rows.length
              ? `${rows.length} môn · ${rows.reduce((sum, item) => sum + Number(item.periods_per_week || 0), 0)} tiết/tuần`
              : "Chưa cấu hình";
          },
        ],
      ],
      "grade",
    );
    $("#classTable").innerHTML = table(
      data.classes,
      [
        ["Tên lớp", "name"],
        [
          "Khối",
          (r) => data.grades.find((x) => x.id === r.grade_id)?.name || "—",
        ],
      ],
      "class",
    );
    renderAssignmentFilters();
    renderAssignmentTable();
    if ($("#statLessons")) {
      $("#statTeachers").textContent = data.teachers.length;
      $("#statClasses").textContent = data.classes.length;
      $("#statAssignments").textContent = data.assignments.length;
      $("#statLessons").textContent = data.lessons.length;
    }
    renderScheduleSelectors();
    renderConstraintSelectors();
  }
}
function opts(rows, label = "name") {
  return rows
    .map((x) => `<option value="${x.id}">${esc(x[label])}</option>`)
    .join("");
}

function renderScheduleSelectors() {
  const type = $("#viewType"),
    entity = $("#viewEntity"),
    search = $("#viewSearch");
  if (!type || !entity) return;

  const updateEntity = (preserveValue = true) => {
    const previousValue = preserveValue ? entity.value : "";
    const filterType = type.value;
    let rows = [];
    if (filterType === "class") rows = data.classes || [];
    else if (filterType === "teacher") rows = data.teachers || [];
    else if (filterType === "subject") rows = data.subjects || [];

    const query = (search?.value || "").trim().toLocaleLowerCase("vi");
    if (query) {
      rows = rows.filter((item) =>
        [item.name, item.short_name]
          .filter(Boolean)
          .some((value) =>
            String(value).toLocaleLowerCase("vi").includes(query),
          ),
      );
    }

    const needsEntity = filterType !== "overview";
    entity.hidden = !needsEntity;
    entity.disabled = !needsEntity;
    const entityLabel = entity.closest("label");
    if (entityLabel) entityLabel.hidden = !needsEntity;

    entity.innerHTML = needsEntity ? opts(rows) : "";
    if (
      needsEntity &&
      previousValue &&
      [...entity.options].some((o) => o.value === previousValue)
    ) {
      entity.value = previousValue;
    }
  };

  const rerender = () => {
    renderSchedule(true);
    if ($("#unscheduledTray")) renderManualTray();
  };

  updateEntity(true);

  type.onchange = () => {
    clearTapAssign();
    updateEntity(false);
    rerender();
  };
  entity.onchange = () => { clearTapAssign(); rerender(); };

  if (search) {
    search.oninput = () => {
      clearTapAssign();
      updateEntity(true);
      rerender();
    };
  }

  rerender();
}
function blockModeEditor(mode = "free") {
  const selected = (value) => (value === mode ? "selected" : "");
  return `<label>Chế độ xếp tiết<select name="block_mode" onchange="updateBlockModePreview(this.form)"><option value="free" ${selected("free")}>Tự do</option><option value="preferred_double" ${selected("preferred_double")}>Ưu tiên tiết đôi</option><option value="required_double" ${selected("required_double")}>Bắt buộc tiết đôi</option></select><small class="block-mode-help">Tự do: các tiết độc lập. Ưu tiên: cố gắng ghép đôi nhưng được tách. Bắt buộc: hệ thống chia thành các cặp 2 tiết; nếu tổng số tiết lẻ thì còn 1 tiết đơn.</small></label><div class="block-mode-preview" data-block-preview></div>`;
}
function updateBlockModePreview(form) {
  if (!form) return;
  const total = Number(
    form.querySelector('[name="periods_per_week"]')?.value || 0,
  ),
    mode = form.querySelector('[name="block_mode"]')?.value || "free",
    preview = form.querySelector("[data-block-preview]");
  if (preview)
    preview.textContent =
      total > 0
        ? describeBlockMode(mode, total)
        : "Nhập số tiết/tuần để xem cách xếp.";
}
function teacherSubjectPicker(selectedIds = []) {
  const selected = new Set((selectedIds || []).map(Number));
  return `<div class="teacher-subject-picker"><div class="assignment-pick-head"><b>Môn giáo viên có thể dạy</b><div class="assignment-pick-actions"><button type="button" onclick="selectTeacherSubjects(this.form,true)">Chọn tất cả</button><button type="button" onclick="selectTeacherSubjects(this.form,false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${data.subjects.length ? data.subjects.map((item) => `<label class="assignment-pick-row"><input type="checkbox" name="subject_ids" value="${item.id}" ${selected.has(item.id) ? "checked" : ""}><span>${esc(item.name)}</span></label>`).join("") : '<div class="assignment-bulk-empty">Chưa có môn học. Hãy thêm môn trước.</div>'}</div></div><p class="teacher-subject-help">Màn phân công chỉ hiển thị các môn được chọn ở đây.</p>`;
}
function selectTeacherSubjects(form, checked) {
  if (!form) return;
  form
    .querySelectorAll('input[name="subject_ids"]')
    .forEach((input) => (input.checked = checked));
}
function gradeRequirementPicker(selectedRows = []) {
  const selected = new Map(
    (selectedRows || []).map((item) => [Number(item.subject_id), item]),
  );
  const modeOptions = (mode) =>
    `<option value="free" ${mode === "free" ? "selected" : ""}>Tự do</option><option value="preferred_double" ${mode === "preferred_double" ? "selected" : ""}>Ưu tiên tiết đôi</option><option value="required_double" ${mode === "required_double" ? "selected" : ""}>Bắt buộc tiết đôi</option>`;
  return `<div class="teacher-subject-picker"><div class="assignment-pick-head"><b>Chương trình môn chuẩn của khối</b><div class="assignment-pick-actions"><button type="button" onclick="selectGradeRequirements(this.form,true)">Chọn tất cả</button><button type="button" onclick="selectGradeRequirements(this.form,false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${data.subjects.length
    ? data.subjects
      .map((item) => {
        const row = selected.get(item.id),
          checked = !!row,
          periods = row?.periods_per_week || 1,
          mode = row?.block_mode || "free";
        return `<div class="assignment-subject-item"><label class="assignment-pick-row"><input type="checkbox" name="grade_subject_ids" value="${item.id}" ${checked ? "checked" : ""} onchange="toggleGradeRequirement(this)"><span>${esc(item.name)}</span></label><div class="assignment-subject-config" data-grade-subject-settings="${item.id}" ${checked ? "" : "hidden"}><label>Tiết/tuần<input type="number" name="grade_subject_periods_${item.id}" min="1" max="40" value="${periods}"></label><label>Chế độ xếp<select name="grade_subject_mode_${item.id}">${modeOptions(mode)}</select></label></div></div>`;
      })
      .join("")
    : '<div class="assignment-bulk-empty">Chưa có môn học. Hãy thêm môn trước.</div>'
    }</div></div><p class="teacher-subject-help">Bộ lọc thiếu phân công sẽ so trực tiếp từng lớp trong khối với danh sách này, không suy đoán từ các lớp khác.</p>`;
}
function toggleGradeRequirement(input) {
  const box = input.form?.querySelector(
    `[data-grade-subject-settings="${input.value}"]`,
  );
  if (box) box.hidden = !input.checked;
}
function selectGradeRequirements(form, checked) {
  if (!form) return;
  form.querySelectorAll('input[name="grade_subject_ids"]').forEach((input) => {
    input.checked = checked;
    toggleGradeRequirement(input);
  });
}
function openEntity(type, preset = null) {
  entityType = type;
  pendingAssignmentGap = type === "assignment" && preset ? preset : null;
  const titles = {
    subject: "Thêm môn học",
    department: "Thêm tổ chuyên môn",
    teacher: "Thêm giáo viên",
    grade: "Thêm khối / nhóm",
    class: "Thêm lớp",
    assignment: "Thêm phân công nhanh",
  };
  $("#modalTitle").textContent = titles[type];
  let h = '<label>Tên<input name="name" required></label>';
  if (type === "subject")
    h +=
      `<label>Tên rút gọn<input name="short_name" required></label><label>Số tiết liên tiếp tối đa<input type="number" name="max_consecutive" value="${Math.min(2, projectMaxConsecutive())}" min="1" max="${projectMaxConsecutive()}"></label><p class="muted">Giới hạn số tiết của môn này được phép xếp liền nhau trong cùng một buổi.</p>`;
  if (type === "teacher")
    h = `<label>Họ tên<input name="name" required></label><label>Tên ngắn<input name="short_name" required></label><label>Tổ chuyên môn<select name="department_id"><option value="">Không chọn</option>${opts(data.departments)}</select></label><label>Tối đa tiết/ngày<input type="number" name="max_periods_day" value="${Math.min(5, projectMaxPeriodsDay())}" min="1" max="${projectMaxPeriodsDay()}"></label>${teacherSubjectPicker()}`;
  if (type === "grade")
    h = `<label>Tên khối / nhóm<input name="name" required></label>${gradeRequirementPicker()}`;
  if (type === "class")
    h = `<label>Tên lớp<input name="name" required></label><label>Khối / nhóm<select name="grade_id"><option value="">Không chọn</option>${opts(data.grades)}</select></label>`;
  if (type === "assignment") {
    const eligibleTeachers = assignmentEligibleTeachers();
    h = `<div class="assignment-bulk-modal"><p class="assignment-bulk-intro">Chọn giáo viên trước, tick môn và lớp. Nếu các lớp đã có chương trình chuẩn theo khối, số tiết/tuần và chế độ xếp sẽ tự điền theo chương trình; hệ thống không lấy lại số tiết từ một lớp khác của giáo viên.</p><label>Giáo viên<select name="teacher_id" required onchange="renderBulkAssignmentChoices(this.value)" ${eligibleTeachers.length ? "" : "disabled"}><option value="">${eligibleTeachers.length ? "Chọn giáo viên" : "Chưa có giáo viên đã cấu hình môn dạy"}</option>${opts(eligibleTeachers)}</select></label>${eligibleTeachers.length ? "" : '<div class="assignment-bulk-empty assignment-bulk-empty-warning">Tài khoản giáo viên mới đăng ký không tự trở thành giáo viên trong phân công. Hãy tạo/cấu hình hồ sơ ở tab <b>Giáo viên</b> và chọn ít nhất một môn có thể dạy.</div>'}<div id="bulkAssignmentChoices"><div class="assignment-bulk-empty">${eligibleTeachers.length ? "Chọn giáo viên để hiện danh sách môn và lớp." : "Chưa thể tạo phân công."}</div></div></div>`;
  }
  $("#entityFields").innerHTML = h;
  if (type === "assignment") {
    entityModal
      .querySelector(".modal-form")
      ?.classList.add("assignment-bulk-form");
  } else {
    entityModal
      .querySelector(".modal-form")
      ?.classList.remove("assignment-bulk-form");
  }
  entityModal.showModal();
}
function editOpts(rows, selected, label = "name") {
  return rows
    .map(
      (x) =>
        `<option value="${x.id}" ${x.id === selected ? "selected" : ""}>${esc(x[label])}</option>`,
    )
    .join("");
}
function bulkRequirementForSelection(subjectId, classIds) {
  if (!classIds.length) return { status: "none" };
  const rows = [];
  for (const classId of classIds) {
    const schoolClass = data.classes.find((item) => item.id === classId);
    if (!schoolClass || schoolClass.grade_id == null) continue;
    const gradeRequirements = (data.grade_requirements || []).filter(
      (item) => item.grade_id === schoolClass.grade_id,
    );
    // Khối chưa cấu hình chương trình: cho phép nhập thủ công như trước.
    if (!gradeRequirements.length) continue;
    const requirement = gradeRequirements.find(
      (item) => item.subject_id === subjectId,
    );
    if (!requirement) return { status: "forbidden" };
    rows.push(requirement);
  }
  if (!rows.length) return { status: "open" };
  const first = rows[0],
    same = rows.every(
      (item) =>
        Number(item.periods_per_week) === Number(first.periods_per_week) &&
        String(item.block_mode || "free") ===
        String(first.block_mode || "free"),
    );
  return same
    ? {
      status: "exact",
      periods: Number(first.periods_per_week),
      mode: first.block_mode || "free",
    }
    : { status: "mixed" };
}

function syncBulkCurriculumDefaults(form, force = false) {
  if (!form) return;
  const classIds = [
    ...form.querySelectorAll('input[name="class_ids"]:checked'),
  ].map((input) => Number(input.value));
  form.querySelectorAll('input[name="subject_ids"]').forEach((subjectInput) => {
    const subjectId = Number(subjectInput.value),
      periodInput = form.querySelector(`[name="subject_periods_${subjectId}"]`),
      modeInput = form.querySelector(`[name="subject_mode_${subjectId}"]`),
      status = form.querySelector(`[data-subject-curriculum="${subjectId}"]`);
    if (!periodInput || !modeInput) return;
    const auto = force || periodInput.dataset.auto !== "0";
    const requirement = bulkRequirementForSelection(subjectId, classIds);
    if (requirement.status === "exact") {
      if (auto) {
        periodInput.value = requirement.periods;
        modeInput.value = requirement.mode;
        periodInput.dataset.auto = "1";
        modeInput.dataset.auto = "1";
      }
      if (status)
        status.textContent = `Theo chương trình lớp đã chọn: ${requirement.periods} tiết/tuần.`;
    } else if (requirement.status === "mixed") {
      if (auto) {
        periodInput.value = "";
        modeInput.value = "free";
      }
      if (status)
        status.textContent =
          "Các lớp đã chọn có chương trình khác nhau cho môn này. Hãy chia lần phân công theo từng khối/chương trình.";
    } else if (requirement.status === "forbidden") {
      if (auto) {
        periodInput.value = "";
        modeInput.value = "free";
      }
      if (status)
        status.textContent =
          "Môn này không thuộc chương trình của ít nhất một khối đã chọn.";
    } else if (requirement.status === "open") {
      if (status)
        status.textContent =
          "Có lớp thuộc khối chưa cấu hình chương trình; có thể nhập thủ công.";
    } else {
      if (auto) {
        periodInput.value = "";
        modeInput.value = "free";
      }
      if (status)
        status.textContent = "Chọn lớp để tự điền theo chương trình khối.";
    }
    updateBulkSubjectPreview(subjectId, form);
  });
}
function markBulkSubjectManual(subjectId, form) {
  const periodInput = form?.querySelector(
    `[name="subject_periods_${subjectId}"]`,
  ),
    modeInput = form?.querySelector(`[name="subject_mode_${subjectId}"]`);
  if (periodInput) periodInput.dataset.auto = "0";
  if (modeInput) modeInput.dataset.auto = "0";
  updateBulkSubjectPreview(subjectId, form);
  updateBulkAssignmentPreview(form);
}
function renderBulkAssignmentChoices(value) {
  const teacherId = Number(value),
    box = $("#bulkAssignmentChoices");
  if (!box) return;
  if (!teacherId) {
    box.innerHTML =
      '<div class="assignment-bulk-empty">Chọn giáo viên để hiện danh sách môn và lớp.</div>';
    return;
  }
  const teacher = data.teachers.find((item) => item.id === teacherId),
    allowed = new Set((teacher?.subject_ids || []).map(Number)),
    subjects = data.subjects
      .filter((item) => allowed.has(item.id))
      .sort((a, b) => a.name.localeCompare(b.name, "vi")),
    classes = [...data.classes].sort((a, b) =>
      a.name.localeCompare(b.name, "vi"),
    );
  if (!subjects.length) {
    box.innerHTML =
      '<div class="assignment-bulk-empty">Giáo viên này chưa được cấu hình môn có thể dạy. Hãy vào mục Giáo viên → Sửa và tick môn trước.</div>';
    return;
  }
  const modeOptions = `<option value="free">Tự do</option><option value="preferred_double">Ưu tiên tiết đôi</option><option value="required_double">Bắt buộc tiết đôi</option>`;
  const subjectRows = subjects
    .map(
      (item) =>
        `<div class="assignment-subject-item"><label class="assignment-pick-row"><input type="checkbox" name="subject_ids" value="${item.id}" onchange="toggleBulkSubjectSettings(this);syncBulkCurriculumDefaults(this.form);updateBulkAssignmentPreview(this.form)"><span>${esc(item.name)}</span></label><div class="assignment-subject-config" data-subject-settings="${item.id}" hidden><label>Tiết/tuần<input type="number" name="subject_periods_${item.id}" min="1" max="40" value="" placeholder="Theo khối" data-auto="1" oninput="markBulkSubjectManual(${item.id},this.form)" onchange="markBulkSubjectManual(${item.id},this.form)"></label><label>Chế độ xếp<select name="subject_mode_${item.id}" data-auto="1" onchange="markBulkSubjectManual(${item.id},this.form)">${modeOptions}</select></label><div class="block-mode-preview" data-subject-preview="${item.id}"></div><small class="teacher-subject-help" data-subject-curriculum="${item.id}">Chọn lớp để tự điền theo chương trình khối.</small></div></div>`,
    )
    .join("");
  const classRows = classes.length
    ? classes
      .map((item) => {
        const grade = data.grades.find((g) => g.id === item.grade_id);
        return `<label class="assignment-pick-row"><input type="checkbox" name="class_ids" value="${item.id}" onchange="syncBulkCurriculumDefaults(this.form);updateBulkAssignmentPreview(this.form)"><span>${esc(item.name)}${grade ? ` <small>${esc(grade.name)}</small>` : ""}</span></label>`;
      })
      .join("")
    : '<div class="assignment-bulk-empty">Chưa có lớp học.</div>';
  box.innerHTML = `<div id="bulkTeacherLoad"></div><div class="assignment-bulk-grid"><div class="assignment-pick-panel"><div class="assignment-pick-head"><b>Môn học của giáo viên</b><div class="assignment-pick-actions"><button type="button" onclick="selectBulkAssignmentGroup('subject_ids',true)">Chọn tất cả</button><button type="button" onclick="selectBulkAssignmentGroup('subject_ids',false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${subjectRows}</div></div><div class="assignment-pick-panel"><div class="assignment-pick-head"><b>Lớp học</b><div class="assignment-pick-actions"><button type="button" onclick="selectBulkAssignmentGroup('class_ids',true)">Chọn tất cả</button><button type="button" onclick="selectBulkAssignmentGroup('class_ids',false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${classRows}</div></div></div><div id="bulkAssignmentPreview" class="assignment-bulk-preview"></div>`;
  const form = entityModal.querySelector("form");
  if (pendingAssignmentGap) {
    const subjectInput = form.querySelector(
      `input[name="subject_ids"][value="${pendingAssignmentGap.subjectId}"]`,
    ),
      classInput = form.querySelector(
        `input[name="class_ids"][value="${pendingAssignmentGap.classId}"]`,
      );
    if (subjectInput) {
      subjectInput.checked = true;
      toggleBulkSubjectSettings(subjectInput);
    }
    if (classInput) classInput.checked = true;
    if (!subjectInput) {
      box.insertAdjacentHTML(
        "afterbegin",
        '<div class="assignment-warning" style="padding:10px 12px">Giáo viên này chưa được cấu hình dạy môn đang thiếu. Hãy chọn giáo viên khác hoặc cập nhật môn dạy của giáo viên.</div>',
      );
    }
  }
  syncBulkCurriculumDefaults(form, true);
  updateBulkAssignmentPreview(form);
}
function toggleBulkSubjectSettings(input) {
  const box = input.form?.querySelector(
    `[data-subject-settings="${input.value}"]`,
  );
  if (box) box.hidden = !input.checked;
  if (input.checked) {
    syncBulkCurriculumDefaults(input.form);
    updateBulkSubjectPreview(Number(input.value), input.form);
  }
}
function updateBulkSubjectPreview(subjectId, form) {
  if (!form) return;
  const total = Number(
    form.querySelector(`[name="subject_periods_${subjectId}"]`)?.value || 0,
  ),
    mode =
      form.querySelector(`[name="subject_mode_${subjectId}"]`)?.value || "free",
    preview = form.querySelector(`[data-subject-preview="${subjectId}"]`);
  if (preview)
    preview.textContent =
      total > 0 ? describeBlockMode(mode, total) : "Chưa có số tiết/tuần.";
}
function selectBulkAssignmentGroup(name, checked) {
  const form = entityModal.querySelector("form");
  if (!form) return;
  form.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
    input.checked = checked;
    if (name === "subject_ids") toggleBulkSubjectSettings(input);
  });
  syncBulkCurriculumDefaults(form);
  updateBulkAssignmentPreview(form);
}
function updateBulkAssignmentPreview(form) {
  const preview = $("#bulkAssignmentPreview");
  if (!preview || !form) return;
  const teacherId = Number(
    form.querySelector('[name="teacher_id"]')?.value || 0,
  ),
    teacher = data.teachers.find((item) => item.id === teacherId),
    subjectIds = [
      ...form.querySelectorAll('input[name="subject_ids"]:checked'),
    ].map((input) => Number(input.value)),
    classIds = [
      ...form.querySelectorAll('input[name="class_ids"]:checked'),
    ].map((input) => Number(input.value)),
    total = subjectIds.length * classIds.length;
  const subjectSet = new Set(subjectIds),
    classSet = new Set(classIds),
    existing = data.assignments.filter(
      (item) => subjectSet.has(item.subject_id) && classSet.has(item.class_id),
    );
  let addedPeriods = 0;
  for (const subjectId of subjectIds) {
    const periods = Number(
      form.querySelector(`[name="subject_periods_${subjectId}"]`)?.value || 0,
    );
    for (const classId of classIds) {
      if (
        !existing.some(
          (item) => item.subject_id === subjectId && item.class_id === classId,
        )
      )
        addedPeriods += periods;
    }
  }
  const current = Number(teacher?.assigned_periods || 0),
    projected = current + addedPeriods,
    loadBox = $("#bulkTeacherLoad");
  if (loadBox) loadBox.innerHTML = teacherLoadCardHtml(teacher, projected);
  if (!total) {
    preview.innerHTML =
      "Hãy tick ít nhất 1 môn và 1 lớp. Tải giáo viên phía trên sẽ cập nhật ngay khi bạn chọn.";
    return;
  }
  const forbiddenSubjects = subjectIds.filter(
    (subjectId) =>
      bulkRequirementForSelection(subjectId, classIds).status === "forbidden",
  );
  if (forbiddenSubjects.length) {
    preview.innerHTML = `<span class="assignment-warning">Có ${forbiddenSubjects.length} môn không thuộc chương trình của ít nhất một lớp đã chọn. Hãy bỏ môn/lớp đó hoặc cập nhật chương trình khối.</span>`;
    return;
  }
  const mixedSubjects = subjectIds.filter(
    (subjectId) =>
      bulkRequirementForSelection(subjectId, classIds).status === "mixed",
  );
  if (mixedSubjects.length) {
    preview.innerHTML = `<span class="assignment-warning">Có ${mixedSubjects.length} môn có số tiết/chế độ khác nhau giữa các lớp đã chọn. Hãy chia lần phân công theo từng khối/chương trình để tránh gán sai.</span>`;
    return;
  }
  const duplicates = existing.filter(
    (item) => item.teacher_id === teacherId,
  ).length,
    conflicts = existing.filter((item) => item.teacher_id !== teacherId).length,
    staleDuplicates = existing.filter((item) => {
      if (item.teacher_id !== teacherId) return false;
      const periods = Number(
        form.querySelector(`[name="subject_periods_${item.subject_id}"]`)?.value ||
        0,
      );
      const mode =
        form.querySelector(`[name="subject_mode_${item.subject_id}"]`)?.value ||
        "free";
      return (
        Number(item.periods_per_week) !== periods ||
        String(item.block_mode || "free") !== String(mode)
      );
    }).length,
    fresh = Math.max(0, total - duplicates - conflicts),
    capacity = teacher?.week_capacity;
  let status = "";
  if (conflicts)
    status = `<span class="assignment-warning">Có ${conflicts} cặp lớp–môn đã thuộc giáo viên khác; hệ thống sẽ không cho lưu cho đến khi xử lý các phân công đó.</span>`;
  else if (staleDuplicates)
    status = `<span class="assignment-warning">Có ${staleDuplicates} cặp đã tồn tại nhưng số tiết/chế độ khác cấu hình đang chọn. Hệ thống sẽ không bỏ qua âm thầm; hãy sửa phân công hiện có hoặc bỏ các cặp đó khỏi lần phân công này.</span>`;
  else if (capacity != null && projected > Number(capacity))
    status = `<span class="assignment-warning">Tải dự kiến ${projected}/${capacity} tiết/tuần vượt khả năng xếp của giáo viên.</span>`;
  else
    status =
      capacity == null
        ? ""
        : `<span class="assignment-ok">Tải giáo viên: ${projected}/${capacity} tiết/tuần.</span>`;
  preview.innerHTML = `Đã chọn <b>${subjectIds.length}</b> môn × <b>${classIds.length}</b> lớp = <b>${total}</b> cặp. ${duplicates ? `Có ${duplicates} cặp đã tồn tại; ` : ""}dự kiến tạo mới <b>${fresh}</b> phân công, thêm <b>${addedPeriods}</b> tiết/tuần.${status}`;
}
function openEntityEdit(type, id) {
  const rows =
    {
      department: data.departments,
      subject: data.subjects,
      teacher: data.teachers,
      grade: data.grades,
      class: data.classes,
    }[type] || [];
  const item = rows.find((x) => x.id === Number(id));
  if (!item) return;
  entityType = `${type}_edit`;
  entityId = item.id;
  entityModal
    .querySelector(".modal-form")
    ?.classList.remove("assignment-bulk-form");
  const titles = {
    department: "Sửa tổ chuyên môn",
    subject: "Sửa môn học",
    teacher: "Sửa giáo viên",
    grade: "Sửa khối / nhóm",
    class: "Sửa lớp học",
  };
  $("#modalTitle").textContent = titles[type];
  let h = "";
  if (type === "department")
    h = `<label>Tên tổ chuyên môn<input name="name" value="${esc(item.name)}" maxlength="120" required></label>`;
  if (type === "subject")
    h = `<label>Tên môn học<input name="name" value="${esc(item.name)}" required></label><label>Tên rút gọn<input name="short_name" value="${esc(item.short_name)}" required></label><label>Số tiết liên tiếp tối đa<input type="number" name="max_consecutive" value="${Math.min(Number(item.max_consecutive) || 1, projectMaxConsecutive())}" min="1" max="${projectMaxConsecutive()}" required></label><p class="muted">Giới hạn số tiết của môn này được phép xếp liền nhau trong cùng một buổi.</p>`;
  if (type === "teacher")
    h = `<label>Họ tên<input name="name" value="${esc(item.name)}" required></label><label>Tên ngắn<input name="short_name" value="${esc(item.short_name)}" required></label><label>Tổ chuyên môn<select name="department_id"><option value="">Không chọn</option>${editOpts(data.departments, item.department_id)}</select></label><label>Tối đa tiết/ngày<input type="number" name="max_periods_day" value="${Math.min(Number(item.max_periods_day) || 1, projectMaxPeriodsDay())}" min="1" max="${projectMaxPeriodsDay()}" required></label>${teacherSubjectPicker(item.subject_ids || [])}`;
  if (type === "grade")
    h = `<label>Tên khối / nhóm<input name="name" value="${esc(item.name)}" required></label>${gradeRequirementPicker((data.grade_requirements || []).filter((row) => row.grade_id === item.id))}`;
  if (type === "class")
    h = `<label>Tên lớp<input name="name" value="${esc(item.name)}" required></label><label>Khối / nhóm<select name="grade_id"><option value="">Không chọn</option>${editOpts(data.grades, item.grade_id)}</select></label>`;
  $("#entityFields").innerHTML = h;
  entityModal.showModal();
}
function openAssignmentEdit(id) {
  const item = data.assignments.find((x) => x.id === id);
  if (!item) return;
  entityType = "assignment_edit";
  entityModal
    .querySelector(".modal-form")
    ?.classList.remove("assignment-bulk-form");
  $("#modalTitle").textContent = "Sửa phân công";
  $("#entityFields").innerHTML =
    `<div class="assignment-summary"><b>${esc(item.class_name)} · ${esc(item.subject_name)}</b><span>${esc(item.teacher_name)}</span></div><input type="hidden" name="assignment_id" value="${item.id}"><label>Số tiết/tuần<input type="number" name="periods_per_week" min="1" max="40" value="${item.periods_per_week}" required oninput="updateAssignmentEditPreview(this.form)" onchange="updateAssignmentEditPreview(this.form)"></label><div data-assignment-edit-load></div>${blockModeEditor(item.block_mode)}`;
  updateAssignmentEditPreview(entityModal.querySelector("form"));
  entityModal.showModal();
}
async function updateWithScheduleConfirmation(url, payload) {
  // Entity edits put their fields in data; assignment edits use the root body.
  const fields = payload.data || payload;
  for (let attempt = 0; attempt < 5; attempt++) {
    const response = await fetch(url, {
      method: "PUT",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    const result = await readApiResponse(response);
    if (response.ok) return { response, result, cancelled: false };
    const displacement = result?.reason === "schedule_displacement";
    const extraAssignments = [
      "class_grade_extra_assignments", "grade_program_extra_assignments",
    ].includes(result?.reason);
    if (!displacement && !extraAssignments)
      return { response, result, cancelled: false };
    const confirmed = await confirmAction(result.message, {
      title: displacement ? "Xác nhận thay đổi lịch" : "Xác nhận xóa phân công",
      confirmText: displacement ? "Lưu và gỡ tiết" : "Xóa phân công dư và lưu",
    });
    if (!confirmed) return { response, result, cancelled: true };
    if (displacement) {
      fields.confirm_displacement = true;
      fields.confirmed_displaced_lesson_ids = result.affected_lesson_ids;
    } else {
      fields.remove_extra_assignments = true;
    }
  }
  throw new Error("Dữ liệu lịch đã thay đổi nhiều lần. Hãy tải lại dữ liệu và thử lại.");
}

async function submitEntity(e) {
  e.preventDefault();
  const form = e.target,
    formData = new FormData(form),
    o = Object.fromEntries(formData),
    submitButton = e.submitter || $("#entitySubmitButton");
  setEntityActionMessage("");
  setInlineActionState(submitButton, "loading", {
    idle: "Lưu",
    loading: "Đang lưu...",
  });
  for (const k of [
    "department_id",
    "grade_id",
    "class_id",
    "subject_id",
    "teacher_id",
    "assignment_id",
    "max_periods_day",
    "max_consecutive",
    "periods_per_week",
  ])
    if (o[k]) o[k] = Number(o[k]);
  if (entityType === "teacher" || entityType === "teacher_edit")
    o.subject_ids = formData.getAll("subject_ids").map(Number).filter(Boolean);
  if (entityType === "grade" || entityType === "grade_edit") {
    o.subject_requirements = formData
      .getAll("grade_subject_ids")
      .map(Number)
      .filter(Boolean)
      .map((subject_id) => ({
        subject_id,
        periods_per_week: Number(
          form.querySelector(`[name="grade_subject_periods_${subject_id}"]`)
            ?.value || 0,
        ),
        block_mode:
          form.querySelector(`[name="grade_subject_mode_${subject_id}"]`)
            ?.value || "free",
      }));
    if (
      o.subject_requirements.some(
        (item) =>
          !Number.isInteger(item.periods_per_week) || item.periods_per_week < 1,
      )
    ) {
      entityActionError(
        submitButton,
        "Số tiết/tuần trong chương trình khối phải từ 1 trở lên.",
      );
      return;
    }
  }
  try {
    if (entityType === "assignment") {
      const subject_ids = formData
        .getAll("subject_ids")
        .map(Number)
        .filter(Boolean),
        class_ids = formData.getAll("class_ids").map(Number).filter(Boolean);
      if (!o.teacher_id) {
        entityActionError(submitButton, "Hãy chọn giáo viên.");
        return;
      }
      if (!subject_ids.length) {
        entityActionError(submitButton, "Hãy chọn ít nhất một môn học.");
        return;
      }
      if (!class_ids.length) {
        entityActionError(submitButton, "Hãy chọn ít nhất một lớp.");
        return;
      }
      const forbiddenSubject = subject_ids.find(
        (subject_id) =>
          bulkRequirementForSelection(subject_id, class_ids).status === "forbidden",
      );
      if (forbiddenSubject) {
        const subject = data.subjects.find((item) => item.id === forbiddenSubject);
        entityActionError(
          submitButton,
          `${subject?.name || "Môn đã chọn"} không thuộc chương trình của ít nhất một lớp đã chọn.`,
        );
        return;
      }
      const mixedSubject = subject_ids.find(
        (subject_id) =>
          bulkRequirementForSelection(subject_id, class_ids).status === "mixed",
      );
      if (mixedSubject) {
        const subject = data.subjects.find((item) => item.id === mixedSubject);
        entityActionError(
          submitButton,
          `${subject?.name || "Môn đã chọn"} có chương trình khác nhau giữa các lớp. Hãy chia lần phân công theo từng khối.`,
        );
        return;
      }
      const subjects = subject_ids.map((subject_id) => ({
        subject_id,
        periods_per_week: Number(
          form.querySelector(`[name="subject_periods_${subject_id}"]`)?.value ||
          0,
        ),
        block_mode:
          form.querySelector(`[name="subject_mode_${subject_id}"]`)?.value ||
          "free",
      }));
      if (
        subjects.some(
          (item) =>
            !Number.isInteger(item.periods_per_week) ||
            item.periods_per_week < 1,
        )
      ) {
        entityActionError(
          submitButton,
          "Số tiết/tuần của mỗi môn phải từ 1 trở lên.",
        );
        return;
      }
      const r = await fetch(`/api/projects/${PROJECT_ID}/assignments/bulk`, {
        method: "POST",
        headers: operationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ teacher_id: o.teacher_id, class_ids, subjects }),
      });
      const result = await readApiResponse(r);
      if (!r.ok) {
        entityActionError(
          submitButton,
          apiErrorMessage(result, "Không thể thêm phân công."),
        );
        return;
      }
      setInlineActionState(submitButton, "success", {
        idle: "Lưu",
        success: "Đã lưu",
      });
      setEntityActionMessage(
        result.message || `Đã tạo ${result.created || 0} phân công.`,
        "success",
      );
      await wait(650);
      entityModal.close();
      await refreshAfterSuccessfulMutation();
      return;
    }
    if (entityType === "assignment_edit") {
      const { response: r, result, cancelled } = await updateWithScheduleConfirmation(
        `/api/projects/${PROJECT_ID}/assignments/${o.assignment_id}`,
        { periods_per_week: o.periods_per_week, block_mode: o.block_mode },
      );
      if (cancelled) {
        setInlineActionState(submitButton, "idle", { idle: "Lưu" });
        setEntityActionMessage("Đã hủy. Phân công và lịch hiện tại được giữ nguyên.", "info");
        return;
      }
      if (!r.ok) {
        entityActionError(
          submitButton,
          apiErrorMessage(result, "Không thể cập nhật phân công."),
        );
        return;
      }
      setInlineActionState(submitButton, "success", {
        idle: "Lưu",
        success: "Đã cập nhật",
      });
      const message = result.displaced_lessons
        ? `Đã cập nhật phân công và gỡ ${result.displaced_lessons} tiết khỏi lịch. Phần còn thiếu nằm trong khay để xếp lại.`
        : "Đã cập nhật phân công.";
      setEntityActionMessage(message, "success");
      await wait(650);
      entityModal.close();
      const refreshed = await refreshAfterSuccessfulMutation();
      if (refreshed) showToast(message, "success", 6000);
      return;
    }
    if (entityType.endsWith("_edit")) {
      const type = entityType.replace("_edit", "");
      const { response: r, result, cancelled } = await updateWithScheduleConfirmation(
        `/api/projects/${PROJECT_ID}/entity/${type}/${entityId}`,
        { type, data: o },
      );
      if (cancelled) {
        setInlineActionState(submitButton, "idle", { idle: "Lưu" });
        setEntityActionMessage("Đã hủy. Dữ liệu và lịch hiện tại được giữ nguyên.", "info");
        return;
      }

      if (!r.ok) {
        entityActionError(
          submitButton,
          apiErrorMessage(result, "Không thể cập nhật dữ liệu."),
        );
        return;
      }
      setInlineActionState(submitButton, "success", {
        idle: "Lưu",
        success: "Đã cập nhật",
      });
      const syncedAssignments = Number(result.synced_assignments || 0),
        removedExtraAssignments = Number(result.removed_extra_assignments || 0),
        missingGradeAssignments = Number(
          result.missing_grade_assignments_count || 0,
        ),
        messages = ["Đã cập nhật dữ liệu."];
      if (syncedAssignments > 0)
        messages.push(
          `Đã đồng bộ ${syncedAssignments} phân công theo chương trình khối.`,
        );
      if (removedExtraAssignments > 0)
        messages.push(
          `Đã xóa ${removedExtraAssignments} phân công không thuộc chương trình khối mới.`,
        );
      if (result.displaced_lessons > 0)
        messages.push(`Đã gỡ ${result.displaced_lessons} tiết khỏi lịch; phần còn thiếu nằm trong khay để xếp lại.`);
      if (missingGradeAssignments > 0)
        messages.push(
          `Còn ${missingGradeAssignments} phân công lớp–môn cần bổ sung giáo viên ở mục Phân công.`,
        );
      setEntityActionMessage(
        messages.join(" "),
        missingGradeAssignments > 0 ? "info" : "success",
      );
      await wait(650);
      entityModal.close();
      const refreshed = await refreshAfterSuccessfulMutation();
      if (refreshed)
        showToast(messages.join(" "), missingGradeAssignments > 0 ? "warning" : "success", 7000);
      return;
    }
    const r = await fetch(`/api/projects/${PROJECT_ID}/entity`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ type: entityType, data: o }),
    });
    const result = await readApiResponse(r);
    if (!r.ok) {
      entityActionError(
        submitButton,
        apiErrorMessage(result, "Không thể lưu dữ liệu."),
      );
      return;
    }
    setInlineActionState(submitButton, "success", {
      idle: "Lưu",
      success: "Đã lưu",
    });
    setEntityActionMessage("Đã lưu dữ liệu.", "success");
    await wait(650);
    entityModal.close();
    await refreshAfterSuccessfulMutation();
  } catch (error) {
    entityActionError(
      submitButton,
      requestFailureMessage(error, "Mất kết nối tới máy chủ. Vui lòng thử lại."),
    );
  }
}
async function delEntity(type, id, button) {
  if (type !== "assignment") {
    if (!(await confirmAction("Xóa mục này?", { confirmText: "Xóa" }))) return;
  }

  setInlineActionState(button, "loading", {
    idle: "Xóa",
    loading: type === "assignment" ? "Đang kiểm tra..." : "Đang xóa...",
  });

  try {
    let confirmation = null;
    for (let attemptIndex = 0; attemptIndex < 3; attemptIndex++) {
      const headers = operationHeaders();
      const request = {
        method: "DELETE",
        headers,
      };
      if (type === "assignment") {
        request.headers = operationHeaders({ "Content-Type": "application/json" });
        request.body = JSON.stringify(confirmation || {});
      }

      const r = await fetch(`/api/projects/${PROJECT_ID}/entity/${type}/${id}`, request);
      const result = await readApiResponse(r);

      if (type === "assignment" && !r.ok && result?.requires_confirmation) {
        const confirmed = await confirmAction(
          result.message || "Xóa phân công này? Thao tác này không thể hoàn tác.",
          {
            title: "Xác nhận xóa phân công",
            confirmText: "Xóa phân công",
          },
        );
        if (!confirmed) {
          setInlineActionState(button, "idle", { idle: "Xóa" });
          return;
        }
        confirmation = {
          confirm_assignment_cascade: true,
          confirmed_lesson_ids: Array.isArray(result.lesson_ids) ? result.lesson_ids : [],
          confirmed_fixed_lesson_ids: Array.isArray(result.fixed_lesson_ids)
            ? result.fixed_lesson_ids
            : [],
        };
        setInlineActionState(button, "loading", {
          idle: "Xóa",
          loading: "Đang xóa...",
        });
        continue;
      }

      if (r.ok) {
        setInlineActionState(button, "success", {
          idle: "Xóa",
          success: "Đã xóa",
        });
        await wait(450);
        await refreshAfterSuccessfulMutation();
      } else {
        setInlineActionState(
          button,
          "error",
          { idle: "Xóa", error: "Không thể xóa" },
          2200,
        );
        showInlineActionFeedback(
          button,
          apiErrorMessage(result, "Không thể xóa dữ liệu. Vui lòng thử lại."),
          "error",
          5000,
        );
      }
      return;
    }
    throw new Error("Dữ liệu lịch thay đổi trong lúc xác nhận. Hãy thử xóa lại.");
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Xóa", error: "Chưa hoàn tất" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
function exportFilenameFromResponse(response) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch { }
  }
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1]?.trim() || "thoi-khoa-bieu.xlsx";
}
async function handleExportExcel(event, link) {
  if (!link) return;
  event?.preventDefault?.();
  if (link.dataset.exportBusy === "1") return;

  const originalHtml = link.innerHTML;
  link.dataset.exportBusy = "1";
  link.innerHTML = '<span class="btn-spinner"></span> Đang tạo tệp...';
  link.style.pointerEvents = "none";
  link.setAttribute("aria-busy", "true");

  try {
    const response = await fetch(link.href, {
      method: "GET",
      headers: operationHeaders({
        Accept: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "X-Requested-With": "XMLHttpRequest",
      }),
    });
    if (response.status === 401 ||
      (response.redirected && new URL(response.url, location.href).pathname === "/login")) {
      location.href = "/login";
      throw new Error("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại để xuất Excel.");
    }
    if (!response.ok) {
      const result = await readApiResponse(response);
      throw new Error(
        apiErrorMessage(result, `Không thể xuất Excel (HTTP ${response.status}).`),
      );
    }

    const contentType = (response.headers.get("Content-Type") || "")
      .split(";")[0].trim().toLowerCase();
    if (contentType !== "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") {
      throw new Error("Máy chủ không trả về tệp Excel hợp lệ. Hãy tải lại trang và thử lại.");
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error("Máy chủ trả về tệp Excel rỗng.");

    const downloadUrl = URL.createObjectURL(blob);
    const downloadLink = document.createElement("a");
    downloadLink.href = downloadUrl;
    downloadLink.download = exportFilenameFromResponse(response);
    downloadLink.style.display = "none";
    document.body.appendChild(downloadLink);
    downloadLink.click();
    downloadLink.remove();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);

    showToast("Đã tạo file Excel và bắt đầu tải xuống.", "success", 3200);
  } catch (error) {
    showToast(
      error?.message || "Không thể xuất Excel. Vui lòng thử lại.",
      "error",
      5000,
    );
  } finally {
    link.innerHTML = originalHtml;
    link.style.pointerEvents = "";
    link.removeAttribute("aria-busy");
    delete link.dataset.exportBusy;
  }
}
window.handleExportExcel = handleExportExcel;

