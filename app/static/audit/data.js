"use strict";
function scheduleAuditConflictLabel(code) {
  return (
    {
      teacher_collision: "Trùng giáo viên",
      class_collision: "Trùng lớp",
      room_collision: "Trùng phòng",
    }[code] || "Xung đột"
  );
}
function scheduleAuditAiSeverityLabel(severity) {
  return severity === "warning" ? "AI cảnh báo" : "AI gợi ý";
}
function scheduleAuditAiCategoryLabel(category) {
  return (
    {
      distribution: "Phân bố lịch",
      teacher_load: "Tải giáo viên",
      consecutive: "Tiết liên tiếp",
      parser_suspicion: "Cần kiểm tra cách đọc ô",
      other: "Khác",
    }[category] || "Khác"
  );
}
function scheduleAuditSlotParts(slot, viewer) {
  const periods = Number(viewer.periods || 1),
    sessions = Number(viewer.sessions || 1),
    perDay = periods * sessions;
  const day = Math.floor(Number(slot) / perDay),
    inside = Number(slot) % perDay,
    session = Math.floor(inside / periods),
    period = (inside % periods) + 1;
  return { day, session, period };
}
function scheduleAuditDayName(day) {
  return (
    ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][day] ||
    `Ngày ${day + 1}`
  );
}
function scheduleAuditSessionName(session, sessions) {
  if (Number(sessions) <= 1) return "";
  return session === 0
    ? "Sáng"
    : session === 1
      ? "Chiều"
      : `Buổi ${session + 1}`;
}
function scheduleAuditAiMap(ai) {
  const map = new Map();
  for (const issue of ai?.issues || []) {
    for (const key of issue.cell_keys || []) {
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(issue);
    }
  }
  return map;
}
function scheduleAuditEntityKey(value) {
  return String(value ?? "")
    .trim()
    .toLocaleLowerCase("vi-VN")
    .replace(/đ/g, "d")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
function scheduleAuditIdentityKey(value) {
  return String(value ?? "")
    .normalize("NFC")
    .trim()
    .toLocaleLowerCase("vi-VN")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}
function scheduleAuditIsUnknownSubject(value) {
  return scheduleAuditEntityKey(value).startsWith("mon chua xac dinh");
}
function scheduleAuditIsUnknownTeacher(value) {
  return scheduleAuditEntityKey(value).startsWith("gv chua xac dinh");
}
function scheduleAuditTeacherIsOptional(subjectName) {
  return new Set([
    "chao co",
    "sinh hoat",
    "trai nghiem",
    "hdtn",
    "hdtnhn",
    "tnhn",
  ]).has(scheduleAuditEntityKey(subjectName));
}
function scheduleAuditShortName(value, fallback = "") {
  const words = String(value || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) return String(fallback || "").slice(0, 20);
  if (words.length === 1) return words[0].slice(0, 20).toUpperCase();
  return (
    words
      .map((word) => word[0] || "")
      .join("")
      .slice(0, 20)
      .toUpperCase() || String(fallback || "").slice(0, 20)
  );
}
function scheduleAuditRebuildDataFromViewer(report) {
  if (!report?.viewer) return;
  const viewer = report.viewer,
    cells = Array.isArray(viewer.cells) ? viewer.cells : [];
  const data = report.data || (report.data = {});
  const existingSubjects = Array.isArray(data.subjects) ? data.subjects : [];
  const existingTeachers = Array.isArray(data.teachers) ? data.teachers : [];
  const existingSubjectByKey = new Map(
    existingSubjects
      .map((row) => [scheduleAuditIdentityKey(row?.name), row])
      .filter(([key]) => key),
  );
  const existingTeacherByKey = new Map(
    existingTeachers
      .map((row) => [scheduleAuditIdentityKey(row?.name), row])
      .filter(([key]) => key),
  );
  const usedSubjectIds = new Set(),
    usedTeacherIds = new Set();
  let nextSubjectId =
    Math.max(0, ...existingSubjects.map((row) => Number(row?.id) || 0)) + 1;
  let nextTeacherId =
    Math.max(0, ...existingTeachers.map((row) => Number(row?.id) || 0)) + 1;
  const subjectsByKey = new Map(),
    teachersByKey = new Map();

  const reserveId = (preferred, used, nextRef) => {
    const parsed = Number(preferred);
    if (Number.isInteger(parsed) && parsed > 0 && !used.has(parsed)) {
      used.add(parsed);
      return [parsed, nextRef];
    }
    while (used.has(nextRef)) nextRef += 1;
    used.add(nextRef);
    return [nextRef, nextRef + 1];
  };
  const getSubject = (name) => {
    const clean = String(name || "").trim(),
      key = scheduleAuditIdentityKey(clean);
    if (subjectsByKey.has(key)) return subjectsByKey.get(key);
    const previous = existingSubjectByKey.get(key) || {};
    let id;
    [id, nextSubjectId] = reserveId(previous.id, usedSubjectIds, nextSubjectId);
    const row = {
      ...previous,
      id,
      name: clean,
      short_name:
        previous.short_name || scheduleAuditShortName(clean, `M${id}`),
      is_placeholder: scheduleAuditIsUnknownSubject(clean),
    };
    subjectsByKey.set(key, row);
    return row;
  };
  const getTeacher = (name) => {
    const clean = String(name || "").trim(),
      key = scheduleAuditIdentityKey(clean);
    if (teachersByKey.has(key)) return teachersByKey.get(key);
    const previous = existingTeacherByKey.get(key) || {};
    let id;
    [id, nextTeacherId] = reserveId(previous.id, usedTeacherIds, nextTeacherId);
    const row = {
      ...previous,
      id,
      name: clean,
      short_name:
        previous.short_name || scheduleAuditShortName(clean, `GV${id}`),
      is_placeholder: scheduleAuditIsUnknownTeacher(clean),
      subject_ids: [],
    };
    teachersByKey.set(key, row);
    return row;
  };

  const assignmentsByKey = new Map(),
    lessons = [];
  let nextAssignmentId = 1;
  for (const cell of cells) {
    const classId = Number(cell.class_id),
      subject = getSubject(cell.subject_name),
      teacher = getTeacher(cell.teacher_name);
    const key = `${classId}:${subject.id}:${teacher.id}`;
    let assignment = assignmentsByKey.get(key);
    if (!assignment) {
      assignment = {
        id: nextAssignmentId++,
        class_id: classId,
        subject_id: subject.id,
        teacher_id: teacher.id,
        periods_per_week: 0,
        block_mode: "free",
        class_name: String(cell.class_name || "").trim(),
        subject_name: subject.name,
        subject_short: subject.short_name,
        teacher_name: teacher.name,
        teacher_short: teacher.short_name,
      };
      assignmentsByKey.set(key, assignment);
    }
    assignment.periods_per_week += 1;
    if (!teacher.subject_ids.includes(subject.id))
      teacher.subject_ids.push(subject.id);
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
    report.detection.teachers = data.teachers
      .filter((row) => !row.is_placeholder)
      .map((row) => row.name);
    report.detection.classes = (viewer.classes || []).map((row) => row.name);
  }
}
