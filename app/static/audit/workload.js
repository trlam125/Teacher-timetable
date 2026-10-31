"use strict";
// Exact required periods are entered by the user and checked on demand.
// Import-time collision checking remains independent of this form.
let scheduleAuditWorkloadLimits = null;
let scheduleAuditWorkloadOpen = false;
let scheduleAuditWorkloadBusy = false;
let scheduleAuditWorkloadError = "";
let scheduleAuditWorkloadCheckId = 0;

const WEEKLY_LIMIT_TYPES = ["class_subject", "assignments"];

// The import collision table is the single source of subject labels.
// Parentheses are meaningful: "KHTN" and "KHTN(S)" are different subjects.
const WEEKLY_MATRIX_GRADES = ["6", "7", "8", "9"];
function weeklySubjectCode(value) {
  return String(value ?? "").normalize("NFC").trim().replace(/\s+/g, " ")
    .toLocaleLowerCase("vi-VN").replace(/\s*\(\s*/g, "(").replace(/\s*\)\s*/g, ")");
}
function weeklyMatrixSubjects() {
  const names = new Map();
  for (const row of scheduleAuditWorkloadLimits?.class_subject || []) {
    if (!WEEKLY_MATRIX_GRADES.includes(String(row.grade))) continue;
    const label = String(row.subject || "").trim(), key = weeklySubjectCode(label);
    if (key && !names.has(key)) names.set(key, label);
  }
  return [...names.entries()].sort((a,b)=>a[1].localeCompare(b[1],"vi",{numeric:true}));
}
function weeklyNormalizeLimitDraft(limits) {
  return Object.fromEntries(WEEKLY_LIMIT_TYPES.map(type => [type,
    (limits?.[type] || []).map(row => ({...row, periods:row.periods ?? ""}))]));
}
function weeklyLoadNumber(value) {
  return value === null || value === undefined ? "—" : Number(value).toLocaleString("vi-VN", {maximumFractionDigits: 2});
}
function weeklyLoadTarget(row) {
  return row?.periods == null || row.periods === "" ? "Chưa nhập" : weeklyLoadNumber(row.periods);
}
function weeklyLoadStatus(state, difference) {
  if (state === "extra") return `<span class="weekly-load-state extra">Thừa ${weeklyLoadNumber(Math.abs(difference))} tiết</span>`;
  if (state === "missing") return `<span class="weekly-load-state missing">Thiếu ${weeklyLoadNumber(Math.abs(difference))} tiết</span>`;
  if (state === "ok") return '<span class="weekly-load-state ok">Đủ tiết</span>';
  if (state === "not_set") return '<span class="weekly-load-state unverified">Chưa nhập phân công</span>';
  return '<span class="weekly-load-state unverified">Chưa xác minh</span>';
}
function resetScheduleAuditWorkloadLimits() {
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadLimits = null;
  scheduleAuditWorkloadOpen = false;
  scheduleAuditWorkloadBusy = false;
  scheduleAuditWorkloadError = "";
  scheduleAuditLimitsDirty = false;
  scheduleAuditLimitsNotice = "";
  scheduleAuditSavedProfile = null;
}
function weeklyMakeLimitDraft(report) {
  const viewer = report?.viewer || {}, cells = viewer.cells || [];
  const classSubjects = new Map(), assignments = new Map();
  // Only show subjects actually present in the timetable's collision table.
  // Never split or rename "KHTN", "KHTN(S)", "LSĐL", "LSĐL(Đ)".
  const observed = new Map();
  for (const cell of cells) {
    const subject = String(cell.subject_name || "").trim();
    const key = weeklySubjectCode(subject);
    if (key && !scheduleAuditIsUnknownSubject(subject) && !observed.has(key))
      observed.set(key, subject);
  }
  for (const [code, label] of observed) {
    for (const grade of WEEKLY_MATRIX_GRADES)
      classSubjects.set(`${grade}|${code}`, {grade, subject:label, periods:""});
  }
  for (const cell of cells) {
    const cls = String(cell.class_name || "").trim();
    const grade = (cls.match(/^(1[0-2]|[1-9])[a-z]/i) || [])[1];
    const subject = String(cell.subject_name || "").trim();
    const teacher = String(cell.teacher_name || "").trim();
    const code = weeklySubjectCode(subject);
    if (grade && subject && !WEEKLY_MATRIX_GRADES.includes(grade) &&
        !scheduleAuditIsUnknownSubject(subject))
      classSubjects.set(`${grade}|${code}`, {grade,subject,periods:""});
    if (teacher && !scheduleAuditIsUnknownTeacher(teacher) && cls && subject &&
        !scheduleAuditIsUnknownSubject(subject))
      assignments.set(`${scheduleAuditEntityKey(teacher)}|${cls}|${code}`,
        {teacher, class_name:cls, subject, periods:""});
  }
  return {
    class_subject:[...classSubjects.values()],
    assignments:[...assignments.values()].sort((a,b)=>a.class_name.localeCompare(b.class_name,"vi",{numeric:true}) || a.teacher.localeCompare(b.teacher,"vi")),
  };
}
function initScheduleAuditWorkloadLimits(report) {
  if (!scheduleAuditWorkloadLimits) scheduleAuditWorkloadLimits = weeklyMakeLimitDraft(report);
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
  const numeric = field === "periods";
  return `<input type="${numeric ? "number" : "text"}" ${numeric ? 'min="0" max="1000" step="0.5" inputmode="decimal"' : 'maxlength="120"'} value="${esc(value ?? "")}" aria-label="${esc(aria)}" oninput="setScheduleAuditLimit('${type}',${index},'${field}',this.value)">`;
}
function renderWeeklyLoadRows(type) {
  const rows = scheduleAuditWorkloadLimits?.[type] || [];
  return rows.map((row, i) => ({row, i})).filter(({row}) => type !== "class_subject" ||
    !WEEKLY_MATRIX_GRADES.includes(String(row.grade)) || !weeklySubjectCode(row.subject))
    .map(({row, i}) => {
    const inputs = type === "class_subject"
      ? `<td>${weeklyLoadInput(type, i, "grade", row.grade, "Khối")}</td><td>${weeklyLoadInput(type, i, "subject", row.subject, "Môn")}</td>`
      : `<td>${weeklyLoadInput(type, i, "teacher", row.teacher, "Giáo viên")}</td><td>${weeklyLoadInput(type, i, "class_name", row.class_name, "Lớp")}</td><td>${weeklyLoadInput(type, i, "subject", row.subject, "Môn")}</td>`;
    return `<tr>${inputs}<td>${weeklyLoadInput(type, i, "periods", row.periods, "Số tiết bắt buộc")}</td><td><button class="weekly-load-remove" type="button" title="Xóa dòng" aria-label="Xóa dòng" onclick="removeScheduleAuditLimit('${type}',${i})">×</button></td></tr>`;
  }).join("");
}
function renderWeeklyLimitSection(type, title, explanation, expanded = false) {
  const headings = type === "class_subject" ? "<th>Khối</th><th>Môn học</th>" : "<th>Giáo viên</th><th>Lớp</th><th>Môn học</th>";
  const count = scheduleAuditWorkloadLimits?.[type]?.length || 0;
  return `<details class="weekly-load-limits-section" ${expanded ? "open" : ""}><summary>${esc(title)} <small>(${count} dòng)</small></summary>
    <p>${esc(explanation)}</p>
    <div class="weekly-load-table-wrap"><table class="weekly-load-table weekly-load-input-table"><thead><tr>${headings}<th>Tiết/tuần</th><th></th></tr></thead><tbody>${renderWeeklyLoadRows(type)}</tbody></table></div>
    <button class="btn ghost weekly-load-add" type="button" onclick="addScheduleAuditLimit('${type}')">+ Thêm dòng</button>
    </details>`;
}
function weeklyMatrixInput(code, label, index, grade) {
  const rows = scheduleAuditWorkloadLimits?.class_subject || [];
  const i = rows.findIndex(row => String(row.grade) === grade && weeklySubjectCode(row.subject) === code);
  const current = i >= 0 ? rows[i].periods : "";
  return `<input type="number" min="0" max="1000" step="0.5" inputmode="decimal" value="${esc(current ?? "")}" aria-label="${esc(label + " lớp " + grade)}" placeholder="—" oninput="setScheduleAuditMatrixLimit(${index},'${grade}',this.value)">`;
}
function renderWeeklyMatrix() {
  const subjects = weeklyMatrixSubjects();
  const lines = subjects.map(([code, name], i) => `<tr>
    <td class="weekly-matrix-index">${i+1}</td><th scope="row">${esc(name)}</th>
    ${WEEKLY_MATRIX_GRADES.map(grade=>`<td>${weeklyMatrixInput(code,name,i,grade)}</td>`).join("")}
    </tr>`).join("");
  return `<section class="weekly-matrix-panel">
    <h3>Số tiết bắt buộc của từng môn theo khối</h3>
    <p>Danh sách môn lấy tự động từ bảng kiểm tra trùng TKB, giữ nguyên tên môn. <b>KHTN</b> và <b>KHTN(S)</b> được kiểm tra riêng. Mỗi ô là đúng một mức tiết/tuần cho từng lớp trong khối.</p>
    <div class="weekly-matrix-wrap"><table class="weekly-matrix-table"><thead>
    <tr><th rowspan="2">TT</th><th rowspan="2">CÁC MÔN + HĐGD</th><th colspan="4">Số tiết/tuần</th></tr>
    <tr>${WEEKLY_MATRIX_GRADES.map(grade=>`<th>Lớp ${grade}</th>`).join("")}</tr>
    </thead><tbody>${lines || '<tr><td colspan="6">TKB chưa có tên môn để thiết lập.</td></tr>'}</tbody></table></div>
  </section>`;
}
function setScheduleAuditMatrixLimit(index, grade, value) {
  const rows = scheduleAuditWorkloadLimits?.class_subject;
  const subject = weeklyMatrixSubjects()[index];
  if (!rows || !subject || !WEEKLY_MATRIX_GRADES.includes(grade)) return;
  const [code,label] = subject;
  let idx = rows.findIndex(row => String(row.grade) === grade && weeklySubjectCode(row.subject) === code);
  if (idx < 0) { idx = rows.length; rows.push({grade, subject:label, periods:""}); }
  setScheduleAuditLimit("class_subject", idx, "periods", value);
}
function renderWeeklyLoadForm(report) {
  if (!scheduleAuditWorkloadLimits) return '<button class="btn weekly-load-action" type="button" onclick="openScheduleAuditWorkload()">Kiểm tra thừa/thiếu tiết</button>';
  const extras = renderWeeklyLoadRows("class_subject");
  return `<details id="weeklyLoadLimits" class="weekly-load-limits" ${scheduleAuditWorkloadOpen ? "open" : ""} ontoggle="scheduleAuditWorkloadOpen=this.open">
      <summary>Thiết lập số tiết bắt buộc <span>(Nhấn để mở / thu gọn)</span></summary>
      <div class="weekly-load-limits-content">
        ${renderWeeklyMatrix()}
        <details class="weekly-load-limits-section"><summary>Môn khác / khối khác (${(extras.match(/<tr>/g)||[]).length} dòng)</summary>
          <p>Có thể bổ sung thủ công môn khác hoặc khối ngoài 6–9.</p>
          <div class="weekly-load-table-wrap"><table class="weekly-load-table weekly-load-input-table"><thead><tr><th>Khối</th><th>Môn học</th><th>Tiết/tuần</th><th></th></tr></thead><tbody>${extras}</tbody></table></div>
          <button class="btn ghost weekly-load-add" type="button" onclick="addScheduleAuditLimit('class_subject')">+ Thêm môn/khối</button>
        </details>
        ${renderWeeklyLimitSection("assignments", "Tiết giáo viên dạy theo lớp/môn", "Nhập một số tiết cho mỗi giáo viên – lớp – môn. Tổng tiết giáo viên được tự cộng từ đây, không nhập riêng.")}
        <p class="weekly-load-save-status" role="status">${esc(scheduleAuditLimitsNotice || "Nhập số tiết rồi bấm Lưu để dùng lại vào lần sau.")}${scheduleAuditLimitsDirty ? " · Có thay đổi chưa lưu." : ""}</p>
        <div class="weekly-load-actions">
          <button type="button" class="btn ghost" ${scheduleAuditSavedBusy ? "disabled" : ""} onclick="saveScheduleAuditWorkloadLimits()">${scheduleAuditSavedBusy ? "Đang lưu…" : "Lưu số tiết"}</button>
          <button type="button" class="btn" ${scheduleAuditWorkloadBusy ? "disabled" : ""} onclick="runScheduleAuditWorkloadCheck()">${scheduleAuditWorkloadBusy ? "Đang đối chiếu…" : "Kiểm tra thừa/thiếu tiết"}</button>
          <small>Nhập đúng 1 mức; thiếu 1 tiết hay thừa 1 tiết đều được báo.</small>
        </div>
        <p id="weeklyLoadError" class="weekly-load-error" role="alert" ${scheduleAuditWorkloadError ? "" : "hidden"}>${esc(scheduleAuditWorkloadError)}</p>
      </div>
    </details>`;
}
function renderScheduleAuditWorkload(workload, report) {
  const form = `<div class="weekly-load-intro"><h2>Kiểm tra thừa/thiếu số tiết</h2><p>TKB đã được kiểm tra trùng lịch khi import. Phần thừa/thiếu chỉ chạy khi bạn nhập ngưỡng và nhấn kiểm tra.</p></div>${renderWeeklyLoadForm(report)}`;
  if (!workload) return `<div class="weekly-load-results">${form}<p class="weekly-load-notes">Chưa có kết quả đối chiếu theo số tiết bắt buộc.</p></div>`;
  const totalRules = (workload.summary?.class_rules || 0) + (workload.summary?.assignment_rules || 0);
  if (!totalRules) return `<div class="weekly-load-results">${form}<p class="weekly-load-notes">Chưa nhập số tiết nào. Hãy nhập ít nhất một ô rồi kiểm tra.</p></div>`;
  const summary = workload.summary || {};
  const diffs = (workload.classes || []).filter(item => item.status !== "ok");
  const teacherRows = (workload.teachers || []).filter(row => row.periods !== null || (row.detail || []).length);
  const classTable = diffs.map(row => `<tr><td>${esc(row.class_name)}</td><td>${esc(row.subject)}</td><td>${esc(weeklyLoadTarget(row))}</td><td>${weeklyLoadNumber(row.actual)}</td><td>${weeklyLoadStatus(row.status, row.difference)}</td></tr>`).join("");
  const teacherTable = teacherRows.map(row => {
    const details = (row.detail || []).filter(x => x.status !== "ok");
    const incompleteNote = row.status === "unverified" ? `<small>Chưa thể kết luận tổng tiết: còn phân công chưa nhập, lớp không có trong TKB hoặc ${weeklyLoadNumber(row.unconfigured_lessons || 0)} tiết chưa khai báo định mức.</small>` : "";
    const detailTable = details.length ? `<div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Bắt buộc</th><th>Đã xếp</th><th>Kết quả</th></tr></thead><tbody>${details.map(x => `<tr><td>${esc(x.class_name)}</td><td>${esc(x.subject)}</td><td>${esc(weeklyLoadTarget(x))}</td><td>${weeklyLoadNumber(x.actual)}</td><td>${weeklyLoadStatus(x.status, x.difference)}</td></tr>`).join("")}</tbody></table></div>` : '<small>Không có phân công lớp/môn lệch ngưỡng.</small>';
    return `<tr data-weekly-teacher="${esc(row.name.toLocaleLowerCase("vi-VN"))}"><td><details class="weekly-load-teacher" ${details.length ? "open" : ""}><summary>${esc(row.name)}</summary><div class="weekly-load-detail">${incompleteNote}${detailTable}</div></details></td><td>${esc(weeklyLoadTarget(row))}</td><td>${weeklyLoadNumber(row.actual)}</td><td>${weeklyLoadStatus(row.status, row.difference)}</td></tr>`;
  }).join("");
  const notFound = (workload.unclassified_subjects || []).map(row => `<li>${esc(row.name)}: ${weeklyLoadNumber(row.lessons)} tiết</li>`).join("");
  return `<div class="weekly-load-results">${form}
    <div class="weekly-load-cards"><article><small>Lớp có trong TKB</small><b>${weeklyLoadNumber(summary.classes_checked || 0)}</b></article><article><small>Lớp/môn thừa hoặc thiếu</small><b>${weeklyLoadNumber(summary.class_subject_mismatches || 0)}</b></article><article><small>GV lệch số tiết</small><b>${weeklyLoadNumber(summary.teacher_mismatches || 0)}</b></article><article><small>Phân công GV/lớp/môn sai tiết</small><b>${weeklyLoadNumber(summary.assignment_mismatches || 0)}</b></article></div>
    <section class="weekly-load-section"><h3>Theo lớp và môn học</h3><p><small>Chỉ hiện những mục chưa đủ số tiết hoặc cần xác minh.</small></p><div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Tiết bắt buộc</th><th>Đã xếp</th><th>Kết quả</th></tr></thead><tbody>${classTable || '<tr><td colspan="5">Không có chênh lệch trong những ngưỡng đã nhập.</td></tr>'}</tbody></table></div></section>
    <section class="weekly-load-section"><div class="weekly-load-section-title"><h3>Theo giáo viên và lớp phụ trách</h3><input type="search" placeholder="Tìm giáo viên…" aria-label="Tìm giáo viên" oninput="filterScheduleAuditWorkload(this.value)"></div><div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Giáo viên / Phân công lớp</th><th>Tổng từ phân công</th><th>Đã xếp</th><th>Đối chiếu</th></tr></thead><tbody>${teacherTable || '<tr><td colspan="4">Chưa nhập tiết giáo viên dạy theo lớp/môn.</td></tr>'}</tbody></table></div></section>
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
  scheduleAuditLimitsDirty = true;
  scheduleAuditWorkloadOpen = true;
  scheduleAuditWorkloadError = "";
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadBusy = false;
  if (scheduleAuditLastReport) scheduleAuditLastReport.workload = null;
  const error = document.getElementById("weeklyLoadError");
  if (error) error.hidden = true;
  const saveInfo = document.querySelector("#weeklyLoadLimits .weekly-load-save-status");
  if (saveInfo) saveInfo.textContent = `${scheduleAuditLimitsNotice || "Ngưỡng chưa được lưu."} · Có thay đổi chưa lưu.`;
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
  scheduleAuditLimitsDirty = true;
  scheduleAuditWorkloadLimits[type].push(type === "class_subject" ? {grade: "", subject: "", periods: ""}
    : {teacher: "", class_name: "", subject: "", periods: ""});
  scheduleAuditWorkloadOpen = true;
  redrawScheduleAuditWorkload();
  const sections = document.querySelectorAll("#weeklyLoadLimits .weekly-load-limits-section");
  const section = type === "class_subject" ? sections[0] : sections[WEEKLY_LIMIT_TYPES.indexOf(type)];
  if (section) section.open = true;
  section?.querySelector("tbody tr:last-child input")?.focus();
}
function removeScheduleAuditLimit(type, index) {
  if (!WEEKLY_LIMIT_TYPES.includes(type) || !scheduleAuditWorkloadLimits?.[type]) return;
  scheduleAuditWorkloadLimits[type].splice(index, 1);
  scheduleAuditLimitsDirty = true;
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
