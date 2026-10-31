"use strict";
// Only user-entered thresholds are used. The imported timetable is initially
// checked for conflicts; weekly workloads are checked on explicit request.
let scheduleAuditWorkloadLimits = null;
let scheduleAuditWorkloadOpen = false;
let scheduleAuditWorkloadBusy = false;
let scheduleAuditWorkloadError = "";
let scheduleAuditWorkloadCheckId = 0;

const WEEKLY_LIMIT_TYPES = ["class_subject", "teachers", "assignments"];

function weeklyLoadNumber(value) {
  return value === null || value === undefined ? "—" : Number(value).toLocaleString("vi-VN", {maximumFractionDigits: 2});
}
function weeklyLoadTarget(row) {
  if (!row || (row.min == null && row.max == null)) return "Chưa nhập";
  if (row.min != null && row.max != null && Number(row.min) === Number(row.max)) return weeklyLoadNumber(row.min);
  return `${row.min == null ? "—" : weeklyLoadNumber(row.min)} – ${row.max == null ? "—" : weeklyLoadNumber(row.max)}`;
}
function weeklyLoadStatus(state, difference) {
  if (state === "extra") return `<span class="weekly-load-state extra">Thừa ${weeklyLoadNumber(Math.abs(difference))} tiết</span>`;
  if (state === "missing") return `<span class="weekly-load-state missing">Thiếu ${weeklyLoadNumber(Math.abs(difference))} tiết</span>`;
  if (state === "ok") return '<span class="weekly-load-state ok">Đạt ngưỡng</span>';
  if (state === "not_set") return '<span class="weekly-load-state unverified">Chưa đặt ngưỡng tổng</span>';
  return '<span class="weekly-load-state unverified">Chưa xác minh</span>';
}
function resetScheduleAuditWorkloadLimits() {
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadLimits = null;
  scheduleAuditWorkloadOpen = false;
  scheduleAuditWorkloadBusy = false;
  scheduleAuditWorkloadError = "";
}
function initScheduleAuditWorkloadLimits(report) {
  if (scheduleAuditWorkloadLimits) return;
  const viewer = report?.viewer || {}, cells = viewer.cells || [];
  const classSubjects = new Map(), teachers = new Map(), assignments = new Map();
  for (const cell of cells) {
    const cls = String(cell.class_name || "").trim();
    const grade = (cls.match(/^(1[0-2]|[1-9])[a-z]/i) || [])[1];
    const subject = String(cell.subject_name || "").trim();
    const teacher = String(cell.teacher_name || "").trim();
    if (grade && subject) classSubjects.set(`${grade}|${scheduleAuditEntityKey(subject)}`, {grade, subject, min: "", max: ""});
    if (teacher && !scheduleAuditIsUnknownTeacher(teacher)) teachers.set(scheduleAuditEntityKey(teacher), {teacher, min: "", max: ""});
    if (teacher && !scheduleAuditIsUnknownTeacher(teacher) && cls && subject)
      assignments.set(`${scheduleAuditEntityKey(teacher)}|${cls}|${scheduleAuditEntityKey(subject)}`, {teacher, class_name: cls, subject, min: "", max: ""});
  }
  scheduleAuditWorkloadLimits = {
    class_subject: [...classSubjects.values()].sort((a, b) => (a.grade - b.grade) || a.subject.localeCompare(b.subject, "vi")),
    teachers: [...teachers.values()].sort((a, b) => a.teacher.localeCompare(b.teacher, "vi")),
    assignments: [...assignments.values()].sort((a, b) => a.class_name.localeCompare(b.class_name, "vi", {numeric: true}) || a.teacher.localeCompare(b.teacher, "vi")),
  };
}
function openScheduleAuditWorkload() {
  if (!scheduleAuditLastReport) return;
  initScheduleAuditWorkloadLimits(scheduleAuditLastReport);
  scheduleAuditWorkloadOpen = true;
  scheduleAuditActiveView = "workload";
  renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis);
  document.getElementById("scheduleAuditView-workload")?.scrollIntoView({behavior: "smooth", block: "start"});
}
function weeklyLoadInput(type, index, field, value, aria) {
  const numeric = field === "min" || field === "max";
  return `<input type="${numeric ? "number" : "text"}" ${numeric ? 'min="0" max="1000" step="0.5" inputmode="decimal"' : 'maxlength="120"'} value="${esc(value ?? "")}" aria-label="${esc(aria)}" oninput="setScheduleAuditLimit('${type}',${index},'${field}',this.value)">`;
}
function renderWeeklyLoadRows(type) {
  const rows = scheduleAuditWorkloadLimits?.[type] || [];
  return rows.map((row, i) => {
    const inputs = type === "class_subject"
      ? `<td>${weeklyLoadInput(type, i, "grade", row.grade, "Khối")}</td><td>${weeklyLoadInput(type, i, "subject", row.subject, "Môn")}</td>`
      : type === "teachers"
        ? `<td>${weeklyLoadInput(type, i, "teacher", row.teacher, "Giáo viên")}</td>`
        : `<td>${weeklyLoadInput(type, i, "teacher", row.teacher, "Giáo viên")}</td><td>${weeklyLoadInput(type, i, "class_name", row.class_name, "Lớp")}</td><td>${weeklyLoadInput(type, i, "subject", row.subject, "Môn")}</td>`;
    return `<tr>${inputs}<td>${weeklyLoadInput(type, i, "min", row.min, "Tiết tối thiểu")}</td><td>${weeklyLoadInput(type, i, "max", row.max, "Tiết tối đa")}</td><td><button class="weekly-load-remove" type="button" title="Xóa dòng" aria-label="Xóa dòng" onclick="removeScheduleAuditLimit('${type}',${i})">×</button></td></tr>`;
  }).join("");
}
function renderWeeklyLimitSection(type, title, explanation, expanded = false) {
  const headings = type === "class_subject" ? "<th>Khối</th><th>Môn học</th>" :
    type === "teachers" ? "<th>Giáo viên</th>" : "<th>Giáo viên</th><th>Lớp</th><th>Môn học</th>";
  const count = scheduleAuditWorkloadLimits?.[type]?.length || 0;
  return `<details class="weekly-load-limits-section" ${expanded ? "open" : ""}><summary>${esc(title)} <small>(${count} dòng)</small></summary>
    <p>${esc(explanation)}</p>
    <div class="weekly-load-table-wrap"><table class="weekly-load-table weekly-load-input-table"><thead><tr>${headings}<th>Tối thiểu</th><th>Tối đa</th><th></th></tr></thead><tbody>${renderWeeklyLoadRows(type)}</tbody></table></div>
    <button class="btn ghost weekly-load-add" type="button" onclick="addScheduleAuditLimit('${type}')">+ Thêm dòng</button>
    </details>`;
}
function renderWeeklyLoadForm(report) {
  if (!scheduleAuditWorkloadLimits) return '<button class="btn weekly-load-action" type="button" onclick="openScheduleAuditWorkload()">Kiểm tra thừa/thiếu tiết</button>';
  return `<details id="weeklyLoadLimits" class="weekly-load-limits" ${scheduleAuditWorkloadOpen ? "open" : ""} ontoggle="scheduleAuditWorkloadOpen=this.open">
      <summary>Thiết lập ngưỡng thừa/thiếu tiết <span>(Nhấn để mở / thu gọn)</span></summary>
      <div class="weekly-load-limits-content">
        <p>Nhập số tiết/tuần theo dữ liệu thực tế của trường. <b>Để trống nếu chưa muốn kiểm tra.</b> Đặt tối thiểu = tối đa nếu phải đúng chính xác số tiết đó. Không có định mức nào được lấy từ bảng Word mẫu.</p>
        ${renderWeeklyLimitSection("class_subject", "1. Giới hạn tiết theo khối và môn", "Áp dụng cho từng lớp của khối đã có trong file import. Ví dụ khối 6 – Toán – tối thiểu 4, tối đa 4. Có thể thêm môn chưa có tiết trên TKB để phát hiện thiếu.", true)}
        ${renderWeeklyLimitSection("teachers", "2. Giới hạn tổng số tiết của giáo viên", "Kiểm tra tổng số tiết đứng lớp/tuần. Có thể nhập tên giáo viên chưa xuất hiện trong TKB để phát hiện thiếu.")}
        ${renderWeeklyLimitSection("assignments", "3. Giới hạn giáo viên – lớp – môn", "Để biết chính xác giáo viên thừa hoặc thiếu tiết ở lớp, môn nào. Có thể thêm phân công chưa xuất hiện trong TKB.")}
        <div class="weekly-load-actions"><button type="button" class="btn" ${scheduleAuditWorkloadBusy ? "disabled" : ""} onclick="runScheduleAuditWorkloadCheck()">${scheduleAuditWorkloadBusy ? "Đang đối chiếu…" : "Áp dụng & kiểm tra thừa/thiếu tiết"}</button><small>Chỉ các dòng đã nhập ít nhất một ngưỡng mới được so sánh.</small></div>
        <p id="weeklyLoadError" class="weekly-load-error" role="alert" ${scheduleAuditWorkloadError ? "" : "hidden"}>${esc(scheduleAuditWorkloadError)}</p>
      </div>
    </details>`;
}
function renderScheduleAuditWorkload(workload, report) {
  const form = `<div class="weekly-load-intro"><h2>Kiểm tra thừa/thiếu số tiết</h2><p>TKB đã được kiểm tra trùng lịch khi import. Phần thừa/thiếu chỉ chạy khi bạn nhập ngưỡng và nhấn kiểm tra.</p></div>${renderWeeklyLoadForm(report)}`;
  if (!workload) return `<div class="weekly-load-results">${form}<p class="weekly-load-notes">Chưa có kết quả đối chiếu theo ngưỡng nhập tay.</p></div>`;
  const totalRules = (workload.summary?.class_rules || 0) + (workload.summary?.teacher_rules || 0) + (workload.summary?.assignment_rules || 0);
  if (!totalRules) return `<div class="weekly-load-results">${form}<p class="weekly-load-notes">Chưa đặt ngưỡng nào. Hãy nhập ít nhất một dòng giới hạn rồi kiểm tra.</p></div>`;
  const summary = workload.summary || {};
  const diffs = (workload.classes || []).filter(item => item.status !== "ok");
  const teacherRows = (workload.teachers || []).filter(row => row.status !== "not_set" || (row.detail || []).length);
  const classTable = diffs.map(row => `<tr><td>${esc(row.class_name)}</td><td>${esc(row.subject)}</td><td>${esc(weeklyLoadTarget(row))}</td><td>${weeklyLoadNumber(row.actual)}</td><td>${weeklyLoadStatus(row.status, row.difference)}</td></tr>`).join("");
  const teacherTable = teacherRows.map(row => {
    const details = (row.detail || []).filter(x => x.status !== "ok");
    const detailTable = details.length ? `<div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Ngưỡng</th><th>Đã xếp</th><th>Kết quả</th></tr></thead><tbody>${details.map(x => `<tr><td>${esc(x.class_name)}</td><td>${esc(x.subject)}</td><td>${esc(weeklyLoadTarget(x))}</td><td>${weeklyLoadNumber(x.actual)}</td><td>${weeklyLoadStatus(x.status, x.difference)}</td></tr>`).join("")}</tbody></table></div>` : '<small>Không có phân công lớp/môn lệch ngưỡng.</small>';
    return `<tr data-weekly-teacher="${esc(row.name.toLocaleLowerCase("vi-VN"))}"><td><details class="weekly-load-teacher" ${details.length ? "open" : ""}><summary>${esc(row.name)}</summary><div class="weekly-load-detail">${detailTable}</div></details></td><td>${esc(weeklyLoadTarget(row))}</td><td>${weeklyLoadNumber(row.actual)}</td><td>${weeklyLoadStatus(row.status, row.difference)}</td></tr>`;
  }).join("");
  const notFound = (workload.unclassified_subjects || []).map(row => `<li>${esc(row.name)}: ${weeklyLoadNumber(row.lessons)} tiết</li>`).join("");
  return `<div class="weekly-load-results">${form}
    <div class="weekly-load-cards"><article><small>Lớp có trong TKB</small><b>${weeklyLoadNumber(summary.classes_checked || 0)}</b></article><article><small>Lớp/môn lệch ngưỡng</small><b>${weeklyLoadNumber(summary.class_subject_mismatches || 0)}</b></article><article><small>GV lệch tổng tiết</small><b>${weeklyLoadNumber(summary.teacher_mismatches || 0)}</b></article><article><small>Phân công GV/lớp/môn lệch</small><b>${weeklyLoadNumber(summary.assignment_mismatches || 0)}</b></article></div>
    <section class="weekly-load-section"><h3>Theo lớp và môn học</h3><p><small>Chỉ hiện những mục chưa đạt ngưỡng hoặc cần xác minh.</small></p><div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Giới hạn (tiết)</th><th>Đã xếp</th><th>Kết quả</th></tr></thead><tbody>${classTable || '<tr><td colspan="5">Không có chênh lệch trong những ngưỡng đã nhập.</td></tr>'}</tbody></table></div></section>
    <section class="weekly-load-section"><div class="weekly-load-section-title"><h3>Theo giáo viên và lớp phụ trách</h3><input type="search" placeholder="Tìm giáo viên…" aria-label="Tìm giáo viên" oninput="filterScheduleAuditWorkload(this.value)"></div><div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Giáo viên / Phân công lớp</th><th>Giới hạn tổng</th><th>Đã xếp</th><th>Kết quả tổng</th></tr></thead><tbody>${teacherTable || '<tr><td colspan="4">Chưa có ngưỡng giáo viên hoặc phân công được nhập.</td></tr>'}</tbody></table></div></section>
    ${notFound ? `<details class="weekly-load-disclosure"><summary>Môn chưa nhận diện chính xác trong TKB</summary><ul>${notFound}</ul></details>` : ""}
    <div class="weekly-load-notes">${(workload.notes || []).map(note => `<p>• ${esc(note)}</p>`).join("")}</div>
  </div>`;
}
function filterScheduleAuditWorkload(query) {
  const needle = String(query || "").trim().toLocaleLowerCase("vi-VN");
  document.querySelectorAll("[data-weekly-teacher]").forEach(row => row.hidden = !!needle && !String(row.dataset.weeklyTeacher || "").includes(needle));
}
function setScheduleAuditLimit(type, index, field, value) {
  if (!WEEKLY_LIMIT_TYPES.includes(type) || !scheduleAuditWorkloadLimits?.[type]?.[index]) return;
  scheduleAuditWorkloadLimits[type][index][field] = value;
  scheduleAuditWorkloadOpen = true;
  scheduleAuditWorkloadError = "";
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadBusy = false;
  if (scheduleAuditLastReport) scheduleAuditLastReport.workload = null;
  const error = document.getElementById("weeklyLoadError");
  if (error) error.hidden = true;
  // Remove stale results without destroying the form being edited.
  const results = document.querySelectorAll("#scheduleAuditView-workload .weekly-load-cards, #scheduleAuditView-workload .weekly-load-section, #scheduleAuditView-workload .weekly-load-notes");
  results.forEach(el => { if (!el.closest(".weekly-load-limits")) el.remove(); });
}
function redrawScheduleAuditWorkload() {
  const container = document.getElementById("scheduleAuditView-workload");
  if (container && scheduleAuditLastReport)
    container.innerHTML = renderScheduleAuditWorkload(scheduleAuditLastReport.workload, scheduleAuditLastReport);
}
function addScheduleAuditLimit(type) {
  if (!WEEKLY_LIMIT_TYPES.includes(type) || !scheduleAuditWorkloadLimits) return;
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadBusy = false;
  if (scheduleAuditLastReport) scheduleAuditLastReport.workload = null;
  scheduleAuditWorkloadLimits[type].push(type === "class_subject" ? {grade: "", subject: "", min: "", max: ""}
    : type === "teachers" ? {teacher: "", min: "", max: ""}
      : {teacher: "", class_name: "", subject: "", min: "", max: ""});
  scheduleAuditWorkloadOpen = true;
  redrawScheduleAuditWorkload();
  const sections = document.querySelectorAll("#weeklyLoadLimits .weekly-load-limits-section");
  const section = sections[WEEKLY_LIMIT_TYPES.indexOf(type)];
  if (section) section.open = true;
  section?.querySelector("tbody tr:last-child input")?.focus();
}
function removeScheduleAuditLimit(type, index) {
  if (!WEEKLY_LIMIT_TYPES.includes(type) || !scheduleAuditWorkloadLimits?.[type]) return;
  scheduleAuditWorkloadLimits[type].splice(index, 1);
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadBusy = false;
  if (scheduleAuditLastReport) scheduleAuditLastReport.workload = null;
  scheduleAuditWorkloadOpen = true;
  redrawScheduleAuditWorkload();
  const section = document.querySelectorAll("#weeklyLoadLimits .weekly-load-limits-section")[WEEKLY_LIMIT_TYPES.indexOf(type)];
  if (section) section.open = true;
}
async function runScheduleAuditWorkloadCheck() {
  const report = scheduleAuditLastReport;
  const file = scheduleAuditSelectedFile || document.getElementById("scheduleAuditFile")?.files?.[0];
  if (!report || !file || !scheduleAuditWorkloadLimits || scheduleAuditWorkloadBusy) return;
  const id = ++scheduleAuditWorkloadCheckId;
  scheduleAuditWorkloadBusy = true;
  scheduleAuditWorkloadError = "";
  redrawScheduleAuditWorkload();
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("report_json", JSON.stringify(report));
  form.append("limits_json", JSON.stringify(scheduleAuditWorkloadLimits));
  try {
    const response = await fetch("/api/schedule-audit/workload", {method: "POST", headers: operationHeaders(), body: form});
    const data = await readAuditResponse(response);
    if (id !== scheduleAuditWorkloadCheckId || scheduleAuditLastReport !== report) return;
    if (!response.ok || !data.ok) throw new Error(data.message || "Không thể kiểm tra ngưỡng tiết.");
    report.workload = data.workload;
    scheduleAuditWorkloadOpen = false;
    renderScheduleAudit(report, scheduleAuditAiAnalysis);
  } catch (error) {
    if (id !== scheduleAuditWorkloadCheckId || scheduleAuditLastReport !== report) return;
    scheduleAuditWorkloadError = error.message || "Không thể đối chiếu định mức.";
    scheduleAuditWorkloadOpen = true;
  } finally {
    if (id === scheduleAuditWorkloadCheckId) {
      scheduleAuditWorkloadBusy = false;
      redrawScheduleAuditWorkload();
    }
  }
}
