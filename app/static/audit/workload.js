"use strict";
// Exact required periods are entered by the user and checked on demand.
// Import-time collision checking remains independent of this form.
let scheduleAuditWorkloadLimits = null;
let scheduleAuditWorkloadOpen = false;
let scheduleAuditWorkloadBusy = false;
let scheduleAuditWorkloadError = "";
let scheduleAuditWorkloadCheckId = 0;
let scheduleAuditTeacherOpen = false;
let scheduleAuditTeacherMatrixGrade = "all";
let scheduleAuditTeacherNotice = "";

const WEEKLY_LIMIT_TYPES = ["class_subject", "assignments"];

// The shared school catalog defines official subject labels and their order.
// A generic integrated subject remains distinct from each component.
const WEEKLY_MATRIX_GRADES = ["6", "7", "8", "9"];
function weeklySubjectCode(value) { return schoolSubjectCatalog.key(value); }
function weeklyCanonicalSubject(value) {return schoolSubjectCatalog.canonical(value);}
function weeklyImportedSubjectNames(report) {
  const names = new Map();
  for (const cell of report?.viewer?.cells || []) {
    const label = String(cell.subject_name || "").trim();
    if (!label || scheduleAuditIsUnknownSubject(label)) continue;
    const code = weeklySubjectCode(label);
    if (!names.has(code)) names.set(code, weeklyCanonicalSubject(label));
  }
  return names;
}
function weeklySubjectSortRank(label) {return schoolSubjectCatalog.rank(label);}
function weeklyMatrixSubjects() {
  const names = new Map();
  for (const row of scheduleAuditWorkloadLimits?.class_subject || []) {
    if (!/^(?:[1-9]|1[0-2])$/.test(String(row.grade))) continue;
    const label = weeklyCanonicalSubject(row.subject), key = weeklySubjectCode(label);
    if (key && !names.has(key)) names.set(key, label);
  }
  return [...names.entries()].sort((a,b) => weeklySubjectSortRank(a[1]) - weeklySubjectSortRank(b[1])
    || a[1].localeCompare(b[1], "vi", {numeric:true}));
}
function weeklyNormalizeLimitDraft(limits) {
  return Object.fromEntries(WEEKLY_LIMIT_TYPES.map(type => [type,
    (limits?.[type] || []).map(row => ({...row, subject:weeklyCanonicalSubject(row.subject), periods:row.periods ?? ""}))]));
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
  scheduleAuditTeacherMatrixGrade = "all";
  scheduleAuditTeacherNotice = "";
  scheduleAuditLimitsDirty = false;
  scheduleAuditLimitsNotice = "";
  scheduleAuditSavedProfile = null;
}
function weeklyMakeLimitDraft(report) {
  const viewer = report?.viewer || {}, cells = viewer.cells || [];
  const classSubjects = new Map(), assignments = new Map();
  // The imported subjects are relabeled to the 16 canonical names;
  // unsuffixed integrated subjects remain separate from their components.
  const observed = weeklyImportedSubjectNames(report);
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
    const displaySubject = observed.get(code) || weeklyCanonicalSubject(subject);
    if (grade && subject && !WEEKLY_MATRIX_GRADES.includes(grade) &&
        !scheduleAuditIsUnknownSubject(subject))
      classSubjects.set(`${grade}|${code}`, {grade,subject:displaySubject,periods:""});
    if (teacher && !scheduleAuditIsUnknownTeacher(teacher) && cls && subject &&
        !scheduleAuditIsUnknownSubject(subject))
      assignments.set(`${scheduleAuditEntityKey(teacher)}|${cls}|${code}`,
        {teacher, class_name:cls, subject:displaySubject, periods:""});
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
  renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis, false);
  document.getElementById("scheduleAuditView-workload")?.scrollIntoView({behavior: "smooth", block: "start"});
}
// Excel-style assignment matrix: one row per subject, two columns (GV / Số tiết)
// per class. Keep the saved model (teacher, class_name, subject, periods) intact.
function weeklyHasPeriods(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}
function weeklyAssignmentChanged() {
  scheduleAuditLimitsDirty = true;
  scheduleAuditWorkloadOpen = true;
  scheduleAuditWorkloadError = "";
  scheduleAuditWorkloadCheckId++;
  scheduleAuditWorkloadBusy = false;
  if (scheduleAuditLastReport) scheduleAuditLastReport.workload = null;
}
function weeklyMatrixClasses() {
  const names = new Map();
  const add = name => {
    const label = String(name || "").trim();
    const key = scheduleAuditEntityKey(label);
    if (key && !names.has(key)) names.set(key, label);
  };
  for (const cls of scheduleAuditLastReport?.viewer?.classes || []) add(cls.name);
  for (const row of scheduleAuditWorkloadLimits?.assignments || []) add(row.class_name);
  return [...names.values()].sort((a,b) => a.localeCompare(b,"vi",{numeric:true}));
}
function weeklyMatrixTeacherNames() {
  const teachers = new Map();
  for (const row of scheduleAuditWorkloadLimits?.assignments || []) {
    const t = String(row.teacher || "").trim(), k = scheduleAuditEntityKey(t);
    if (k && !teachers.has(k)) teachers.set(k,t);
  }
  for (const cell of scheduleAuditLastReport?.viewer?.cells || []) {
    const t = String(cell.teacher_name || "").trim(), k = scheduleAuditEntityKey(t);
    if (k && !scheduleAuditIsUnknownTeacher(t) && !teachers.has(k)) teachers.set(k,t);
  }
  return [...teachers.values()].sort((a,b) => a.localeCompare(b,"vi",{numeric:true}));
}
function weeklyAssignmentMatrixSubjects() {
  const subjects = new Map(weeklyMatrixSubjects());
  for (const row of scheduleAuditWorkloadLimits?.assignments || []) {
    const name = weeklyCanonicalSubject(row.subject), key = weeklySubjectCode(name);
    if (key && !subjects.has(key)) subjects.set(key,name);
  }
  return [...subjects.entries()].sort((a,b) => weeklySubjectSortRank(a[1]) - weeklySubjectSortRank(b[1])
    || a[1].localeCompare(b[1],"vi",{numeric:true}));
}
function weeklyMatrixActualCounts() {
  const counts = new Map();
  for (const cell of scheduleAuditLastReport?.viewer?.cells || []) {
    const teacher = String(cell.teacher_name || "").trim();
    const cls = String(cell.class_name || "").trim();
    const subject = String(cell.subject_name || "").trim();
    if (!teacher || !cls || !subject) continue;
    const key = `${scheduleAuditEntityKey(teacher)}|${scheduleAuditEntityKey(cls)}|${weeklySubjectCode(subject)}`;
    counts.set(key,(counts.get(key)||0)+1);
  }
  return counts;
}
function weeklyAssignmentMatrixStats() {
  const rows = scheduleAuditWorkloadLimits?.assignments || [];
  const filled = rows.filter(x => weeklyHasPeriods(x.periods));
  const target = filled.reduce((sum,x) => sum + (Number(x.periods)||0),0);
  return {filled:filled.length,total:rows.length,target};
}
function weeklyMatrixSetGrade(grade) {
  if (grade !== "all" && !WEEKLY_MATRIX_GRADES.includes(grade)) return;
  scheduleAuditTeacherMatrixGrade = grade;
  const node = document.getElementById("weeklyTeacherMatrixWorkspace");
  if (node) node.innerHTML = weeklyTeacherMatrixWorkspace();
}
function weeklyMatrixShowNotice(message) {
  scheduleAuditTeacherNotice = message;
  const node = document.getElementById("weeklyTeacherNotice");
  if (node) node.textContent = message;
}
function weeklyMatrixAddByIndex(subjectIndex, classIndex) {
  const classes=weeklyMatrixClasses().filter(cls => scheduleAuditTeacherMatrixGrade === "all" ||
    (String(cls).match(/^(1[0-2]|[1-9])[a-z]/i)||[])[1] === scheduleAuditTeacherMatrixGrade);
  const subject=weeklyAssignmentMatrixSubjects()[subjectIndex];
  if (!subject || !classes[classIndex]) return;
  weeklyMatrixAddAssignment(classes[classIndex], subject[1]);
}
function weeklyMatrixRedraw() {
  const area=document.getElementById("weeklyTeacherMatrixWorkspace");
  if (!area) return;
  const prev=area.querySelector?.(".weekly-assignment-scroll");
  const left=prev?.scrollLeft || 0, top=prev?.scrollTop || 0;
  area.innerHTML=weeklyTeacherMatrixWorkspace();
  const next=area.querySelector?.(".weekly-assignment-scroll");
  if (next) {next.scrollLeft=left;next.scrollTop=top;}
}
function weeklyMatrixAddAssignment(className, subject) {
  if (!scheduleAuditWorkloadLimits) return;
  const cls=String(className||"").trim(), label=String(subject||"").trim();
  if (!cls || !label) return;
  if (scheduleAuditWorkloadLimits.assignments.some(row => !String(row.teacher||"").trim() &&
    scheduleAuditEntityKey(row.class_name)===scheduleAuditEntityKey(cls) &&
    weeklySubjectCode(row.subject)===weeklySubjectCode(label))) {
    weeklyMatrixShowNotice("Ô này đã có dòng chưa chọn giáo viên. Hãy điền dòng đó trước khi thêm tiếp.");
    return;
  }
  // Empty rows never become permanent until the user explicitly clicks "+".
  scheduleAuditWorkloadLimits.assignments.push({teacher:"",class_name:cls,subject:label,periods:""});
  weeklyAssignmentChanged();
  scheduleAuditTeacherOpen=true;
  weeklyMatrixShowNotice("Đã thêm một ô phân công. Chọn giáo viên và nhập số tiết trước khi lưu.");
  weeklyMatrixRedraw();
}
function weeklyMatrixChangeTeacher(index, value, input) {
  const list=scheduleAuditWorkloadLimits?.assignments || [];
  const row=list[index];
  if (!row) return;
  const name=String(value||"").trim();
  if (!name || scheduleAuditIsUnknownTeacher(name)) {
    if (input) input.value=row.teacher;
    weeklyMatrixShowNotice("Hãy chọn hoặc nhập tên giáo viên hợp lệ. Dùng nút × để xóa phân công.");
    return;
  }
  const key=scheduleAuditEntityKey(name);
  const repeated=list.some((candidate,i) => i !== index &&
    scheduleAuditEntityKey(candidate.teacher)===key &&
    scheduleAuditEntityKey(candidate.class_name)===scheduleAuditEntityKey(row.class_name) &&
    weeklySubjectCode(candidate.subject)===weeklySubjectCode(row.subject));
  if (repeated) {
    if (input) input.value=row.teacher;
    weeklyMatrixShowNotice("Giáo viên đã có phân công cho môn và lớp này; không thể thêm trùng.");
    return;
  }
  if (row.teacher===name) return;
  row.teacher=name;
  weeklyAssignmentChanged();
  weeklyMatrixShowNotice("Đã đổi giáo viên. Hãy lưu bảng phân công khi hoàn thành.");
  weeklyMatrixRefreshSummary();
}
function weeklyRemoveTeacherAssignment(index) {
  const rows=scheduleAuditWorkloadLimits?.assignments || [];
  if (!rows[index]) return;
  rows.splice(index,1);
  weeklyAssignmentChanged();
  scheduleAuditTeacherOpen=true;
  scheduleAuditTeacherNotice="Đã xóa phân công khỏi bảng nhập. Bấm Lưu để ghi nhận.";
  weeklyMatrixRedraw();
}
function weeklyMatrixRefreshSummary() {
  const stats=weeklyAssignmentMatrixStats();
  const display=document.getElementById("weeklyMatrixEnteredCount");
  if (display) display.textContent=`${stats.filled}/${stats.total} ô đã nhập · ${weeklyLoadNumber(stats.target)} tiết`;
  const summary=document.querySelector(".weekly-teacher-section > summary small");
  if (summary) summary.textContent=`(${stats.filled}/${stats.total} phân công)`;
  for (const cls of weeklyMatrixClasses()) {
    const clskey=scheduleAuditEntityKey(cls);
    let total=0,ready=true,hasRow=false;
    for (const row of scheduleAuditWorkloadLimits?.assignments || []) {
      if (scheduleAuditEntityKey(row.class_name)!==clskey) continue;
      hasRow=true;
      if (!weeklyHasPeriods(row.periods) || !String(row.teacher||"").trim()) ready=false;
      else total+=Number(row.periods)||0;
    }
    for (const node of document.querySelectorAll('[data-weekly-matrix-class-total]')) {
      if (node.dataset.weeklyMatrixClassTotal!==clskey) continue;
      node.textContent=hasRow ? `${weeklyLoadNumber(total)}${ready?'':' *'}` : "—";
    }
  }
  const actual=weeklyMatrixActualCounts();
  for (const [index,row] of (scheduleAuditWorkloadLimits?.assignments||[]).entries()) {
    const badge=document.querySelector(`[data-weekly-matrix-actual="${index}"]`);
    if (!badge) continue;
    const n=actual.get(`${scheduleAuditEntityKey(row.teacher)}|${scheduleAuditEntityKey(row.class_name)}|${weeklySubjectCode(row.subject)}`)||0;
    badge.textContent=`TKB: ${n}`;
  }
}
function weeklyAutofillTeacher() {
  const entries=(scheduleAuditWorkloadLimits?.assignments||[]).filter(row => !weeklyHasPeriods(row.periods) && row.teacher);
  const classRules=new Map((scheduleAuditWorkloadLimits?.class_subject||[])
    .filter(row=>weeklyHasPeriods(row.periods))
    .map(row=>[`${String(row.grade)}|${weeklySubjectCode(row.subject)}`,Number(row.periods)]));
  const observed=new Map();
  for (const cell of scheduleAuditLastReport?.viewer?.cells||[]) {
    const key=`${scheduleAuditEntityKey(cell.class_name)}|${weeklySubjectCode(cell.subject_name)}`;
    if (!observed.has(key)) observed.set(key,new Set());
    if (cell.teacher_name && !scheduleAuditIsUnknownTeacher(cell.teacher_name))
      observed.get(key).add(scheduleAuditEntityKey(cell.teacher_name));
  }
  const eligible=entries.filter(row=>{
    const grade=(String(row.class_name).match(/^(1[0-2]|[1-9])[a-z]/i)||[])[1];
    const key=`${scheduleAuditEntityKey(row.class_name)}|${weeklySubjectCode(row.subject)}`;
    return classRules.has(`${grade}|${weeklySubjectCode(row.subject)}`) &&
      observed.get(key)?.size===1 && observed.get(key).has(scheduleAuditEntityKey(row.teacher)) &&
      !((scheduleAuditWorkloadLimits?.assignments||[]).some(other => other!==row &&
        scheduleAuditEntityKey(other.class_name)===scheduleAuditEntityKey(row.class_name) &&
        weeklySubjectCode(other.subject)===weeklySubjectCode(row.subject)));
  });
  if (!eligible.length) {weeklyMatrixShowNotice("Không có ô trống đủ điều kiện điền nhanh."); return;}
  if (!window.confirm(`Điền ${eligible.length} phân công trống từ bảng số tiết theo khối? Chỉ áp dụng khi TKB có một giáo viên duy nhất cho môn/lớp; không ghi đè ô đã nhập.`)) return;
  for (const row of eligible) {
    const grade=(String(row.class_name).match(/^(1[0-2]|[1-9])[a-z]/i)||[])[1];
    row.periods=classRules.get(`${grade}|${weeklySubjectCode(row.subject)}`);
  }
  weeklyAssignmentChanged();
  scheduleAuditTeacherOpen=true;
  scheduleAuditTeacherNotice=`Đã điền ${eligible.length} ô. Rà soát và bấm Lưu.`;
  weeklyMatrixRedraw();
}
function weeklyTeacherMatrixWorkspace() {
  const classes=weeklyMatrixClasses().filter(cls=>scheduleAuditTeacherMatrixGrade==="all" ||
    (String(cls).match(/^(1[0-2]|[1-9])[a-z]/i)||[])[1]===scheduleAuditTeacherMatrixGrade);
  const subjects=weeklyAssignmentMatrixSubjects();
  const entries=scheduleAuditWorkloadLimits?.assignments||[];
  const byCell=new Map();
  for (const [index,row] of entries.entries()) {
    const key=`${scheduleAuditEntityKey(row.class_name)}|${weeklySubjectCode(row.subject)}`;
    if (!byCell.has(key)) byCell.set(key,[]);
    byCell.get(key).push({row,index});
  }
  const actual=weeklyMatrixActualCounts();
  const teacherOptions=weeklyMatrixTeacherNames().map(x=>`<option value="${esc(x)}"></option>`).join("");
  const stats=weeklyAssignmentMatrixStats();
  const grades=["all",...WEEKLY_MATRIX_GRADES];
  const buttons=grades.map(g=>`<button type="button" class="weekly-assignment-grade${g===scheduleAuditTeacherMatrixGrade?' active':''}"
    aria-pressed="${g===scheduleAuditTeacherMatrixGrade}" onclick="weeklyMatrixSetGrade('${g}')">${g==='all'?'Tất cả':`Khối ${g}`}</button>`).join("");
  const headers=classes.map(x=>`<th colspan="2" scope="colgroup">${esc(x)}</th>`).join("");
  const subheaders=classes.map(()=>`<th>GV</th><th>Số tiết</th>`).join("");
  const subjectsRows=subjects.map(([code,label],i)=>`<tr><td class="weekly-assignment-index">${i+1}</td>
    <th scope="row" class="weekly-assignment-subject">${esc(label)}</th>
    ${classes.map((cls,cj)=>{
      const matches=byCell.get(`${scheduleAuditEntityKey(cls)}|${code}`)||[];
      const body=matches.map(({row,index})=>{
        const n=actual.get(`${scheduleAuditEntityKey(row.teacher)}|${scheduleAuditEntityKey(cls)}|${code}`)||0;
        return {teacher:`<div class="weekly-assignment-entry"><input type="text" list="weeklyMatrixTeachers" value="${esc(row.teacher)}"
          placeholder="Giáo viên" maxlength="120" aria-label="${esc(label+' '+cls+' giáo viên')}" onchange="weeklyMatrixChangeTeacher(${index},this.value,this)">
          <button type="button" class="weekly-assignment-remove" title="Xóa phân công" aria-label="${esc('Xóa '+row.teacher+' '+cls+' '+label)}" onclick="weeklyRemoveTeacherAssignment(${index})">×</button></div>`,
          periods:`<div class="weekly-assignment-entry"><input type="number" min="0" max="1000" step="0.5" inputmode="decimal"
          value="${esc(row.periods??'')}" placeholder="—" aria-label="${esc(label+' '+cls+' số tiết')}"
          oninput="setScheduleAuditLimit('assignments',${index},'periods',this.value)">
          <small data-weekly-matrix-actual="${index}">TKB: ${n}</small></div>`};
      });
      const add=`<button type="button" class="weekly-assignment-add" title="Thêm giáo viên" aria-label="${esc('Thêm giáo viên '+label+' '+cls)}"
        onclick="weeklyMatrixAddByIndex(${i},${cj})">+</button>`;
      return `<td class="weekly-assignment-teacher-cell">${body.map(x=>x.teacher).join('')}${add}</td>
        <td class="weekly-assignment-period-cell">${body.map(x=>x.periods).join('')}${matches.length?'':'<span class="weekly-assignment-hint">—</span>'}</td>`;
    }).join('')}</tr>`).join('');
  const totals=classes.map(cls=>{
    const current=entries.filter(row=>scheduleAuditEntityKey(row.class_name)===scheduleAuditEntityKey(cls));
    const ready=current.length>0 && current.every(x=>weeklyHasPeriods(x.periods)&&String(x.teacher||'').trim());
    const total=current.reduce((s,x)=>s+(weeklyHasPeriods(x.periods)?Number(x.periods)||0:0),0);
    return `<td colspan="2" data-weekly-matrix-class-total="${esc(scheduleAuditEntityKey(cls))}">${current.length?`${weeklyLoadNumber(total)}${ready?'':' *'}`:'—'}</td>`;
  }).join('');
  return `<div class="weekly-assignment-toolbar"><div class="weekly-assignment-tabs">${buttons}</div>
    <span class="weekly-teacher-progress" id="weeklyMatrixEnteredCount">${stats.filled}/${stats.total} ô đã nhập · ${weeklyLoadNumber(stats.target)} tiết</span></div>
    <p class="weekly-assignment-help">Mỗi môn là một dòng; mỗi lớp có cột <b>GV</b> và <b>Số tiết</b> như bảng Excel. Bấm <b>+</b> để thêm giáo viên, kể cả khi một môn do nhiều giáo viên cùng dạy. Dấu * nghĩa là còn ô chưa nhập.</p>
    <datalist id="weeklyMatrixTeachers">${teacherOptions}</datalist>
    <div class="weekly-assignment-scroll" tabindex="0" aria-label="Bảng phân công giáo viên theo lớp và môn, cuộn ngang để xem các lớp khác">
      <table class="weekly-assignment-table"><thead><tr><th rowspan="2" class="weekly-assignment-index">TT</th>
        <th rowspan="2" class="weekly-assignment-subject">Môn</th>${headers}</tr><tr>${subheaders}</tr></thead>
        <tbody>${subjectsRows || `<tr><td colspan="${2+2*classes.length}">TKB chưa có môn học.</td></tr>`}
        <tr class="weekly-assignment-total"><th colspan="2">Tổng tiết phân công</th>${totals}</tr></tbody></table></div>
    <div class="weekly-teacher-tools"><button type="button" class="btn ghost" onclick="weeklyAutofillTeacher()">Điền nhanh từ bảng khối</button>
      <small>Chỉ điền ô trống khi có một giáo viên duy nhất; không tự ghi đè.</small></div>
    <p class="weekly-teacher-notice" id="weeklyTeacherNotice" role="status">${esc(scheduleAuditTeacherNotice)}</p>`;
}
function renderWeeklyTeacherSection() {
  const stats=weeklyAssignmentMatrixStats();
  return `<details class="weekly-load-limits-section weekly-teacher-section" ${scheduleAuditTeacherOpen?'open':''}
    ontoggle="scheduleAuditTeacherOpen=this.open"><summary>Phân công giáo viên theo lớp, môn
      <small>(${stats.filled}/${stats.total} phân công)</small></summary>
    <div id="weeklyTeacherMatrixWorkspace">${weeklyTeacherMatrixWorkspace()}</div>
  </details>`;
}
// Extra subjects and grades are managed inside the same matrix as the imported
// subjects. A blank subject row for a nonstandard grade is a harmless marker
// that lets a newly added grade remain visible until numbers are entered.
function weeklyMatrixGrades() {
  const values = new Set(WEEKLY_MATRIX_GRADES);
  for (const row of scheduleAuditWorkloadLimits?.class_subject || []) {
    const grade = String(row.grade || "").trim();
    if (/^(?:[1-9]|1[0-2])$/.test(grade)) values.add(grade);
  }
  return [...WEEKLY_MATRIX_GRADES, ...[...values].filter(g => !WEEKLY_MATRIX_GRADES.includes(g))
    .sort((a,b) => Number(a) - Number(b))];
}
function weeklyMatrixImportedSubjects() {
  return new Set((scheduleAuditLastReport?.viewer?.cells || [])
    .filter(row => !scheduleAuditIsUnknownSubject(String(row.subject_name || "")))
    .map(row => weeklySubjectCode(row.subject_name)));
}
function weeklyMatrixInput(code, label, index, grade) {
  const rows = scheduleAuditWorkloadLimits?.class_subject || [];
  const i = rows.findIndex(row => String(row.grade) === grade && weeklySubjectCode(row.subject) === code);
  const current = i >= 0 ? rows[i].periods : "";
  return `<input type="number" min="0" max="1000" step="0.5" inputmode="decimal" value="${esc(current ?? "")}" aria-label="${esc(label + " lớp " + grade)}" placeholder="—" oninput="setScheduleAuditMatrixLimit(${index},'${grade}',this.value)">`;
}
function renderWeeklyMatrix() {
  const subjects = weeklyMatrixSubjects();
  const grades = weeklyMatrixGrades();
  const importedSubjects = weeklyMatrixImportedSubjects();
  const extraGrades = Array.from({length:12}, (_,i)=>String(i+1)).filter(g=>!grades.includes(g));
  const gradeSelect = `<select id="weeklyNewGrade" aria-label="Chọn khối cần thêm" ${extraGrades.length?'':'disabled'}>
    ${extraGrades.map(grade=>`<option value="${grade}">Khối ${grade}</option>`).join('')}</select>`;
  const lines = subjects.map(([code, name], i) => `<tr>
    <td class="weekly-matrix-index">${i+1}</td><th scope="row"><span class="weekly-matrix-subject-name">${esc(name)}</span>
    ${importedSubjects.has(code)?'':`<button class="weekly-matrix-remove" type="button" title="Xóa môn tự thêm" aria-label="Xóa môn ${esc(name)}" onclick="weeklyMatrixRemoveSubject(${i})">×</button>`}</th>
    ${grades.map(grade=>`<td>${weeklyMatrixInput(code,name,i,grade)}</td>`).join("")}
    </tr>`).join("");
  const headers = grades.map(grade=>`<th id="weeklyMatrixGrade-${grade}">Lớp ${grade}${WEEKLY_MATRIX_GRADES.includes(grade) ? '' :
    ` <button type="button" class="weekly-matrix-remove" title="Xóa khối ${grade}" aria-label="Xóa khối ${grade}" onclick="weeklyMatrixRemoveGrade('${grade}')">×</button>`}</th>`).join('');
  return `<section class="weekly-matrix-panel">
    <h3>1. Số tiết bắt buộc của từng môn theo khối</h3>
    <p>Giữ tên môn đúng như bảng TKB; <b>KHTN</b> và <b>KHTN(S)</b> là hai môn độc lập. Môn/khối mới được thêm ngay vào bảng này, không tạo bảng phụ.</p>
    <div class="weekly-matrix-wrap"><table class="weekly-matrix-table"><thead>
    <tr><th rowspan="2">TT</th><th rowspan="2">CÁC MÔN + HĐGD</th><th colspan="${grades.length}">Số tiết/tuần</th></tr>
    <tr>${headers}</tr>
    </thead><tbody>${lines || `<tr><td colspan="${2+grades.length}">Chưa có tên môn học. Có thể nhập môn ở bên dưới.</td></tr>`}</tbody></table></div>
    <div class="weekly-matrix-edit-tools">
      <label for="weeklyNewSubject">Môn khác <input id="weeklyNewSubject" type="text" maxlength="120" placeholder="Tên môn đúng như trên TKB" onkeydown="if(event.key==='Enter'){event.preventDefault();weeklyMatrixAddSubject()}"></label>
      <button type="button" class="btn ghost" onclick="weeklyMatrixAddSubject()">+ Thêm môn vào bảng</button>
      <label for="weeklyNewGrade">Khối khác ${gradeSelect}</label>
      <button type="button" class="btn ghost" ${extraGrades.length?'':'disabled'} onclick="weeklyMatrixAddGrade()">+ Thêm khối vào bảng</button>
    </div>
    <p class="weekly-matrix-hint" id="weeklyMatrixNotice" role="status"></p>
  </section>`;
}
function setScheduleAuditMatrixLimit(index, grade, value) {
  const rows = scheduleAuditWorkloadLimits?.class_subject;
  const subject = weeklyMatrixSubjects()[index];
  if (!rows || !subject || !weeklyMatrixGrades().includes(grade)) return;
  const [code,label] = subject;
  let idx = rows.findIndex(row => String(row.grade) === grade && weeklySubjectCode(row.subject) === code);
  if (idx < 0) { idx = rows.length; rows.push({grade, subject:label, periods:""}); }
  setScheduleAuditLimit("class_subject", idx, "periods", value);
}
function weeklyMatrixNote(message) {
  const node = document.getElementById('weeklyMatrixNotice');
  if (node) node.textContent = message;
}
function weeklyMatrixAddSubject() {
  if (!scheduleAuditWorkloadLimits) return;
  const input = document.getElementById('weeklyNewSubject');
  const name = weeklyCanonicalSubject(input?.value);
  if (!name) { weeklyMatrixNote('Hãy nhập tên môn cần thêm.'); input?.focus(); return; }
  if (weeklyMatrixSubjects().some(([code])=>code===weeklySubjectCode(name))) {
    weeklyMatrixNote('Môn này đã có trong bảng. Hãy nhập trực tiếp số tiết tại dòng của môn.');
    return;
  }
  scheduleAuditWorkloadLimits.class_subject.push({grade:WEEKLY_MATRIX_GRADES[0], subject:name, periods:""});
  weeklyAssignmentChanged();
  redrawScheduleAuditWorkload();
  document.getElementById('weeklyNewSubject')?.focus();
  weeklyMatrixNote(`Đã thêm ${name} vào Mục 1. Hãy nhập tiết cho từng khối rồi bấm Lưu số tiết.`);
}
function weeklyMatrixAddGrade() {
  if (!scheduleAuditWorkloadLimits) return;
  const grade = String(document.getElementById('weeklyNewGrade')?.value || '');
  if (!/^(?:[1-9]|1[0-2])$/.test(grade) || weeklyMatrixGrades().includes(grade)) return;
  scheduleAuditWorkloadLimits.class_subject.push({grade, subject:'', periods:''});
  weeklyAssignmentChanged();
  redrawScheduleAuditWorkload();
  weeklyMatrixNote(`Đã thêm khối ${grade} vào cùng bảng. Hãy nhập số tiết ở cột mới.`);
}
function weeklyMatrixRemoveSubject(index) {
  const subject = weeklyMatrixSubjects()[index];
  if (!subject || weeklyMatrixImportedSubjects().has(subject[0])) return;
  const [code, label] = subject;
  const rows = scheduleAuditWorkloadLimits.class_subject;
  const affected = rows.filter(x=>weeklySubjectCode(x.subject)===code);
  const assignments = scheduleAuditWorkloadLimits.assignments.filter(x=>weeklySubjectCode(x.subject)===code);
  if ((affected.some(x=>weeklyHasPeriods(x.periods)) || assignments.length) &&
      !window.confirm(`Xóa môn "${label}" và ${assignments.length} phân công liên quan khỏi bảng định mức?`)) return;
  scheduleAuditWorkloadLimits.class_subject = rows.filter(x=>weeklySubjectCode(x.subject)!==code);
  scheduleAuditWorkloadLimits.assignments = scheduleAuditWorkloadLimits.assignments.filter(x=>weeklySubjectCode(x.subject)!==code);
  weeklyAssignmentChanged();
  redrawScheduleAuditWorkload();
}
function weeklyMatrixRemoveGrade(grade) {
  if (WEEKLY_MATRIX_GRADES.includes(grade) || !weeklyMatrixGrades().includes(grade)) return;
  const rows = scheduleAuditWorkloadLimits.class_subject.filter(x=>String(x.grade)===grade);
  if (rows.some(x=>weeklyHasPeriods(x.periods)) &&
      !window.confirm(`Xóa toàn bộ số tiết đã nhập của khối ${grade} trong bảng định mức?`)) return;
  scheduleAuditWorkloadLimits.class_subject = scheduleAuditWorkloadLimits.class_subject.filter(x=>String(x.grade)!==grade);
  weeklyAssignmentChanged();
  redrawScheduleAuditWorkload();
}
function renderWeeklyLoadForm(report) {
  if (!scheduleAuditWorkloadLimits) return '<button class="btn weekly-load-action" type="button" onclick="openScheduleAuditWorkload()">Kiểm tra thừa/thiếu tiết</button>';
  return `<details id="weeklyLoadLimits" class="weekly-load-limits" ${scheduleAuditWorkloadOpen ? "open" : ""} ontoggle="scheduleAuditWorkloadOpen=this.open">
      <summary>Thiết lập số tiết bắt buộc <span>(Nhấn để mở / thu gọn)</span></summary>
      <div class="weekly-load-limits-content">
        ${renderWeeklyMatrix()}
        ${renderWeeklyTeacherSection()}
        <p class="weekly-load-save-status" role="status">${esc(scheduleAuditLimitsNotice || "Nhập số tiết rồi bấm Lưu để dùng lại vào lần sau.")}${scheduleAuditLimitsDirty ? " · Có thay đổi chưa lưu." : ""}</p>
        <div class="weekly-load-actions">
          <button type="button" class="btn ghost" ${scheduleAuditSavedBusy ? "disabled" : ""} onclick="saveScheduleAuditWorkloadLimits()">${scheduleAuditSavedBusy ? "Đang lưu…" : "Lưu số tiết"}</button>
          <button type="button" class="btn" ${scheduleAuditWorkloadBusy ? "disabled" : ""} onclick="runScheduleAuditWorkloadCheck()">${scheduleAuditWorkloadBusy ? "Đang đối chiếu…" : "Kiểm tra thừa/thiếu tiết"}</button>
          <button type="button" class="btn ghost weekly-load-reset" ${scheduleAuditSavedBusy ? "disabled" : ""} onclick="clearAllScheduleAuditWorkloadLimits()">Xóa toàn bộ định mức</button>
          <small>Nhập một số tiết bắt buộc ở mỗi ô; thừa hoặc thiếu đều bị báo.</small>
        </div>
        <p id="weeklyLoadError" class="weekly-load-error" role="alert" ${scheduleAuditWorkloadError ? "" : "hidden"}>${esc(scheduleAuditWorkloadError)}</p>
      </div>
    </details>`;
}
function renderScheduleAuditWorkload(workload, report) {
  const form = `<div class="weekly-load-intro"><h2>Kiểm tra thừa/thiếu số tiết</h2><p>TKB đã được kiểm tra trùng tiết khi tải lên. Để kiểm tra thừa/thiếu, hãy nhập số tiết quy định rồi bấm Kiểm tra.</p></div>${renderWeeklyLoadForm(report)}`;
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
    const detailTable = details.length ? `<div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Bắt buộc</th><th>Đã xếp</th><th>Kết quả</th></tr></thead><tbody>${details.map(x => `<tr><td>${esc(x.class_name)}</td><td>${esc(x.subject)}</td><td>${esc(weeklyLoadTarget(x))}</td><td>${weeklyLoadNumber(x.actual)}</td><td>${weeklyLoadStatus(x.status, x.difference)}</td></tr>`).join("")}</tbody></table></div>` : '<small>Không có phân công nào thừa hoặc thiếu so với số tiết đã nhập.</small>';
    return `<tr data-weekly-teacher="${esc(row.name.toLocaleLowerCase("vi-VN"))}"><td><details class="weekly-load-teacher" ${details.length ? "open" : ""}><summary>${esc(row.name)}</summary><div class="weekly-load-detail">${incompleteNote}${detailTable}</div></details></td><td>${esc(weeklyLoadTarget(row))}</td><td>${weeklyLoadNumber(row.actual)}</td><td>${weeklyLoadStatus(row.status, row.difference)}</td></tr>`;
  }).join("");
  const notFound = (workload.unclassified_subjects || []).map(row => `<li>${esc(row.name)}: ${weeklyLoadNumber(row.lessons)} tiết</li>`).join("");
  return `<div class="weekly-load-results">${form}
    <div class="weekly-load-cards"><article><small>Lớp có trong TKB</small><b>${weeklyLoadNumber(summary.classes_checked || 0)}</b></article><article><small>Lớp/môn thừa hoặc thiếu</small><b>${weeklyLoadNumber(summary.class_subject_mismatches || 0)}</b></article><article><small>GV lệch số tiết</small><b>${weeklyLoadNumber(summary.teacher_mismatches || 0)}</b></article><article><small>Phân công GV/lớp/môn sai tiết</small><b>${weeklyLoadNumber(summary.assignment_mismatches || 0)}</b></article></div>
    <section class="weekly-load-section"><h3>Theo lớp và môn học</h3><p><small>Chỉ hiện những mục chưa đủ số tiết hoặc cần xác minh.</small></p><div class="weekly-load-table-wrap"><table class="weekly-load-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Tiết bắt buộc</th><th>Đã xếp</th><th>Kết quả</th></tr></thead><tbody>${classTable || '<tr><td colspan="5">Các môn đã khai báo đều đủ số tiết theo quy định.</td></tr>'}</tbody></table></div></section>
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
  if (type === "assignments" && field === "periods") weeklyMatrixRefreshSummary();
}
function redrawScheduleAuditWorkload() {
  const container = document.getElementById("scheduleAuditView-workload");
  if (!container || !scheduleAuditLastReport) return;
  const oldScroller = container.querySelector(".weekly-assignment-scroll");
  const left = oldScroller?.scrollLeft ?? 0;
  const top = oldScroller?.scrollTop ?? 0;
  const pageTop = window.scrollY;
  const pageLeft = window.scrollX;
  container.innerHTML = renderScheduleAuditWorkload(scheduleAuditLastReport.workload, scheduleAuditLastReport);
  const apply = () => {
    const scroller = container.querySelector(".weekly-assignment-scroll");
    if (scroller) {
      scroller.scrollLeft = left;
      scroller.scrollTop = top;
    }
    try {
      window.scrollTo({ top: pageTop, left: pageLeft, behavior: "instant" });
    } catch {
      window.scrollTo(pageLeft, pageTop);
    }
  };
  apply();
  requestAnimationFrame(apply);
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
    if (!response.ok || !data.ok) throw new Error(auditErrorMessage(data, response.status, "Không thể kiểm tra số tiết. Hãy thử lại."));
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
