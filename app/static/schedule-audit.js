'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const operationHeaders = extra => ({ 'X-Skip-Operation-Status': '1', ...(extra || {}) });

let scheduleAuditSelectedFile = null;
let scheduleAuditRunId = 0;
let scheduleAuditAiRunId = 0;
let scheduleAuditLastReport = null;
let scheduleAuditAiAnalysis = null;
let scheduleAuditAiModel = '';
let scheduleAuditActiveView = 'timetable';
let scheduleAuditManualEdits = 0;
let scheduleAuditBulkTeacherRename = false;
const SCHEDULE_AUDIT_MAX_BYTES = 15 * 1024 * 1024;
const SCHEDULE_AUDIT_ALLOWED_EXTENSIONS = ['xlsx', 'xlsm', 'xls', 'docx', 'csv', 'tsv'];

function scheduleAuditAiIsEnabled() { return $('#scheduleAuditAiButton')?.dataset?.enabled === '1'; }
function scheduleAuditFileValidationError(file) {
  if (!file) return 'Hãy chọn file thời khóa biểu trước khi kiểm tra.';
  if (file.size > SCHEDULE_AUDIT_MAX_BYTES) return 'File vượt quá giới hạn 15 MB.';
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (!SCHEDULE_AUDIT_ALLOWED_EXTENSIONS.includes(ext)) return 'Định dạng chưa hỗ trợ. Dùng .xlsx, .xlsm, .xls, .docx, .csv hoặc .tsv.';
  return '';
}
function setScheduleAuditFile(file) {
  scheduleAuditSelectedFile = file || null;
  const name = $('#scheduleAuditFileName'), drop = $('#scheduleAuditDropzone'), actions = $('#scheduleAuditFileActions'), button = $('#scheduleAuditButton'), aiButton = $('#scheduleAuditAiButton');
  if (name) name.textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(file.size >= 1024 * 1024 ? 2 : 3)} MB` : 'Chưa chọn file';
  if (drop) { drop.classList.toggle('has-file', !!file); drop.setAttribute('aria-label', file ? `${file.name} đã sẵn sàng. Bấm để chọn file khác.` : 'Kéo thả file thời khóa biểu vào đây hoặc bấm để chọn file.'); }
  if (actions) actions.hidden = !file;
  if (button && !button.disabled) button.textContent = file ? 'Kiểm tra lại' : 'Kiểm tra thời khóa biểu';
  if (aiButton && !aiButton.classList.contains('is-loading')) {
    aiButton.disabled = !scheduleAuditAiIsEnabled();
    aiButton.textContent = '✦ Phân tích bằng AI';
  }
}
function resetScheduleAuditAiResult() {
  scheduleAuditAiAnalysis = null; scheduleAuditAiModel = '';
  const aiBox = $('#scheduleAuditAiResult');
  if (aiBox) { aiBox.hidden = true; aiBox.innerHTML = ''; }
}
function clearScheduleAuditFile(resetResult = true) {
  scheduleAuditRunId += 1; scheduleAuditAiRunId += 1; scheduleAuditLastReport = null; scheduleAuditManualEdits = 0; resetScheduleAuditAiResult();
  const input = $('#scheduleAuditFile'), box = $('#scheduleAuditResult'), button = $('#scheduleAuditButton'), aiButton = $('#scheduleAuditAiButton'), drop = $('#scheduleAuditDropzone');
  if (input) input.value = '';
  setScheduleAuditFile(null);
  if (button) { button.disabled = false; button.textContent = 'Kiểm tra thời khóa biểu'; }
  if (aiButton) { aiButton.classList.remove('is-loading'); aiButton.disabled = !scheduleAuditAiIsEnabled(); aiButton.textContent = '✦ Phân tích bằng AI'; }
  if (drop) drop.classList.remove('is-analyzing', 'is-dragging');
  if (resetResult && box) box.innerHTML = '<div class="empty-state">Chọn một file thời khóa biểu để hiển thị và kiểm tra.</div>';
}
function selectScheduleAuditFile(file, { autoRun = true } = {}) {
  const error = scheduleAuditFileValidationError(file);
  if (error) { clearScheduleAuditFile(false); renderScheduleAuditError(error); return false; }
  scheduleAuditAiRunId += 1; scheduleAuditLastReport = null; scheduleAuditManualEdits = 0; scheduleAuditActiveView = 'timetable'; resetScheduleAuditAiResult();
  setScheduleAuditFile(file);
  if (autoRun) runScheduleAudit();
  return true;
}
function scheduleAuditConflictLabel(code) {
  return ({ teacher_collision: 'Trùng giáo viên', class_collision: 'Trùng lớp', room_collision: 'Trùng phòng' })[code] || 'Xung đột';
}
function scheduleAuditAiSeverityLabel(severity) { return severity === 'warning' ? 'AI cảnh báo' : 'AI gợi ý'; }
function scheduleAuditAiCategoryLabel(category) {
  return ({ distribution: 'Phân bố lịch', teacher_load: 'Tải giáo viên', consecutive: 'Tiết liên tiếp', parser_suspicion: 'Cần kiểm tra cách đọc ô', other: 'Khác' })[category] || 'Khác';
}
function scheduleAuditSlotParts(slot, viewer) {
  const periods = Number(viewer.periods || 1), sessions = Number(viewer.sessions || 1), perDay = periods * sessions;
  const day = Math.floor(Number(slot) / perDay), inside = Number(slot) % perDay, session = Math.floor(inside / periods), period = (inside % periods) + 1;
  return { day, session, period };
}
function scheduleAuditDayName(day) { return ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'CN'][day] || `Ngày ${day + 1}`; }
function scheduleAuditSessionName(session, sessions) { if (Number(sessions) <= 1) return ''; return session === 0 ? 'Sáng' : session === 1 ? 'Chiều' : `Buổi ${session + 1}`; }
function scheduleAuditAiMap(ai) {
  const map = new Map();
  for (const issue of ai?.issues || []) {
    for (const key of issue.cell_keys || []) { if (!map.has(key)) map.set(key, []); map.get(key).push(issue); }
  }
  return map;
}
function scheduleAuditEntityKey(value) {
  return String(value ?? '').trim().toLocaleLowerCase('vi-VN').replace(/đ/g, 'd').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
}
function scheduleAuditIdentityKey(value) {
  return String(value ?? '').normalize('NFC').trim().toLocaleLowerCase('vi-VN').replace(/[^\p{L}\p{N}]+/gu, ' ').replace(/\s+/g, ' ').trim();
}
function scheduleAuditIsUnknownSubject(value) { return scheduleAuditEntityKey(value).startsWith('mon chua xac dinh'); }
function scheduleAuditIsUnknownTeacher(value) { return scheduleAuditEntityKey(value).startsWith('gv chua xac dinh'); }
function scheduleAuditTeacherIsOptional(subjectName) {
  return new Set(['chao co', 'sinh hoat', 'trai nghiem', 'hdtn', 'hdtnhn', 'tnhn']).has(scheduleAuditEntityKey(subjectName));
}
function scheduleAuditShortName(value, fallback = '') {
  const words = String(value || '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return String(fallback || '').slice(0, 20);
  if (words.length === 1) return words[0].slice(0, 20).toUpperCase();
  return words.map(word => word[0] || '').join('').slice(0, 20).toUpperCase() || String(fallback || '').slice(0, 20);
}
function scheduleAuditRebuildDataFromViewer(report) {
  if (!report?.viewer) return;
  const viewer = report.viewer, cells = Array.isArray(viewer.cells) ? viewer.cells : [];
  const data = report.data || (report.data = {});
  const existingSubjects = Array.isArray(data.subjects) ? data.subjects : [];
  const existingTeachers = Array.isArray(data.teachers) ? data.teachers : [];
  const existingSubjectByKey = new Map(existingSubjects.map(row => [scheduleAuditIdentityKey(row?.name), row]).filter(([key]) => key));
  const existingTeacherByKey = new Map(existingTeachers.map(row => [scheduleAuditIdentityKey(row?.name), row]).filter(([key]) => key));
  const usedSubjectIds = new Set(), usedTeacherIds = new Set();
  let nextSubjectId = Math.max(0, ...existingSubjects.map(row => Number(row?.id) || 0)) + 1;
  let nextTeacherId = Math.max(0, ...existingTeachers.map(row => Number(row?.id) || 0)) + 1;
  const subjectsByKey = new Map(), teachersByKey = new Map();

  const reserveId = (preferred, used, nextRef) => {
    const parsed = Number(preferred);
    if (Number.isInteger(parsed) && parsed > 0 && !used.has(parsed)) { used.add(parsed); return [parsed, nextRef]; }
    while (used.has(nextRef)) nextRef += 1;
    used.add(nextRef);
    return [nextRef, nextRef + 1];
  };
  const getSubject = name => {
    const clean = String(name || '').trim(), key = scheduleAuditIdentityKey(clean);
    if (subjectsByKey.has(key)) return subjectsByKey.get(key);
    const previous = existingSubjectByKey.get(key) || {};
    let id;[id, nextSubjectId] = reserveId(previous.id, usedSubjectIds, nextSubjectId);
    const row = { ...previous, id, name: clean, short_name: previous.short_name || scheduleAuditShortName(clean, `M${id}`), is_placeholder: scheduleAuditIsUnknownSubject(clean) };
    subjectsByKey.set(key, row); return row;
  };
  const getTeacher = name => {
    const clean = String(name || '').trim(), key = scheduleAuditIdentityKey(clean);
    if (teachersByKey.has(key)) return teachersByKey.get(key);
    const previous = existingTeacherByKey.get(key) || {};
    let id;[id, nextTeacherId] = reserveId(previous.id, usedTeacherIds, nextTeacherId);
    const row = { ...previous, id, name: clean, short_name: previous.short_name || scheduleAuditShortName(clean, `GV${id}`), is_placeholder: scheduleAuditIsUnknownTeacher(clean), subject_ids: [] };
    teachersByKey.set(key, row); return row;
  };

  const assignmentsByKey = new Map(), lessons = [];
  let nextAssignmentId = 1;
  for (const cell of cells) {
    const classId = Number(cell.class_id), subject = getSubject(cell.subject_name), teacher = getTeacher(cell.teacher_name);
    const key = `${classId}:${subject.id}:${teacher.id}`;
    let assignment = assignmentsByKey.get(key);
    if (!assignment) {
      assignment = {
        id: nextAssignmentId++, class_id: classId, subject_id: subject.id, teacher_id: teacher.id,
        periods_per_week: 0, block_mode: 'free', class_name: String(cell.class_name || '').trim(),
        subject_name: subject.name, subject_short: subject.short_name, teacher_name: teacher.name, teacher_short: teacher.short_name,
      };
      assignmentsByKey.set(key, assignment);
    }
    assignment.periods_per_week += 1;
    if (!teacher.subject_ids.includes(subject.id)) teacher.subject_ids.push(subject.id);
    lessons.push({
      id: Number(cell.draft_id) || lessons.length + 1,
      assignment_id: assignment.id,
      slot: Number(cell.slot),
      locked: Boolean(cell.locked),
    });
  }

  data.subjects = [...subjectsByKey.values()];
  data.teachers = [...teachersByKey.values()];
  data.assignments = [...assignmentsByKey.values()];
  data.lessons = lessons;
  if (report.detection) {
    report.detection.teachers = data.teachers.filter(row => !row.is_placeholder).map(row => row.name);
    report.detection.classes = (viewer.classes || []).map(row => row.name);
  }
}
function scheduleAuditDisplayLessonParts(item) {
  const raw = String(item.raw_text || '').trim();
  const teacher = String(item.teacher_name || '').trim().replace(/^[.\-–—:;,\s]+/, '');
  let subject = String(item.subject_name || '').trim();

  if (raw && teacher) {
    const escapedTeacher = teacher.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
    const parsedSubject = raw.replace(new RegExp(`[.\\-–—:;,\\s]*${escapedTeacher}\\s*$`, 'i'), '').trim().replace(/[.\-–—:;,\s]+$/, '').trim();
    if (parsedSubject) subject = parsedSubject;
  }
  return { subject, teacher, raw };
}
function scheduleAuditDisplayLesson(item) {
  const parts = scheduleAuditDisplayLessonParts(item);
  return [parts.subject, parts.teacher].filter(Boolean).join(' - ') || parts.raw;
}
function scheduleAuditEditableLessonHtml(item) {
  const parts = scheduleAuditDisplayLessonParts(item), draftId = Number(item.draft_id);
  const subject = parts.subject || String(item.subject_name || '').trim();
  const teacher = parts.teacher || String(item.teacher_name || '').trim();
  const pieces = [];
  if (subject) {
    pieces.push(`<span class="schedule-view-editable schedule-view-editable-subject" role="button" tabindex="0" data-draft-id="${draftId}" data-field="subject_name" title="Bấm để sửa tên môn" onclick="beginScheduleAuditInlineEdit(this,event)" onkeydown="handleScheduleAuditEditableKey(event,this)">${esc(subject)}</span>`);
  }
  if (subject && teacher) pieces.push('<span class="schedule-view-name-separator" aria-hidden="true"> - </span>');
  if (teacher) {
    pieces.push(`<span class="schedule-view-editable schedule-view-editable-teacher" role="button" tabindex="0" data-draft-id="${draftId}" data-field="teacher_name" title="Bấm để sửa tên giáo viên" onclick="beginScheduleAuditInlineEdit(this,event)" onkeydown="handleScheduleAuditEditableKey(event,this)">${esc(teacher)}</span>`);
  }
  return pieces.join('') || esc(parts.raw);
}
function scheduleAuditCellHtml(entries, aiIssues = []) {
  if (!entries?.length) return '<td class="schedule-view-cell empty"></td>';
  const hasConflict = entries.some(item => (item.conflicts || []).length);
  const hasAiWarning = aiIssues.some(item => item.severity === 'warning');
  const hasAiSuggestion = aiIssues.length > 0 && !hasAiWarning;
  const conflictCodes = [...new Set(entries.flatMap(item => item.conflicts || []))];
  const details = [...new Set(entries.flatMap(item => item.conflict_details || []))];
  const aiDetails = aiIssues.map(item => `AI: ${item.title}${item.message ? ` — ${item.message}` : ''}`);
  const title = [...details, ...aiDetails, ...entries.map(item => item.source).filter(Boolean)].join('\n');
  const stateClass = hasConflict ? ' conflict' : hasAiWarning ? ' ai-warning' : hasAiSuggestion ? ' ai-suggestion' : '';
  return `<td class="schedule-view-cell${stateClass}"${title ? ` title="${esc(title)}"` : ''}>${entries.map(item => `<div class="schedule-view-lesson"><b class="schedule-view-lesson-line">${scheduleAuditEditableLessonHtml(item)}</b>${item.room ? `<small>Phòng ${esc(item.room)}</small>` : ''}</div>`).join('')}${hasConflict ? `<div class="schedule-view-conflict-tags">${conflictCodes.map(code => `<span>! ${esc(scheduleAuditConflictLabel(code))}</span>`).join('')}</div>` : ''}${aiIssues.length ? `<div class="schedule-view-ai-tags"><span class="${hasAiWarning ? 'warning' : 'suggestion'}">✦ ${esc(scheduleAuditAiSeverityLabel(hasAiWarning ? 'warning' : 'suggestion'))}</span></div>` : ''}</td>`;
}
function handleScheduleAuditEditableKey(event, element) {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); beginScheduleAuditInlineEdit(element, event); }
}
function scheduleAuditSlotLabelForEdit(slot, viewer) {
  const part = scheduleAuditSlotParts(slot, viewer), session = scheduleAuditSessionName(part.session, viewer.sessions);
  return [scheduleAuditDayName(part.day), session, `tiết ${part.period}`].filter(Boolean).join(', ');
}
function scheduleAuditBuildStatistics(viewer) {
  const cells = viewer?.cells || [], teacherMap = new Map(), subjectMap = new Map(), classMap = new Map();
  const bump = (map, name) => map.set(name, (map.get(name) || 0) + 1);
  const getEntity = (map, key, name, id) => {
    if (!map.has(key)) map.set(key, { id, name, total_lessons: 0, subjects: new Map(), teachers: new Map(), classes: new Map() });
    return map.get(key);
  };
  for (const cell of cells) {
    const className = String(cell.class_name || '').trim(), subjectName = String(cell.subject_name || '').trim(), teacherName = String(cell.teacher_name || '').trim();
    const knownSubject = subjectName && !scheduleAuditIsUnknownSubject(subjectName), knownTeacher = teacherName && !scheduleAuditIsUnknownTeacher(teacherName);
    if (knownTeacher) {
      const row = getEntity(teacherMap, scheduleAuditIdentityKey(teacherName), teacherName, teacherMap.size + 1); row.total_lessons += 1;
      if (knownSubject) bump(row.subjects, subjectName); if (className) bump(row.classes, className);
    }
    if (knownSubject) {
      const row = getEntity(subjectMap, scheduleAuditIdentityKey(subjectName), subjectName, subjectMap.size + 1); row.total_lessons += 1;
      if (knownTeacher) bump(row.teachers, teacherName); if (className) bump(row.classes, className);
    }
    const classKey = String(cell.class_id ?? className);
    const row = getEntity(classMap, classKey, className || `Lớp ${cell.class_id}`, Number(cell.class_id) || classMap.size + 1); row.total_lessons += 1;
    if (knownSubject) bump(row.subjects, subjectName); if (knownTeacher) bump(row.teachers, teacherName);
  }
  const breakdown = map => [...map.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'vi')).map(([name, lessons]) => ({ name, lessons }));
  const finalize = (map, fields) => [...map.values()].map(row => {
    const out = { id: row.id, name: row.name, total_lessons: row.total_lessons }; for (const field of fields) out[field] = breakdown(row[field]); return out;
  }).sort((a, b) => b.total_lessons - a.total_lessons || a.name.localeCompare(b.name, 'vi'));
  const teachers = finalize(teacherMap, ['subjects', 'classes']), subjects = finalize(subjectMap, ['teachers', 'classes']), classes = finalize(classMap, ['subjects', 'teachers']);
  const leader = rows => rows.length ? { name: rows[0].name, lessons: Number(rows[0].total_lessons || 0) } : null;
  const totalLessons = cells.length, knownTeacherLessons = teachers.reduce((sum, row) => sum + Number(row.total_lessons || 0), 0);
  return { overview: { total_lessons: totalLessons, total_teachers: teachers.length, total_subjects: subjects.length, total_classes: classes.length, avg_lessons_per_teacher: teachers.length ? Math.round((knownTeacherLessons / teachers.length) * 100) / 100 : 0, avg_lessons_per_class: classes.length ? Math.round((totalLessons / classes.length) * 100) / 100 : 0, busiest_teacher: leader(teachers), largest_subject: leader(subjects), busiest_class: leader(classes) }, teachers, subjects, classes };
}
function scheduleAuditRecalculateAfterEdit(report) {
  if (!report?.viewer) return;
  const viewer = report.viewer, cells = viewer.cells || [];
  const dynamicCodes = new Set(['teacher_collision', 'class_collision', 'room_collision', 'unknown_subject', 'unknown_teacher']);
  const retainedIssues = (report.issues || []).filter(issue => !dynamicCodes.has(issue.code));
  for (const cell of cells) { cell.conflicts = []; cell.conflict_details = []; }
  const collisionIssues = [], inferredIssues = [], affected = new Set();
  const addConflict = (code, title, detail, rows, entity) => {
    const slot = Number(rows[0]?.slot || 0);
    for (const row of rows) {
      if (!row.conflicts.includes(code)) row.conflicts.push(code);
      if (!row.conflict_details.includes(detail)) row.conflict_details.push(detail);
      affected.add(`${Number(row.slot)}:${Number(row.class_id)}`);
    }
    collisionIssues.push({ code, severity: 'error', title, detail, slot, slot_label: scheduleAuditSlotLabelForEdit(slot, viewer), entity: entity || '', source: [...new Set(rows.map(row => row.source).filter(Boolean))].join('; ') });
  };
  const addInferredIssue = (code, title, detail, cell, entity) => {
    const key = `${code}:${Number(cell.slot)}:${Number(cell.class_id)}:${scheduleAuditEntityKey(entity)}`;
    if (inferredIssues.some(issue => issue._key === key)) return;
    inferredIssues.push({ _key: key, code, severity: 'warning', title, detail, slot: Number(cell.slot), slot_label: scheduleAuditSlotLabelForEdit(Number(cell.slot), viewer), entity: entity || '', source: cell.source || '' });
  };
  const classGroups = new Map(), teacherGroups = new Map(), roomGroups = new Map();
  for (const cell of cells) {
    const slot = Number(cell.slot), classId = Number(cell.class_id), classKey = `${slot}:${classId}`;
    if (!classGroups.has(classKey)) classGroups.set(classKey, []); classGroups.get(classKey).push(cell);
    const subjectName = String(cell.subject_name || '').trim(), teacherName = String(cell.teacher_name || '').trim(), className = String(cell.class_name || '').trim() || `Lớp ${classId}`;
    if (scheduleAuditIsUnknownSubject(subjectName)) {
      addInferredIssue('unknown_subject', 'Chưa xác định được môn học', `${className} tại ${scheduleAuditSlotLabelForEdit(slot, viewer)} chưa có tên môn rõ ràng.`, cell, className);
    }
    if (scheduleAuditIsUnknownTeacher(teacherName) && !scheduleAuditTeacherIsOptional(subjectName)) {
      addInferredIssue('unknown_teacher', 'Chưa xác định được giáo viên', `${className} · ${subjectName} chưa có tên giáo viên rõ ràng.`, cell, className);
    }
    if (teacherName && !scheduleAuditIsUnknownTeacher(teacherName)) { const key = `${slot}:${scheduleAuditIdentityKey(teacherName)}`; if (!teacherGroups.has(key)) teacherGroups.set(key, []); teacherGroups.get(key).push(cell); }
    const room = String(cell.room || '').trim(); if (room) { const key = `${slot}:${scheduleAuditEntityKey(room)}`; if (!roomGroups.has(key)) roomGroups.set(key, []); roomGroups.get(key).push(cell); }
  }
  for (const rows of classGroups.values()) if (rows.length > 1) { const name = rows[0].class_name || `Lớp ${rows[0].class_id}`; addConflict('class_collision', 'Trùng lịch lớp', `Lớp ${name} có ${rows.length} tiết cùng lúc.`, rows, name); }
  for (const rows of teacherGroups.values()) if (rows.length > 1) { const teacher = rows[0].teacher_name, classNames = [...new Set(rows.map(row => row.class_name || `Lớp ${row.class_id}`))]; addConflict('teacher_collision', 'Trùng lịch giáo viên', `Giáo viên ${teacher} bị xếp đồng thời: ${classNames.join(', ')}.`, rows, teacher); }
  for (const rows of roomGroups.values()) {
    const classIds = new Set(rows.map(row => Number(row.class_id))); if (classIds.size <= 1) continue;
    const room = rows[0].room, classNames = [...new Set(rows.map(row => row.class_name || `Lớp ${row.class_id}`))]; addConflict('room_collision', 'Trùng phòng học', `Phòng ${room} đang được dùng đồng thời cho: ${classNames.join(', ')}.`, rows, room);
  }
  const cleanInferredIssues = inferredIssues.map(({ _key, ...issue }) => issue);
  report.issues = [...collisionIssues, ...cleanInferredIssues, ...retainedIssues];
  viewer.conflict_cells = affected.size;
  report.statistics = scheduleAuditBuildStatistics(viewer);
  const summary = report.summary || (report.summary = {}), stats = report.statistics.overview;
  summary.collisions = collisionIssues.length;
  summary.errors = report.issues.filter(issue => issue.severity === 'error').length;
  summary.warnings = report.issues.filter(issue => issue.severity === 'warning').length;
  summary.teachers = stats.total_teachers; summary.subjects = stats.total_subjects; summary.classes = stats.total_classes; summary.recognized_lessons = cells.length;
  report.status = summary.errors ? 'error' : summary.warnings ? 'warning' : 'clean';
}
function setScheduleAuditBulkTeacherRename(enabled) {
  scheduleAuditBulkTeacherRename = Boolean(enabled);
}
function applyScheduleAuditCellRename(field, draftId, newName) {
  const report = scheduleAuditLastReport, newValue = String(newName || '').trim();
  if (!report?.viewer || !newValue || !Number.isFinite(Number(draftId))) return false;
  const cells = report.viewer.cells || [];
  const cell = cells.find(item => Number(item.draft_id) === Number(draftId));
  if (!cell) return false;
  const parts = scheduleAuditDisplayLessonParts(cell), current = field === 'subject_name' ? parts.subject : parts.teacher;
  if (String(current || '').trim() === newValue) return false;
  const currentKey = scheduleAuditIdentityKey(current);
  if (!currentKey) return false;
  const renameMatchingNames = field === 'subject_name' || scheduleAuditBulkTeacherRename;
  let changed = 0;
  for (const item of cells) {
    if (!renameMatchingNames && Number(item.draft_id) !== Number(draftId)) continue;
    const itemParts = scheduleAuditDisplayLessonParts(item);
    const itemCurrent = field === 'subject_name' ? itemParts.subject : itemParts.teacher;
    if (renameMatchingNames && scheduleAuditIdentityKey(itemCurrent) !== currentKey) continue;
    if (field === 'subject_name') {
      item.subject_name = newValue;
      item.raw_text = [newValue, itemParts.teacher].filter(Boolean).join(' - ');
    } else {
      item.teacher_name = newValue;
      item.raw_text = [itemParts.subject, newValue].filter(Boolean).join(' - ');
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
  event?.preventDefault?.(); event?.stopPropagation?.();
  if (!element || element.dataset.editing === '1' || !scheduleAuditLastReport) return;
  const draftId = Number(element.dataset.draftId), field = element.dataset.field;
  if (!Number.isFinite(draftId) || !['subject_name', 'teacher_name'].includes(field)) return;
  const cell = (scheduleAuditLastReport.viewer?.cells || []).find(item => Number(item.draft_id) === draftId); if (!cell) return;
  const parts = scheduleAuditDisplayLessonParts(cell), current = field === 'subject_name' ? parts.subject : parts.teacher;
  const input = document.createElement('input'); input.type = 'text'; input.className = 'schedule-view-inline-input'; input.value = current; input.setAttribute('aria-label', field === 'subject_name' ? 'Sửa tên môn' : 'Sửa tên giáo viên');
  element.dataset.editing = '1'; element.replaceChildren(input);
  let finished = false;
  const cancel = () => { if (finished) return; finished = true; renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis); };
  const commit = () => { if (finished) return; finished = true; const next = input.value.trim(); if (!next) { renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis); return; } if (!applyScheduleAuditCellRename(field, draftId, next)) renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis); };
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); commit(); } else if (e.key === 'Escape') { e.preventDefault(); cancel(); } e.stopPropagation(); });
  input.addEventListener('click', e => e.stopPropagation()); input.addEventListener('blur', commit, { once: true });
  requestAnimationFrame(() => { input.focus(); input.select(); });
}
function renderScheduleAuditTable(report, ai = null) {
  const viewer = report.viewer || {}, classes = viewer.classes || [], cells = viewer.cells || [];
  if (!classes.length || !cells.length) return '<div class="empty-state">Không có đủ dữ liệu để dựng bảng thời khóa biểu.</div>';
  const byCoordinate = new Map(), aiMap = scheduleAuditAiMap(ai);
  cells.forEach(item => { const key = `${Number(item.slot)}:${Number(item.class_id)}`; if (!byCoordinate.has(key)) byCoordinate.set(key, []); byCoordinate.get(key).push(item); });
  const totalSlots = Math.max(0, Number(viewer.days || 0) * Number(viewer.sessions || 0) * Number(viewer.periods || 0));
  const slots = totalSlots ? Array.from({ length: totalSlots }, (_, index) => index) : [...new Set(cells.map(item => Number(item.slot)))].sort((a, b) => a - b);
  let previousDay = -1, previousSession = -1;
  let rows = '';
  for (const slot of slots) {
    const part = scheduleAuditSlotParts(slot, viewer), newDay = part.day !== previousDay, newSession = newDay || part.session !== previousSession;
    rows += `<tr class="${newDay ? 'schedule-view-new-day ' : ''}${newSession ? 'schedule-view-new-session' : ''}">`;
    rows += `<th class="schedule-view-meta day">${newDay ? esc(scheduleAuditDayName(part.day)) : ''}</th>`;
    rows += `<th class="schedule-view-meta session">${newSession ? esc(scheduleAuditSessionName(part.session, viewer.sessions)) : ''}</th>`;
    rows += `<th class="schedule-view-meta period">${part.period}</th>`;
    for (const cls of classes) { const key = `${slot}:${Number(cls.id)}`; rows += scheduleAuditCellHtml(byCoordinate.get(key) || [], aiMap.get(key) || []); }
    rows += '</tr>'; previousDay = part.day; previousSession = part.session;
  }
  const bulkTeacherChecked = scheduleAuditBulkTeacherRename ? ' checked' : '';
  return `<div class="schedule-view-edit-hint"><span class="schedule-view-edit-icon">✎</span><div class="schedule-view-edit-copy"><b>Có thể sửa trực tiếp</b><small>Bấm vào <strong>tên môn</strong> hoặc <strong>tên giáo viên</strong> trong từng ô. Nhấn Enter hoặc bấm ra ngoài để lưu, Esc để hủy. Tên môn trùng vẫn đổi đồng bộ; tên giáo viên chỉ đổi hàng loạt khi bật công tắc.</small></div><label class="schedule-view-bulk-toggle" title="Bật để đổi tất cả giáo viên có cùng tên"><input type="checkbox"${bulkTeacherChecked} onchange="setScheduleAuditBulkTeacherRename(this.checked)"><span class="schedule-view-switch" aria-hidden="true"><i></i></span><span class="schedule-view-bulk-toggle-text">Đổi hàng loạt tên GV trùng</span></label></div><div class="schedule-view-table-wrap"><table class="schedule-view-table"><thead><tr><th class="schedule-view-meta day">Thứ</th><th class="schedule-view-meta session">Buổi</th><th class="schedule-view-meta period">Tiết</th>${classes.map(cls => `<th class="schedule-view-class">${esc(cls.name)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function scheduleAuditBreakdownHtml(items, emptyLabel = 'Không có dữ liệu') {
  if (!items?.length) return `<span class="schedule-stat-empty">${esc(emptyLabel)}</span>`;
  return `<div class="schedule-stat-breakdown">${items.map(item => `<span>${esc(item.name)} <b>${Number(item.lessons || 0)}</b></span>`).join('')}</div>`;
}
function scheduleAuditStatsOverview(statistics) {
  const overview = statistics?.overview || {};
  const leader = (item, fallback = '—') => item?.name ? `<b>${esc(item.name)}</b><span>${Number(item.lessons || 0)} tiết</span>` : `<b>${fallback}</b><span>Chưa có dữ liệu</span>`;
  return `
    <div class="schedule-stat-cards">
      <article><span>Tổng số tiết</span><b>${Number(overview.total_lessons || 0)}</b></article>
      <article><span>Giáo viên</span><b>${Number(overview.total_teachers || 0)}</b></article>
      <article><span>Môn học</span><b>${Number(overview.total_subjects || 0)}</b></article>
      <article><span>Lớp học</span><b>${Number(overview.total_classes || 0)}</b></article>
    </div>
    <div class="schedule-stat-highlights">
      <article><small>Giáo viên dạy nhiều nhất</small>${leader(overview.busiest_teacher)}</article>
      <article><small>Môn có nhiều tiết nhất</small>${leader(overview.largest_subject)}</article>
      <article><small>Lớp có nhiều tiết nhất</small>${leader(overview.busiest_class)}</article>
      <article><small>Trung bình / giáo viên</small><b>${Number(overview.avg_lessons_per_teacher || 0).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tiết</b><span>TB / lớp: ${Number(overview.avg_lessons_per_class || 0).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tiết</span></article>
    </div>`;
}
function scheduleAuditStatsTable(rows, type) {
  const config = {
    teachers: { title: 'Giáo viên', first: 'Môn giảng dạy', second: 'Lớp phụ trách', firstKey: 'subjects', secondKey: 'classes', search: 'Tìm giáo viên…' },
    subjects: { title: 'Môn học', first: 'Giáo viên', second: 'Lớp học', firstKey: 'teachers', secondKey: 'classes', search: 'Tìm môn học…' },
    classes: { title: 'Lớp học', first: 'Môn học', second: 'Giáo viên', firstKey: 'subjects', secondKey: 'teachers', search: 'Tìm lớp học…' },
  }[type];
  if (!config) return '';
  const body = (rows || []).map(item => `<tr data-stat-text="${esc(String(item.name || '').toLocaleLowerCase('vi-VN'))}"><td><b>${esc(item.name || '—')}</b></td><td class="schedule-stat-total">${Number(item.total_lessons || 0)}</td><td>${scheduleAuditBreakdownHtml(item[config.firstKey])}</td><td>${scheduleAuditBreakdownHtml(item[config.secondKey])}</td></tr>`).join('');
  return `<div class="schedule-stat-toolbar"><div><b>Thống kê theo ${esc(config.title.toLocaleLowerCase('vi-VN'))}</b><small>${Number((rows || []).length)} mục</small></div><input type="search" placeholder="${esc(config.search)}" oninput="filterScheduleAuditStats('${type}',this.value)" aria-label="${esc(config.search)}"></div>
    <div class="schedule-stat-table-wrap"><table class="schedule-stat-table"><thead><tr><th>${esc(config.title)}</th><th>Tổng tiết</th><th>${esc(config.first)}</th><th>${esc(config.second)}</th></tr></thead><tbody>${body || `<tr><td colspan="4" class="schedule-stat-none">Chưa có dữ liệu thống kê.</td></tr>`}</tbody></table></div>`;
}
function renderScheduleAuditStatistics(report) {
  const statistics = report?.statistics || { overview: {}, teachers: [], subjects: [], classes: [] };
  return `
    <section id="scheduleAuditView-overview" class="schedule-audit-view-panel" data-audit-panel="overview" hidden>${scheduleAuditStatsOverview(statistics)}</section>
    <section id="scheduleAuditView-teachers" class="schedule-audit-view-panel" data-audit-panel="teachers" hidden>${scheduleAuditStatsTable(statistics.teachers, 'teachers')}</section>
    <section id="scheduleAuditView-subjects" class="schedule-audit-view-panel" data-audit-panel="subjects" hidden>${scheduleAuditStatsTable(statistics.subjects, 'subjects')}</section>
    <section id="scheduleAuditView-classes" class="schedule-audit-view-panel" data-audit-panel="classes" hidden>${scheduleAuditStatsTable(statistics.classes, 'classes')}</section>`;
}
function switchScheduleAuditView(view) {
  const allowed = new Set(['timetable', 'overview', 'teachers', 'subjects', 'classes']);
  scheduleAuditActiveView = allowed.has(view) ? view : 'timetable';
  document.querySelectorAll('[data-audit-view]').forEach(button => {
    const active = button.dataset.auditView === scheduleAuditActiveView;
    button.classList.toggle('active', active); button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-audit-panel]').forEach(panel => { panel.hidden = panel.dataset.auditPanel !== scheduleAuditActiveView; });
}
function filterScheduleAuditStats(type, query) {
  const normalized = String(query || '').trim().toLocaleLowerCase('vi-VN');
  document.querySelectorAll(`#scheduleAuditView-${type} tbody tr[data-stat-text]`).forEach(row => { row.hidden = !!normalized && !String(row.dataset.statText || '').includes(normalized); });
}
function renderScheduleAuditDataIssues(issues) {
  if (!issues?.length) return '';
  return `<div class="schedule-audit-inline-issues"><div class="schedule-audit-group-head"><h3>Cảnh báo/lỗi dữ liệu cần xem lại</h3><span>${issues.length}</span></div><div class="schedule-audit-issue-list">${issues.map(issue => {
    const severity = issue.severity === 'error' ? 'error' : 'warning';
    const severityLabel = severity === 'error' ? 'Lỗi' : 'Cảnh báo';
    const location = [issue.slot_label, issue.entity].filter(Boolean).join(' · ');
    return `<article class="schedule-audit-issue ${severity}"><div class="schedule-audit-issue-mark">${severity === 'error' ? '!' : '⚠'}</div><div><div class="schedule-audit-issue-title"><b>${esc(issue.title || 'Cần xem lại')}</b><span>${severityLabel}</span></div>${issue.detail ? `<p>${esc(issue.detail)}</p>` : ''}${location ? `<small><b>Vị trí:</b> ${esc(location)}</small>` : ''}${issue.source ? `<small><b>Nguồn:</b> ${esc(issue.source)}</small>` : ''}</div></article>`;
  }).join('')}</div></div>`;
}

function renderScheduleAudit(report, ai = scheduleAuditAiAnalysis) {
  const box = $('#scheduleAuditResult'); if (!box) return;
  const summary = report.summary || {}, viewer = report.viewer || {}, issues = report.issues || [];
  const collisionIssues = issues.filter(item => ['teacher_collision', 'class_collision', 'room_collision'].includes(item.code));
  const nonCellIssues = issues.filter(item => !['teacher_collision', 'class_collision', 'room_collision'].includes(item.code));
  const conflicts = Number(summary.collisions || collisionIssues.length), affected = Number(viewer.conflict_cells || 0);
  const hasConflict = conflicts > 0, hasOtherIssues = nonCellIssues.length > 0, aiMarked = Number(ai?.summary?.marked_cells || 0);
  const statusTitle = hasConflict
    ? `Phát hiện ${conflicts} xung đột trong thời khóa biểu`
    : hasOtherIssues
      ? `Không có ô bị trùng, nhưng còn ${nonCellIssues.length} cảnh báo/lỗi dữ liệu`
      : 'Không phát hiện ô bị trùng';
  box.innerHTML = `
    <div class="schedule-audit-view-head ${hasConflict || hasOtherIssues ? 'has-error' : 'clean'}">
      <div class="schedule-audit-view-summary">
        <span class="schedule-audit-status-icon">${hasConflict || hasOtherIssues ? '!' : '✓'}</span>
        <div><h2>${statusTitle}</h2><p>${esc(report.filename || 'File')} · Đã đọc ${Number(summary.recognized_lessons || 0)} tiết · ${Number(summary.classes || 0)} lớp · ${Number(summary.teachers || 0)} giáo viên.</p></div>
      </div>
      <div class="schedule-audit-view-legend"><span class="legend-conflict"></span><b>Đỏ = lỗi rule</b>${hasConflict ? `<small>${affected} ô</small>` : ''}${ai ? `<span class="legend-ai-warning"></span><b>Cam/vàng = AI</b><small>${aiMarked} ô</small>` : ''}</div>
    </div>
    ${renderScheduleAuditDataIssues(nonCellIssues)}
    <div class="schedule-audit-tabs" role="tablist" aria-label="Chế độ xem thời khóa biểu">
      <button type="button" data-audit-view="timetable" onclick="switchScheduleAuditView('timetable')">Thời khóa biểu</button>
      <button type="button" data-audit-view="overview" onclick="switchScheduleAuditView('overview')">Tổng quan</button>
      <button type="button" data-audit-view="teachers" onclick="switchScheduleAuditView('teachers')">Giáo viên</button>
      <button type="button" data-audit-view="subjects" onclick="switchScheduleAuditView('subjects')">Môn học</button>
      <button type="button" data-audit-view="classes" onclick="switchScheduleAuditView('classes')">Lớp học</button>
    </div>
    <section id="scheduleAuditView-timetable" class="schedule-audit-view-panel" data-audit-panel="timetable">${renderScheduleAuditTable(report, ai)}</section>
    ${renderScheduleAuditStatistics(report)}`;
  switchScheduleAuditView(scheduleAuditActiveView);
}
function renderScheduleAuditError(message) {
  const box = $('#scheduleAuditResult'); if (!box) return;
  box.innerHTML = `<div class="schedule-audit-report-head has-error"><div><span class="schedule-audit-status-icon">!</span></div><div><h2>Không thể kiểm tra file</h2><p>${esc(message || 'Đã xảy ra lỗi khi đọc thời khóa biểu.')}</p></div></div>`;
}
function scheduleAuditCellLocation(cellKey, report) {
  const [slotRaw, classRaw] = String(cellKey || '').split(':'), slot = Number(slotRaw), classId = Number(classRaw), viewer = report?.viewer || {};
  if (!Number.isFinite(slot) || !Number.isFinite(classId)) return '';
  const cls = (viewer.classes || []).find(item => Number(item.id) === classId), part = scheduleAuditSlotParts(slot, viewer), session = scheduleAuditSessionName(part.session, viewer.sessions);
  return [scheduleAuditDayName(part.day), session, `Tiết ${part.period}`, cls?.name || `Lớp ${classId}`].filter(Boolean).join(' · ');
}
function renderScheduleAuditAiLoading() {
  const box = $('#scheduleAuditAiResult'); if (!box) return;
  box.hidden = false;
  box.innerHTML = '<div class="schedule-audit-ai-loading"><span></span><div><b>AI đang phân tích thời khóa biểu…</b><small>Rule thường vẫn giữ nguyên; AI chỉ bổ sung nhận xét.</small></div></div>';
}
function renderScheduleAuditAiError(message) {
  const box = $('#scheduleAuditAiResult'); if (!box) return;
  box.hidden = false;
  box.innerHTML = `<div class="schedule-audit-ai-head error"><div><span class="schedule-audit-ai-icon">!</span></div><div><h2>AI chưa thể phân tích</h2><p>${esc(message || 'Không thể kết nối tới AI.')}</p><small>Phần kiểm tra rule thường phía dưới vẫn sử dụng bình thường.</small></div></div>`;
}
function renderScheduleAuditAiResult(report, ai, model) {
  const box = $('#scheduleAuditAiResult'); if (!box) return;
  const issues = ai?.issues || [], summary = ai?.summary || {}, hasWarnings = Number(summary.warnings || 0) > 0;
  box.hidden = false;
  box.innerHTML = `
    <div class="schedule-audit-ai-head ${issues.length ? 'has-findings' : 'clean'}">
      <div><span class="schedule-audit-ai-icon">✦</span></div>
      <div class="schedule-audit-ai-copy"><div class="schedule-audit-ai-title-row"><h2>Phân tích bằng AI</h2></div><p>${esc(ai?.overview || 'Đã phân tích thời khóa biểu.')}</p><small>AI là lớp kiểm tra bổ sung theo heuristic; lỗi rule cứng vẫn được ưu tiên.</small></div>
      <div class="schedule-audit-ai-counts"><b>${Number(summary.total || issues.length)}</b><span>điểm cần xem</span>${hasWarnings ? `<small>${Number(summary.warnings || 0)} cảnh báo</small>` : ''}</div>
    </div>
    ${issues.length ? `<div class="schedule-audit-ai-issues">${issues.map(issue => {
    const locations = (issue.cell_keys || []).map(key => scheduleAuditCellLocation(key, report)).filter(Boolean);
    return `<article class="schedule-audit-ai-issue ${issue.severity === 'warning' ? 'warning' : 'suggestion'}"><div class="schedule-audit-ai-issue-mark">${issue.severity === 'warning' ? '!' : '✦'}</div><div><div class="schedule-audit-ai-issue-title"><b>${esc(issue.title || 'Cần xem lại')}</b><span>${esc(scheduleAuditAiCategoryLabel(issue.category))}</span></div>${issue.message ? `<p>${esc(issue.message)}</p>` : ''}${issue.suggestion ? `<small><b>Gợi ý:</b> ${esc(issue.suggestion)}</small>` : ''}${locations.length ? `<div class="schedule-audit-ai-locations">${locations.map(location => `<span>${esc(location)}</span>`).join('')}</div>` : '<div class="schedule-audit-ai-global">Nhận xét toàn cục</div>'}</div></article>`;
  }).join('')}</div>` : '<div class="schedule-audit-ai-empty">✓ AI không phát hiện bất thường đáng chú ý ngoài các kiểm tra rule hiện có.</div>'}`;
}
async function runScheduleAudit() {
  const input = $('#scheduleAuditFile'), button = $('#scheduleAuditButton'), file = scheduleAuditSelectedFile || input?.files?.[0];
  const validationError = scheduleAuditFileValidationError(file);
  if (validationError) { renderScheduleAuditError(validationError); return; }
  scheduleAuditAiRunId += 1; resetScheduleAuditAiResult();
  const runId = ++scheduleAuditRunId, drop = $('#scheduleAuditDropzone');
  if (button) { button.disabled = true; button.textContent = 'Đang phân tích…'; }
  if (drop) drop.classList.add('is-analyzing');
  const box = $('#scheduleAuditResult'); if (box) box.innerHTML = '<div class="schedule-audit-loading"><span></span><b>Đang đọc file và dựng thời khóa biểu…</b></div>';
  try {
    const form = new FormData(); form.append('file', file, file.name);
    const response = await fetch('/api/schedule-audit', { method: 'POST', headers: operationHeaders(), body: form });
    let result = {}; try { result = await response.json(); } catch { }
    if (runId !== scheduleAuditRunId) return;
    if (!response.ok || !result.ok) { scheduleAuditLastReport = null; renderScheduleAuditError(result.message || result.detail || `Máy chủ trả về lỗi ${response.status}.`); return; }
    scheduleAuditManualEdits = 0;
    scheduleAuditLastReport = result;
    renderScheduleAudit(result, null);
  } catch (error) {
    if (runId === scheduleAuditRunId) { scheduleAuditLastReport = null; renderScheduleAuditError(error?.message || 'Không thể kết nối tới máy chủ để kiểm tra file.'); }
  } finally {
    if (runId === scheduleAuditRunId) { if (button) { button.disabled = false; button.textContent = 'Kiểm tra lại'; } if (drop) drop.classList.remove('is-analyzing'); }
  }
}
async function runScheduleAuditAI() {
  const input = $('#scheduleAuditFile'), button = $('#scheduleAuditAiButton'), file = scheduleAuditSelectedFile || input?.files?.[0];
  const validationError = scheduleAuditFileValidationError(file);
  if (validationError) { renderScheduleAuditAiError(validationError); return; }
  if (!scheduleAuditAiIsEnabled()) { renderScheduleAuditAiError('Máy chủ chưa cấu hình GEMINI_API_KEY cho chức năng AI.'); return; }
  const runId = ++scheduleAuditAiRunId;
  if (button) { button.disabled = true; button.classList.add('is-loading'); button.textContent = '✦ AI đang phân tích…'; }
  renderScheduleAuditAiLoading();
  try {
    const form = new FormData();
    if (scheduleAuditLastReport && scheduleAuditManualEdits > 0) {
      form.append('report_json', JSON.stringify(scheduleAuditLastReport));
      form.append('file', file, file.name);
    } else form.append('file', file, file.name);
    const response = await fetch('/api/schedule-audit/ai', { method: 'POST', headers: operationHeaders(), body: form });
    let result = {}; try { result = await response.json(); } catch { }
    if (runId !== scheduleAuditAiRunId) return;
    if (!response.ok || !result.ok) { renderScheduleAuditAiError(result.message || result.detail || `AI trả về lỗi ${response.status}.`); return; }
    if (result.report) scheduleAuditLastReport = result.report;
    scheduleAuditAiAnalysis = result.ai || { overview: '', issues: [], summary: {} };
    scheduleAuditAiModel = result.model || '';
    if (scheduleAuditLastReport) renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis);
    renderScheduleAuditAiResult(scheduleAuditLastReport, scheduleAuditAiAnalysis, scheduleAuditAiModel);
  } catch (error) {
    if (runId === scheduleAuditAiRunId) renderScheduleAuditAiError(error?.message || 'Không thể kết nối tới AI để phân tích thời khóa biểu.');
  } finally {
    if (runId === scheduleAuditAiRunId && button) { button.disabled = false; button.classList.remove('is-loading'); button.textContent = '✦ Phân tích lại bằng AI'; }
  }
}

const scheduleAuditInput = $('#scheduleAuditFile'), scheduleAuditDropzone = $('#scheduleAuditDropzone');
if (scheduleAuditInput) scheduleAuditInput.addEventListener('change', () => { const file = scheduleAuditInput.files?.[0] || null; if (file) selectScheduleAuditFile(file); });
if (scheduleAuditDropzone) {
  let dragDepth = 0;
  scheduleAuditDropzone.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); scheduleAuditInput?.click(); } });
  scheduleAuditDropzone.addEventListener('dragenter', event => { event.preventDefault(); dragDepth += 1; scheduleAuditDropzone.classList.add('is-dragging'); if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'; });
  scheduleAuditDropzone.addEventListener('dragover', event => { event.preventDefault(); scheduleAuditDropzone.classList.add('is-dragging'); if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'; });
  scheduleAuditDropzone.addEventListener('dragleave', event => { event.preventDefault(); dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) scheduleAuditDropzone.classList.remove('is-dragging'); });
  scheduleAuditDropzone.addEventListener('drop', event => { event.preventDefault(); dragDepth = 0; scheduleAuditDropzone.classList.remove('is-dragging'); const files = Array.from(event.dataTransfer?.files || []); if (files.length > 1) { clearScheduleAuditFile(false); renderScheduleAuditError('Mỗi lần chỉ kiểm tra 1 file.'); return; } const file = files[0]; if (file) selectScheduleAuditFile(file); });
}
document.addEventListener('dragover', event => { if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault(); });
document.addEventListener('drop', event => { if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return; if (event.target?.closest?.('#scheduleAuditDropzone')) return; event.preventDefault(); });
