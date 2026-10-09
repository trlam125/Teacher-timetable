"use strict";
function scheduleAuditDisplayLessonParts(item) {
  const raw = String(item.raw_text || "").trim();
  const teacher = String(item.teacher_name || "")
    .trim()
    .replace(/^[.\-–—:;,\s]+/, "");
  let subject = String(item.subject_name || "").trim();

  if (raw && teacher) {
    const escapedTeacher = teacher
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/\s+/g, "\\s+");
    const parsedSubject = raw
      .replace(new RegExp(`[.\\-–—:;,\\s]*${escapedTeacher}\\s*$`, "i"), "")
      .trim()
      .replace(/[.\-–—:;,\s]+$/, "")
      .trim();
    if (parsedSubject) subject = parsedSubject;
  }
  return { subject, teacher, raw };
}
function scheduleAuditEditableLessonHtml(item) {
  const parts = scheduleAuditDisplayLessonParts(item),
    draftId = Number(item.draft_id);
  const subject = parts.subject || String(item.subject_name || "").trim();
  const teacher = parts.teacher || String(item.teacher_name || "").trim();
  const pieces = [];
  if (subject) {
    pieces.push(
      `<span class="schedule-view-editable schedule-view-editable-subject" role="button" tabindex="0" data-draft-id="${draftId}" data-field="subject_name" title="Bấm để sửa tên môn" onclick="beginScheduleAuditInlineEdit(this,event)" onkeydown="handleScheduleAuditEditableKey(event,this)">${esc(subject)}</span>`,
    );
  }
  if (subject && teacher)
    pieces.push(
      '<span class="schedule-view-name-separator" aria-hidden="true"> - </span>',
    );
  if (teacher) {
    pieces.push(
      `<span class="schedule-view-editable schedule-view-editable-teacher" role="button" tabindex="0" data-draft-id="${draftId}" data-field="teacher_name" title="Bấm để sửa tên giáo viên" onclick="beginScheduleAuditInlineEdit(this,event)" onkeydown="handleScheduleAuditEditableKey(event,this)">${esc(teacher)}</span>`,
    );
  }
  return pieces.join("") || esc(parts.raw);
}
function scheduleAuditCellHtml(entries, aiIssues = []) {
  if (!entries?.length) return '<td class="schedule-view-cell empty"></td>';
  const hasConflict = entries.some((item) => (item.conflicts || []).length);
  const hasAiWarning = aiIssues.some((item) => item.severity === "warning");
  const hasAiSuggestion = aiIssues.length > 0 && !hasAiWarning;
  const conflictCodes = [
    ...new Set(entries.flatMap((item) => item.conflicts || [])),
  ];
  const details = [
    ...new Set(entries.flatMap((item) => item.conflict_details || [])),
  ];
  const aiDetails = aiIssues.map(
    (item) => `AI: ${item.title}${item.message ? ` — ${item.message}` : ""}`,
  );
  const title = [
    ...details,
    ...aiDetails,
    ...entries.map((item) => item.source).filter(Boolean),
  ].join("\n");
  const stateClass = hasConflict
    ? " conflict"
    : hasAiWarning
      ? " ai-warning"
      : hasAiSuggestion
        ? " ai-suggestion"
        : "";
  return `<td class="schedule-view-cell${stateClass}"${title ? ` title="${esc(title)}"` : ""}>${entries.map((item) => `<div class="schedule-view-lesson"><b class="schedule-view-lesson-line">${scheduleAuditEditableLessonHtml(item)}</b>${item.room ? `<small>Phòng ${esc(item.room)}</small>` : ""}</div>`).join("")}${hasConflict ? `<div class="schedule-view-conflict-tags">${conflictCodes.map((code) => `<span>! ${esc(scheduleAuditConflictLabel(code))}</span>`).join("")}</div>` : ""}${aiIssues.length ? `<div class="schedule-view-ai-tags"><span class="${hasAiWarning ? "warning" : "suggestion"}">✦ ${esc(scheduleAuditAiSeverityLabel(hasAiWarning ? "warning" : "suggestion"))}</span></div>` : ""}</td>`;
}
function handleScheduleAuditEditableKey(event, element) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    beginScheduleAuditInlineEdit(element, event);
  }
}
function scheduleAuditSlotLabelForEdit(slot, viewer) {
  const part = scheduleAuditSlotParts(slot, viewer),
    session = scheduleAuditSessionName(part.session, viewer.sessions);
  return [scheduleAuditDayName(part.day), session, `tiết ${part.period}`]
    .filter(Boolean)
    .join(", ");
}
function scheduleAuditBuildStatistics(viewer) {
  const cells = viewer?.cells || [],
    teacherMap = new Map(),
    subjectMap = new Map(),
    classMap = new Map();
  const bump = (map, name) => map.set(name, (map.get(name) || 0) + 1);
  const getEntity = (map, key, name, id) => {
    if (!map.has(key))
      map.set(key, {
        id,
        name,
        total_lessons: 0,
        subjects: new Map(),
        teachers: new Map(),
        classes: new Map(),
      });
    return map.get(key);
  };
  for (const cell of cells) {
    const className = String(cell.class_name || "").trim(),
      subjectName = String(cell.subject_name || "").trim(),
      teacherName = String(cell.teacher_name || "").trim();
    const knownSubject =
      subjectName && !scheduleAuditIsUnknownSubject(subjectName),
      knownTeacher = teacherName && !scheduleAuditIsUnknownTeacher(teacherName);
    if (knownTeacher) {
      const row = getEntity(
        teacherMap,
        scheduleAuditIdentityKey(teacherName),
        teacherName,
        teacherMap.size + 1,
      );
      row.total_lessons += 1;
      if (knownSubject) bump(row.subjects, subjectName);
      if (className) bump(row.classes, className);
    }
    if (knownSubject) {
      const row = getEntity(
        subjectMap,
        scheduleAuditIdentityKey(subjectName),
        subjectName,
        subjectMap.size + 1,
      );
      row.total_lessons += 1;
      if (knownTeacher) bump(row.teachers, teacherName);
      if (className) bump(row.classes, className);
    }
    const classKey = String(cell.class_id ?? className);
    const row = getEntity(
      classMap,
      classKey,
      className || `Lớp ${cell.class_id}`,
      Number(cell.class_id) || classMap.size + 1,
    );
    row.total_lessons += 1;
    if (knownSubject) bump(row.subjects, subjectName);
    if (knownTeacher) bump(row.teachers, teacherName);
  }
  const breakdown = (map) =>
    [...map.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "vi"))
      .map(([name, lessons]) => ({ name, lessons }));
  const finalize = (map, fields) =>
    [...map.values()]
      .map((row) => {
        const out = {
          id: row.id,
          name: row.name,
          total_lessons: row.total_lessons,
        };
        for (const field of fields) out[field] = breakdown(row[field]);
        return out;
      })
      .sort(
        (a, b) =>
          b.total_lessons - a.total_lessons ||
          a.name.localeCompare(b.name, "vi"),
      );
  const teachers = finalize(teacherMap, ["subjects", "classes"]),
    subjects = finalize(subjectMap, ["teachers", "classes"]),
    classes = finalize(classMap, ["subjects", "teachers"]);
  const leader = (rows) =>
    rows.length
      ? { name: rows[0].name, lessons: Number(rows[0].total_lessons || 0) }
      : null;
  const totalLessons = cells.length,
    knownTeacherLessons = teachers.reduce(
      (sum, row) => sum + Number(row.total_lessons || 0),
      0,
    );
  return {
    overview: {
      total_lessons: totalLessons,
      total_teachers: teachers.length,
      total_subjects: subjects.length,
      total_classes: classes.length,
      avg_lessons_per_teacher: teachers.length
        ? Math.round((knownTeacherLessons / teachers.length) * 100) / 100
        : 0,
      avg_lessons_per_class: classes.length
        ? Math.round((totalLessons / classes.length) * 100) / 100
        : 0,
      busiest_teacher: leader(teachers),
      largest_subject: leader(subjects),
      busiest_class: leader(classes),
    },
    teachers,
    subjects,
    classes,
  };
}
function scheduleAuditRecalculateAfterEdit(report) {
  if (!report?.viewer) return;
  const viewer = report.viewer,
    cells = viewer.cells || [];
  const dynamicCodes = new Set([
    "teacher_collision",
    "class_collision",
    "room_collision",
    "unknown_subject",
    "unknown_teacher",
  ]);
  const retainedIssues = (report.issues || []).filter(
    (issue) => !dynamicCodes.has(issue.code),
  );
  for (const cell of cells) {
    cell.conflicts = [];
    cell.conflict_details = [];
  }
  const collisionIssues = [],
    inferredIssues = [],
    affected = new Set();
  const addConflict = (code, title, detail, rows, entity) => {
    const slot = Number(rows[0]?.slot || 0);
    for (const row of rows) {
      if (!row.conflicts.includes(code)) row.conflicts.push(code);
      if (!row.conflict_details.includes(detail))
        row.conflict_details.push(detail);
      affected.add(`${Number(row.slot)}:${Number(row.class_id)}`);
    }
    collisionIssues.push({
      code,
      severity: "error",
      title,
      detail,
      slot,
      slot_label: scheduleAuditSlotLabelForEdit(slot, viewer),
      entity: entity || "",
      source: [...new Set(rows.map((row) => row.source).filter(Boolean))].join(
        "; ",
      ),
    });
  };
  const addInferredIssue = (code, title, detail, cell, entity) => {
    const key = `${code}:${Number(cell.slot)}:${Number(cell.class_id)}:${scheduleAuditEntityKey(entity)}`;
    if (inferredIssues.some((issue) => issue._key === key)) return;
    inferredIssues.push({
      _key: key,
      code,
      severity: "warning",
      title,
      detail,
      slot: Number(cell.slot),
      slot_label: scheduleAuditSlotLabelForEdit(Number(cell.slot), viewer),
      entity: entity || "",
      source: cell.source || "",
    });
  };
  const classGroups = new Map(),
    teacherGroups = new Map(),
    roomGroups = new Map();
  for (const cell of cells) {
    const slot = Number(cell.slot),
      classId = Number(cell.class_id),
      classKey = `${slot}:${classId}`;
    if (!classGroups.has(classKey)) classGroups.set(classKey, []);
    classGroups.get(classKey).push(cell);
    const subjectName = String(cell.subject_name || "").trim(),
      teacherName = String(cell.teacher_name || "").trim(),
      className = String(cell.class_name || "").trim() || `Lớp ${classId}`;
    if (scheduleAuditIsUnknownSubject(subjectName)) {
      addInferredIssue(
        "unknown_subject",
        "Chưa xác định được môn học",
        `${className} tại ${scheduleAuditSlotLabelForEdit(slot, viewer)} chưa có tên môn rõ ràng.`,
        cell,
        className,
      );
    }
    if (
      scheduleAuditIsUnknownTeacher(teacherName) &&
      !scheduleAuditTeacherIsOptional(subjectName)
    ) {
      addInferredIssue(
        "unknown_teacher",
        "Chưa xác định được giáo viên",
        `${className} · ${subjectName} chưa có tên giáo viên rõ ràng.`,
        cell,
        className,
      );
    }
    if (teacherName && !scheduleAuditIsUnknownTeacher(teacherName)) {
      const key = `${slot}:${scheduleAuditIdentityKey(teacherName)}`;
      if (!teacherGroups.has(key)) teacherGroups.set(key, []);
      teacherGroups.get(key).push(cell);
    }
    const room = String(cell.room || "").trim();
    if (room) {
      const key = `${slot}:${scheduleAuditEntityKey(room)}`;
      if (!roomGroups.has(key)) roomGroups.set(key, []);
      roomGroups.get(key).push(cell);
    }
  }
  for (const rows of classGroups.values())
    if (rows.length > 1) {
      const name = rows[0].class_name || `Lớp ${rows[0].class_id}`;
      addConflict(
        "class_collision",
        "Trùng lịch lớp",
        `Lớp ${name} có ${rows.length} tiết cùng lúc.`,
        rows,
        name,
      );
    }
  for (const rows of teacherGroups.values())
    if (rows.length > 1) {
      const teacher = rows[0].teacher_name,
        classNames = [
          ...new Set(
            rows.map((row) => row.class_name || `Lớp ${row.class_id}`),
          ),
        ];
      addConflict(
        "teacher_collision",
        "Trùng lịch giáo viên",
        `Giáo viên ${teacher} bị xếp đồng thời: ${classNames.join(", ")}.`,
        rows,
        teacher,
      );
    }
  for (const rows of roomGroups.values()) {
    const classIds = new Set(rows.map((row) => Number(row.class_id)));
    if (classIds.size <= 1) continue;
    const room = rows[0].room,
      classNames = [
        ...new Set(rows.map((row) => row.class_name || `Lớp ${row.class_id}`)),
      ];
    addConflict(
      "room_collision",
      "Trùng phòng học",
      `Phòng ${room} đang được dùng đồng thời cho: ${classNames.join(", ")}.`,
      rows,
      room,
    );
  }
  const cleanInferredIssues = inferredIssues.map(({ _key, ...issue }) => issue);
  report.issues = [
    ...collisionIssues,
    ...cleanInferredIssues,
    ...retainedIssues,
  ];
  viewer.conflict_cells = affected.size;
  report.statistics = scheduleAuditBuildStatistics(viewer);
  const summary = report.summary || (report.summary = {}),
    stats = report.statistics.overview;
  summary.collisions = collisionIssues.length;
  summary.errors = report.issues.filter(
    (issue) => issue.severity === "error",
  ).length;
  summary.warnings = report.issues.filter(
    (issue) => issue.severity === "warning",
  ).length;
  summary.teachers = stats.total_teachers;
  summary.subjects = stats.total_subjects;
  summary.classes = stats.total_classes;
  summary.recognized_lessons = cells.length;
  report.status = summary.errors
    ? "error"
    : summary.warnings
      ? "warning"
      : "clean";
}
function setScheduleAuditBulkTeacherRename(enabled) {
  scheduleAuditBulkTeacherRename = Boolean(enabled);
}
function applyScheduleAuditCellRename(field, draftId, newName) {
  const report = scheduleAuditLastReport,
    newValue = String(newName || "").trim();
  if (!report?.viewer || !newValue || !Number.isFinite(Number(draftId)))
    return false;
  const cells = report.viewer.cells || [];
  const cell = cells.find((item) => Number(item.draft_id) === Number(draftId));
  if (!cell) return false;
  const parts = scheduleAuditDisplayLessonParts(cell),
    current = field === "subject_name" ? parts.subject : parts.teacher;
  if (String(current || "").trim() === newValue) return false;
  const currentKey = scheduleAuditIdentityKey(current);
  if (!currentKey) return false;
  const renameMatchingNames =
    field === "subject_name" || scheduleAuditBulkTeacherRename;
  let changed = 0;
  for (const item of cells) {
    if (!renameMatchingNames && Number(item.draft_id) !== Number(draftId))
      continue;
    const itemParts = scheduleAuditDisplayLessonParts(item);
    const itemCurrent =
      field === "subject_name" ? itemParts.subject : itemParts.teacher;
    if (
      renameMatchingNames &&
      scheduleAuditIdentityKey(itemCurrent) !== currentKey
    )
      continue;
    if (field === "subject_name") {
      item.subject_name = newValue;
      item.raw_text = [newValue, itemParts.teacher].filter(Boolean).join(" - ");
    } else {
      item.teacher_name = newValue;
      item.raw_text = [itemParts.subject, newValue].filter(Boolean).join(" - ");
    }
    changed += 1;
  }
  if (!changed) return false;
  scheduleAuditRebuildDataFromViewer(report);
  scheduleAuditManualEdits += 1;
  scheduleAuditRecalculateAfterEdit(report);
  resetScheduleAuditAiResult();
  renderScheduleAudit(report, null);
  return true;
}
function beginScheduleAuditInlineEdit(element, event) {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  if (!element || element.dataset.editing === "1" || !scheduleAuditLastReport)
    return;
  const draftId = Number(element.dataset.draftId),
    field = element.dataset.field;
  if (
    !Number.isFinite(draftId) ||
    !["subject_name", "teacher_name"].includes(field)
  )
    return;
  const cell = (scheduleAuditLastReport.viewer?.cells || []).find(
    (item) => Number(item.draft_id) === draftId,
  );
  if (!cell) return;
  const parts = scheduleAuditDisplayLessonParts(cell),
    current = field === "subject_name" ? parts.subject : parts.teacher;
  const input = document.createElement("input");
  input.type = "text";
  input.className = "schedule-view-inline-input";
  input.value = current;
  input.setAttribute(
    "aria-label",
    field === "subject_name" ? "Sửa tên môn" : "Sửa tên giáo viên",
  );
  element.dataset.editing = "1";
  element.replaceChildren(input);
  let finished = false;
  const cancel = () => {
    if (finished) return;
    finished = true;
    renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis);
  };
  const commit = () => {
    if (finished) return;
    finished = true;
    const next = input.value.trim();
    if (!next) {
      renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis);
      return;
    }
    if (!applyScheduleAuditCellRename(field, draftId, next))
      renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis);
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
    e.stopPropagation();
  });
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("blur", commit, { once: true });
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}
