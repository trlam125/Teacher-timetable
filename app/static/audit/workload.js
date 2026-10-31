"use strict";
// Exact required periods are entered by the user and checked on demand.
// Import-time collision checking remains independent of this form.
let scheduleAuditWorkloadLimits = null;
let scheduleAuditWorkloadOpen = false;
let scheduleAuditWorkloadBusy = false;
let scheduleAuditWorkloadError = "";
let scheduleAuditWorkloadCheckId = 0;
let scheduleAuditTeacherOpen = false;
let scheduleAuditSelectedTeacher = "";
let scheduleAuditTeacherNotice = "";

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
  scheduleAuditTeacherOpen = false;
  scheduleAuditSelectedTeacher = "";
  scheduleAuditTeacherNotice = "";
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
  if (type !== "class_subject") return "";
  const rows = scheduleAuditWorkloadLimits?.class_subject || [];
  return rows.map((row, i) => ({row, i}))
    .filter(({row}) => !WEEKLY_MATRIX_GRADES.includes(String(row.grade)) || !weeklySubjectCode(row.subject))
    .map(({row, i}) => `<tr>
      <td>${weeklyLoadInput(type, i, "grade", row.grade, "Kh\u1ed1i")}</td>
      <td>${weeklyLoadInput(type, i, "subject", row.subject, "M\u00f4n")}</td>
      <td>${weeklyLoadInput(type, i, "periods", row.periods, "S\u1ed1 ti\u1ebft b\u1eaft bu\u1ed9c")}</td>
      <td><button class="weekly-load-remove" type="button" title="X\u00f3a d\u00f2ng" aria-label="X\u00f3a d\u00f2ng" onclick="removeScheduleAuditLimit('class_subject',${i})">&times;</button></td>
    </tr>`).join("");
}
// One teacher at a time: class x subject matrix instead of a repeated flat table.
function weeklyTeacherNames() {
  const names = new Map();
  for (const row of scheduleAuditWorkloadLimits?.assignments || []) {
    const name = String(row.teacher || "").trim();
    const key = scheduleAuditEntityKey(name);
    if (key && !names.has(key)) names.set(key, name);
  }
  return [...names.values()].sort((a,b) => a.localeCompare(b, "vi", {numeric:true}));
}
function weeklyActiveTeacher() {
  const teachers = weeklyTeacherNames();
  return teachers.find(x => scheduleAuditEntityKey(x) === scheduleAuditEntityKey(scheduleAuditSelectedTeacher)) || teachers[0] || "";
}
function weeklyTeacherEntries(teacher) {
  const key = scheduleAuditEntityKey(teacher);
  return (scheduleAuditWorkloadLimits?.assignments || []).map((row, index) => ({row,index}))
    .filter(({row}) => scheduleAuditEntityKey(row.teacher) === key);
}
function weeklyHasPeriods(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}
function weeklyTeacherStats(teacher) {
  const entries = weeklyTeacherEntries(teacher);
  const configured = entries.filter(({row}) => weeklyHasPeriods(row.periods));
  const expected = configured.reduce((sum, {row}) => sum + (Number(row.periods) || 0), 0);
  const imported = new Set((scheduleAuditLastReport?.viewer?.classes || []).map(x => scheduleAuditEntityKey(x.name)));
  const assigned = new Set(entries.map(({row}) => `${scheduleAuditEntityKey(row.class_name)}|${weeklySubjectCode(row.subject)}`));
  const teacherCells = (scheduleAuditLastReport?.viewer?.cells || []).filter(cell =>
    scheduleAuditEntityKey(cell.teacher_name) === scheduleAuditEntityKey(teacher) && imported.has(scheduleAuditEntityKey(cell.class_name)));
  const uncovered = teacherCells.filter(cell => !assigned.has(`${scheduleAuditEntityKey(cell.class_name)}|${weeklySubjectCode(cell.subject_name)}`)).length;
  const outOfScope = entries.some(({row}) => !imported.has(scheduleAuditEntityKey(row.class_name)));
  return {entered:configured.length, total:entries.length, expected, actual:teacherCells.length, uncovered,
    ready:entries.length > 0 && configured.length === entries.length && !uncovered && !outOfScope};
}
function weeklyTeacherActuals(teacher) {
  const counts = new Map();
  for (const cell of scheduleAuditLastReport?.viewer?.cells || []) {
    if (scheduleAuditEntityKey(cell.teacher_name) !== scheduleAuditEntityKey(teacher)) continue;
    const key = `${scheduleAuditEntityKey(cell.class_name)}|${weeklySubjectCode(cell.subject_name)}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}
function weeklyTeacherStatsLabel(stats) {
  return `${stats.entered}/${stats.total}`;
}
function weeklyTeacherGrid(teacher) {
  const entries = weeklyTeacherEntries(teacher);
  if (!entries.length) return '<p class="weekly-teacher-empty">Ch&#432;a c&#243; ph&#226;n c&#244;ng cho gi&#225;o vi&#234;n n&#224;y.</p>';
  const classes = [...new Set(entries.map(({row}) => row.class_name))]
    .sort((a,b) => a.localeCompare(b,"vi",{numeric:true}));
  const subjects = new Map();
  for (const {row} of entries) {
    const code = weeklySubjectCode(row.subject);
    if (code && !subjects.has(code)) subjects.set(code, row.subject);
  }
  const columns = [...subjects].sort((a,b) => a[1].localeCompare(b[1],"vi",{numeric:true}));
  const actual = weeklyTeacherActuals(teacher);
  const byCell = new Map(entries.map(item => [
    `${scheduleAuditEntityKey(item.row.class_name)}|${weeklySubjectCode(item.row.subject)}`, item]));
  const body = classes.map(cls => {
    const classKey = scheduleAuditEntityKey(cls);
    const occupied = entries.filter(({row}) => scheduleAuditEntityKey(row.class_name) === classKey);
    const assigned = occupied.filter(({row}) => weeklyHasPeriods(row.periods));
    const total = assigned.reduce((sum,{row}) => sum + (Number(row.periods) || 0),0);
    const totalLabel = assigned.length ? `${weeklyLoadNumber(total)}${assigned.length < occupied.length ? " *" : ""}` : "\u2014";
    return `<tr><th scope="row">${esc(cls)}</th>${columns.map(([code,label]) => {
      const item = byCell.get(`${classKey}|${code}`);
      if (!item) return '<td class="weekly-teacher-na" title="Kh\u00f4ng c\u00f3 ph\u00e2n c\u00f4ng">\u2014</td>';
      const found = actual.get(`${classKey}|${code}`) || 0;
      return `<td class="weekly-teacher-value"><input type="number" min="0" max="1000" step="0.5" inputmode="decimal" placeholder="\u2014" value="${esc(item.row.periods ?? "")}" aria-label="${esc(`${teacher} - ${cls} - ${label}`)}" oninput="setScheduleAuditLimit('assignments',${item.index},'periods',this.value)"><small title="S\u1ed1 ti\u1ebft trong TKB">TKB: ${found}</small></td>`;
    }).join("")}<td class="weekly-teacher-total" data-weekly-class="${esc(classKey)}">${totalLabel}</td></tr>`;
  }).join("");
  return `<div class="weekly-teacher-grid-wrap"><table class="weekly-teacher-grid"><thead><tr><th>L&#7899;p</th>${columns.map(([,label])=>`<th>${esc(label)}</th>`).join("")}<th>T&#7893;ng l&#7899;p</th></tr></thead><tbody>${body}</tbody></table></div>`;
}
function weeklyTeacherEditForm(teacher) {
  const entries = weeklyTeacherEntries(teacher);
  const classes = new Map(), subjects = new Map();
  for (const cls of scheduleAuditLastReport?.viewer?.classes || []) {
    if (cls?.name) classes.set(scheduleAuditEntityKey(cls.name), String(cls.name));
  }
  for (const cell of scheduleAuditLastReport?.viewer?.cells || []) {
    if (cell.class_name) classes.set(scheduleAuditEntityKey(cell.class_name), String(cell.class_name));
    if (cell.subject_name) subjects.set(weeklySubjectCode(cell.subject_name), String(cell.subject_name));
  }
  for (const {row} of entries) {
    classes.set(scheduleAuditEntityKey(row.class_name), row.class_name);
    subjects.set(weeklySubjectCode(row.subject), row.subject);
  }
  const classOptions = [...classes.values()].sort((a,b)=>a.localeCompare(b,"vi",{numeric:true}))
    .map(x=>`<option value="${esc(x)}"></option>`).join("");
  const subjectOptions = [...subjects.values()].sort((a,b)=>a.localeCompare(b,"vi",{numeric:true}))
    .map(x=>`<option value="${esc(x)}"></option>`).join("");
  const chips = entries.map(({row,index}) => `<span class="weekly-teacher-chip">${esc(row.class_name)} &middot; ${esc(row.subject)}
    <button type="button" aria-label="${esc('X\u00f3a '+row.class_name+' '+row.subject)}" title="X&#243;a ph&#226;n c&#244;ng" onclick="weeklyRemoveTeacherAssignment(${index})">&times;</button></span>`).join("");
  return `<details class="weekly-teacher-edit"><summary>+ B&#7893; sung / x&#243;a ph&#226;n c&#244;ng</summary>
    <p>Ch&#7881; c&#7847;n th&#234;m n&#7871;u TKB thi&#7871;u m&#7897;t m&#244;n ho&#7863;c l&#7899;p. T&#234;n gi&#225;o vi&#234;n &#273;&#227; &#273;&#432;&#7907;c ch&#7885;n s&#7861;n.</p>
    <form class="weekly-teacher-add" onsubmit="weeklyAddTeacherAssignment();return false">
      <label>L&#7899;p<input id="weeklyTeacherNewClass" list="weeklyTeacherClasses" placeholder="6A1" maxlength="120" required></label>
      <datalist id="weeklyTeacherClasses">${classOptions}</datalist>
      <label>M&#244;n<input id="weeklyTeacherNewSubject" list="weeklyTeacherSubjects" placeholder="To&#225;n" maxlength="120" required></label>
      <datalist id="weeklyTeacherSubjects">${subjectOptions}</datalist>
      <button class="btn ghost" type="submit">+ Th&#234;m</button>
    </form><div class="weekly-teacher-chips">${chips}</div>
  </details>`;
}
function weeklyTeacherWorkspace() {
  const name = weeklyActiveTeacher();
  if (!name) return '<p class="weekly-teacher-empty">TKB ch&#432;a c&#243; gi&#225;o vi&#234;n &#273;&#7875; thi&#7871;t l&#7853;p.</p>';
  const stats = weeklyTeacherStats(name);
  const complete = stats.ready;
  return `<div class="weekly-teacher-workspace-head"><div><strong>${esc(name)}</strong>
    <small>Nh&#7853;p ti&#7871;t cho t&#7915;ng l&#7899;p/m&#244;n. S&#7889; b&#234;n d&#432;&#7899;i &#244; l&#224; ti&#7871;t &#273;ang c&#243; trong TKB.</small></div>
    <span class="weekly-teacher-progress" id="weeklyTeacherProgress">${weeklyTeacherStatsLabel(stats)} &#244; &#273;&#227; nh&#7853;p</span></div>
    <div class="weekly-teacher-totals"><span>Ph&#226;n c&#244;ng: <b id="weeklyTeacherTargetTotal">${weeklyLoadNumber(stats.expected)}${complete ? "" : " *"}</b></span>
    <span>TKB: <b>${weeklyLoadNumber(stats.actual)}</b></span>
    <span id="weeklyTeacherTotalStatus">${complete ? (stats.expected === stats.actual ? "&#272;&#7911; ti&#7871;t" : "Ch&#234;nh l&#7879;ch: "+weeklyLoadNumber(stats.actual-stats.expected)) : "* Ch&#432;a x&#225;c minh t&#7893;ng ti&#7871;t"}</span></div>
    ${weeklyTeacherGrid(name)}
    <div class="weekly-teacher-tools"><button type="button" class="btn ghost" onclick="weeklyAutofillTeacher()">&#272;i&#7873;n nhanh t&#7915; b&#7843;ng kh&#7889;i</button>
    <small>Ch&#7881; &#273;i&#7873;n &#244; tr&#7889;ng khi m&#244;n/l&#7899;p c&#243; m&#7897;t gi&#225;o vi&#234;n; kh&#244;ng ghi &#273;&#232;.</small></div>
    ${weeklyTeacherEditForm(name)}
    <p class="weekly-teacher-notice" id="weeklyTeacherNotice" role="status">${esc(scheduleAuditTeacherNotice)}</p>`;
}
function renderWeeklyTeacherSection() {
  const teachers = weeklyTeacherNames(), active = weeklyActiveTeacher(), activeKey = scheduleAuditEntityKey(active);
  const entered = (scheduleAuditWorkloadLimits?.assignments || []).filter(row => weeklyHasPeriods(row.periods)).length;
  const count = scheduleAuditWorkloadLimits?.assignments?.length || 0;
  return `<details class="weekly-load-limits-section weekly-teacher-section" ${scheduleAuditTeacherOpen ? "open" : ""}
      ontoggle="scheduleAuditTeacherOpen=this.open"><summary>Ph&#226;n c&#244;ng gi&#225;o vi&#234;n theo l&#7899;p/m&#244;n
      <small>(${entered}/${count} &#244; &#273;&#227; nh&#7853;p)</small></summary>
    <p>Ch&#7885;n m&#7897;t gi&#225;o vi&#234;n, sau &#273;&#243; nh&#7853;p s&#7889; ti&#7871;t trong b&#7843;ng g&#7885;n. T&#7893;ng ti&#7871;t &#273;&#432;&#7907;c c&#7897;ng t&#7921; &#273;&#7897;ng.</p>
    <div class="weekly-teacher-layout"><div class="weekly-teacher-sidebar">
      <label class="weekly-teacher-search-label" for="weeklyTeacherSearch">T&#236;m gi&#225;o vi&#234;n</label>
      <input id="weeklyTeacherSearch" type="search" placeholder="Nh&#7853;p t&#234;n gi&#225;o vi&#234;n..." oninput="weeklyFilterTeachers(this.value)">
      <div class="weekly-teacher-nav" id="weeklyTeacherNav">${teachers.map((teacher,i)=>{
        const stats = weeklyTeacherStats(teacher);
        const key = scheduleAuditEntityKey(teacher);
        return `<button type="button" class="weekly-teacher-nav-item${key===activeKey ? " is-active" : ""}"
          data-weekly-teacher-name="${esc(teacher.toLocaleLowerCase('vi-VN'))}" data-weekly-teacher-key="${esc(key)}"
          aria-pressed="${key===activeKey}" onclick="weeklySelectTeacher(${i})"><span>${esc(teacher)}</span><small class="weekly-teacher-nav-count">${stats.entered}/${stats.total}</small></button>`;
      }).join("") || '<p>Ch&#432;a c&#243; gi&#225;o vi&#234;n.</p>'}</div>
    </div><div class="weekly-teacher-workspace" id="weeklyTeacherWorkspace">${weeklyTeacherWorkspace()}</div></div>
  </details>`;
}
function weeklyFilterTeachers(query) {
  const needle = String(query || "").normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .toLocaleLowerCase('vi-VN').replace(/\u0111/g,'d').trim();
  document.querySelectorAll('#weeklyTeacherNav [data-weekly-teacher-name]').forEach(button => {
    const label = String(button.dataset.weeklyTeacherName || "").normalize('NFD')
      .replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('vi-VN').replace(/\u0111/g,'d');
    button.hidden = Boolean(needle && !label.includes(needle));
  });
}
function weeklySelectTeacher(index) {
  const teachers = weeklyTeacherNames();
  if (!teachers[index]) return;
  scheduleAuditSelectedTeacher = teachers[index];
  scheduleAuditTeacherNotice = "";
  const area = document.getElementById('weeklyTeacherWorkspace');
  if (area) area.innerHTML = weeklyTeacherWorkspace();
  const chosen = scheduleAuditEntityKey(scheduleAuditSelectedTeacher);
  document.querySelectorAll('#weeklyTeacherNav [data-weekly-teacher-key]').forEach(button => {
    const active = button.dataset.weeklyTeacherKey === chosen;
    button.classList.toggle('is-active',active);
    button.setAttribute('aria-pressed', String(active));
  });
}
function weeklyRefreshTeacherStats() {
  const teacher = weeklyActiveTeacher();
  if (!teacher) return;
  const stats = weeklyTeacherStats(teacher);
  const ready = stats.ready;
  const set = (id, text) => {const el=document.getElementById(id); if(el) el.textContent=text;};
  set('weeklyTeacherProgress', `${weeklyTeacherStatsLabel(stats)} \u00f4 \u0111\u00e3 nh\u1eadp`);
  set('weeklyTeacherTargetTotal', `${weeklyLoadNumber(stats.expected)}${ready ? '' : ' *'}`);
  set('weeklyTeacherTotalStatus', ready ? (stats.expected === stats.actual ? '\u0110\u1ee7 ti\u1ebft' : `Ch\u00eanh l\u1ec7ch: ${weeklyLoadNumber(stats.actual-stats.expected)}`) : '* Ch\u01b0a x\u00e1c minh t\u1ed5ng ti\u1ebft');
  for (const item of weeklyTeacherEntries(teacher)) {
    const classKey = scheduleAuditEntityKey(item.row.class_name);
    const cell = document.querySelector('#weeklyTeacherWorkspace [data-weekly-class="'+classKey+'"]');
    if (!cell) continue;
    const group = weeklyTeacherEntries(teacher).filter(({row})=>scheduleAuditEntityKey(row.class_name)===classKey);
    const filled = group.filter(({row})=>weeklyHasPeriods(row.periods));
    cell.textContent = filled.length ? `${weeklyLoadNumber(filled.reduce((n,{row})=>n+(Number(row.periods)||0),0))}${filled.length<group.length ? ' *' : ''}` : '\u2014';
  }
  const all = (scheduleAuditWorkloadLimits?.assignments || []);
  const count = all.filter(row=>weeklyHasPeriods(row.periods)).length;
  const summary = document.querySelector('.weekly-teacher-section > summary small');
  if (summary) summary.textContent = `(${count}/${all.length} \u00f4 \u0111\u00e3 nh\u1eadp)`;
  const nav = document.querySelector('#weeklyTeacherNav [data-weekly-teacher-key="'+scheduleAuditEntityKey(teacher)+'"] .weekly-teacher-nav-count');
  if (nav) nav.textContent = weeklyTeacherStatsLabel(stats);
}
function weeklyAddTeacherAssignment() {
  const teacher = weeklyActiveTeacher();
  const cls = String(document.getElementById('weeklyTeacherNewClass')?.value || '').trim();
  const subject = String(document.getElementById('weeklyTeacherNewSubject')?.value || '').trim();
  if (!teacher || !cls || !subject || !scheduleAuditWorkloadLimits) return;
  const exists = weeklyTeacherEntries(teacher).some(({row}) =>
    scheduleAuditEntityKey(row.class_name) === scheduleAuditEntityKey(cls) && weeklySubjectCode(row.subject)===weeklySubjectCode(subject));
  if (exists) {scheduleAuditTeacherNotice='Ph\u00e2n c\u00f4ng n\u00e0y \u0111\u00e3 c\u00f3 trong b\u1ea3ng.'; document.getElementById('weeklyTeacherNotice').textContent=scheduleAuditTeacherNotice;return;}
  scheduleAuditWorkloadLimits.assignments.push({teacher,class_name:cls,subject,periods:''});
  weeklyAssignmentChanged();
  scheduleAuditTeacherOpen = true;
  scheduleAuditTeacherNotice='\u0110\u00e3 th\u00eam ph\u00e2n c\u00f4ng m\u1edbi. H\u00e3y nh\u1eadp s\u1ed1 ti\u1ebft v\u00e0 L\u01b0u.';
  redrawScheduleAuditWorkload();
}
function weeklyRemoveTeacherAssignment(index) {
  const rows = scheduleAuditWorkloadLimits?.assignments || [];
  if (!rows[index]) return;
  rows.splice(index,1);
  weeklyAssignmentChanged();
  scheduleAuditTeacherOpen=true;
  scheduleAuditTeacherNotice='\u0110\u00e3 b\u1ecf ph\u00e2n c\u00f4ng kh\u1ecfi b\u1ea3ng nh\u1eadp. H\u00e3y L\u01b0u \u0111\u1ec3 ghi nh\u1eadn.';
  redrawScheduleAuditWorkload();
}
function weeklyAssignmentChanged() {
  scheduleAuditLimitsDirty = true;
  scheduleAuditWorkloadOpen = true;
  scheduleAuditWorkloadError = '';
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadBusy = false;
  if (scheduleAuditLastReport) scheduleAuditLastReport.workload = null;
}
function weeklyAutofillTeacher() {
  const teacher = weeklyActiveTeacher();
  const entries = weeklyTeacherEntries(teacher);
  const classRules = new Map((scheduleAuditWorkloadLimits?.class_subject || [])
    .filter(row=>weeklyHasPeriods(row.periods))
    .map(row=>[`${String(row.grade)}|${weeklySubjectCode(row.subject)}`,Number(row.periods)]));
  const classTeachers = new Map();
  for (const cell of scheduleAuditLastReport?.viewer?.cells || []) {
    const key = `${scheduleAuditEntityKey(cell.class_name)}|${weeklySubjectCode(cell.subject_name)}`;
    if (!classTeachers.has(key)) classTeachers.set(key,new Set());
    if (cell.teacher_name) classTeachers.get(key).add(scheduleAuditEntityKey(cell.teacher_name));
  }
  const editable = entries.filter(({row}) => {
    if (weeklyHasPeriods(row.periods)) return false;
    const grade = (String(row.class_name).match(/^(1[0-2]|[1-9])[a-z]/i)||[])[1];
    const clazz = `${scheduleAuditEntityKey(row.class_name)}|${weeklySubjectCode(row.subject)}`;
    return classRules.has(`${grade}|${weeklySubjectCode(row.subject)}`) && classTeachers.get(clazz)?.size === 1 && classTeachers.get(clazz).has(scheduleAuditEntityKey(teacher));
  });
  if (!editable.length) {
    scheduleAuditTeacherNotice='Kh\u00f4ng c\u00f3 \u00f4 tr\u1ed1ng \u0111\u1ee7 \u0111i\u1ec1u ki\u1ec7n \u0111\u1ec3 \u0111i\u1ec1n nhanh.';
    const notice = document.getElementById('weeklyTeacherNotice'); if(notice) notice.textContent=scheduleAuditTeacherNotice;
    return;
  }
  if (!window.confirm(`\u0110i\u1ec1n ${editable.length} \u00f4 tr\u1ed1ng theo s\u1ed1 ti\u1ebft kh\u1ed1i cho ${teacher}? Ch\u1ec9 \u00e1p d\u1ee5ng khi TKB ghi m\u1ed9t gi\u00e1o vi\u00ean cho m\u00f4n/l\u1edbp. H\u00e3y r\u00e0 so\u00e1t l\u1ea1i v\u00ec TKB c\u00f3 th\u1ec3 ch\u01b0a \u0111\u1ea7y \u0111\u1ee7.`)) return;
  for (const {row} of editable) {
    const grade = (String(row.class_name).match(/^(1[0-2]|[1-9])[a-z]/i)||[])[1];
    row.periods=classRules.get(`${grade}|${weeklySubjectCode(row.subject)}`);
  }
  weeklyAssignmentChanged();
  scheduleAuditTeacherOpen=true;
  scheduleAuditTeacherNotice=`\u0110\u00e3 \u0111i\u1ec1n nhanh ${editable.length} \u00f4. Vui l\u00f2ng r\u00e0 so\u00e1t v\u00e0 b\u1ea5m L\u01b0u.`;
  redrawScheduleAuditWorkload();
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
        ${renderWeeklyTeacherSection()}
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
  if (type === "assignments" && field === "periods") weeklyRefreshTeacherStats();
}
function redrawScheduleAuditWorkload() {
  const container = document.getElementById("scheduleAuditView-workload");
  if (container && scheduleAuditLastReport)
    container.innerHTML = renderScheduleAuditWorkload(scheduleAuditLastReport.workload, scheduleAuditLastReport);
}
function addScheduleAuditLimit(type) {
  if (type !== "class_subject" || !scheduleAuditWorkloadLimits) return;
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
  if (type !== "class_subject" || !scheduleAuditWorkloadLimits?.[type]) return;
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
