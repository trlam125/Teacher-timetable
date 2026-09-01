'use strict';
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const operationHeaders=extra=>({'X-Skip-Operation-Status':'1',...(extra||{})});

let scheduleAuditSelectedFile=null;
let scheduleAuditRunId=0;
const SCHEDULE_AUDIT_MAX_BYTES=15*1024*1024;
const SCHEDULE_AUDIT_ALLOWED_EXTENSIONS=['xlsx','xlsm','xls','docx','csv','tsv'];

function scheduleAuditFileValidationError(file){
  if(!file)return 'Hãy chọn file thời khóa biểu trước khi kiểm tra.';
  if(file.size>SCHEDULE_AUDIT_MAX_BYTES)return 'File vượt quá giới hạn 15 MB.';
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  if(!SCHEDULE_AUDIT_ALLOWED_EXTENSIONS.includes(ext))return 'Định dạng chưa hỗ trợ. Dùng .xlsx, .xlsm, .xls, .docx, .csv hoặc .tsv.';
  return '';
}
function setScheduleAuditFile(file){
  scheduleAuditSelectedFile=file||null;
  const name=$('#scheduleAuditFileName'),drop=$('#scheduleAuditDropzone'),actions=$('#scheduleAuditFileActions'),button=$('#scheduleAuditButton');
  if(name)name.textContent=file?`${file.name} · ${(file.size/1024/1024).toFixed(file.size>=1024*1024?2:3)} MB`:'Chưa chọn file';
  if(drop){drop.classList.toggle('has-file',!!file);drop.setAttribute('aria-label',file?`${file.name} đã sẵn sàng. Bấm để chọn file khác.`:'Kéo thả file thời khóa biểu vào đây hoặc bấm để chọn file.');}
  if(actions)actions.hidden=!file;
  if(button&&!button.disabled)button.textContent=file?'Kiểm tra lại':'Kiểm tra thời khóa biểu';
}
function clearScheduleAuditFile(resetResult=true){
  scheduleAuditRunId+=1;
  const input=$('#scheduleAuditFile'),box=$('#scheduleAuditResult'),button=$('#scheduleAuditButton'),drop=$('#scheduleAuditDropzone');
  if(input)input.value='';
  setScheduleAuditFile(null);
  if(button){button.disabled=false;button.textContent='Kiểm tra thời khóa biểu';}
  if(drop)drop.classList.remove('is-analyzing','is-dragging');
  if(resetResult&&box)box.innerHTML='<div class="empty-state">Chọn một file thời khóa biểu để hiển thị và kiểm tra.</div>';
}
function selectScheduleAuditFile(file,{autoRun=true}={}){
  const error=scheduleAuditFileValidationError(file);
  if(error){clearScheduleAuditFile(false);renderScheduleAuditError(error);return false;}
  setScheduleAuditFile(file);
  if(autoRun)runScheduleAudit();
  return true;
}
function scheduleAuditConflictLabel(code){
  return ({teacher_collision:'Trùng giáo viên',class_collision:'Trùng lớp',room_collision:'Trùng phòng'})[code]||'Xung đột';
}
function scheduleAuditSlotParts(slot,viewer){
  const periods=Number(viewer.periods||1),sessions=Number(viewer.sessions||1),perDay=periods*sessions;
  const day=Math.floor(Number(slot)/perDay),inside=Number(slot)%perDay,session=Math.floor(inside/periods),period=(inside%periods)+1;
  return {day,session,period};
}
function scheduleAuditDayName(day){return ['Thứ 2','Thứ 3','Thứ 4','Thứ 5','Thứ 6','Thứ 7','CN'][day]||`Ngày ${day+1}`;}
function scheduleAuditSessionName(session,sessions){if(Number(sessions)<=1)return '';return session===0?'Sáng':session===1?'Chiều':`Buổi ${session+1}`;}
function scheduleAuditCellHtml(entries){
  if(!entries?.length)return '<td class="schedule-view-cell empty"></td>';
  const hasConflict=entries.some(item=>(item.conflicts||[]).length);
  const conflictCodes=[...new Set(entries.flatMap(item=>item.conflicts||[]))];
  const details=[...new Set(entries.flatMap(item=>item.conflict_details||[]))];
  const title=[...details,...entries.map(item=>item.source).filter(Boolean)].join('\n');
  return `<td class="schedule-view-cell${hasConflict?' conflict':''}"${title?` title="${esc(title)}"`:''}>${entries.map(item=>{
    const raw=item.raw_text||[item.subject_name,item.teacher_name].filter(Boolean).join(' ');
    return `<div class="schedule-view-lesson"><b>${esc(raw)}</b>${item.room?`<small>Phòng ${esc(item.room)}</small>`:''}</div>`;
  }).join('')}${hasConflict?`<div class="schedule-view-conflict-tags">${conflictCodes.map(code=>`<span>! ${esc(scheduleAuditConflictLabel(code))}</span>`).join('')}</div>`:''}</td>`;
}
function renderScheduleAuditTable(report){
  const viewer=report.viewer||{},classes=viewer.classes||[],cells=viewer.cells||[];
  if(!classes.length||!cells.length)return '<div class="empty-state">Không có đủ dữ liệu để dựng bảng thời khóa biểu.</div>';
  const byCoordinate=new Map();
  cells.forEach(item=>{const key=`${Number(item.slot)}:${Number(item.class_id)}`;if(!byCoordinate.has(key))byCoordinate.set(key,[]);byCoordinate.get(key).push(item);});
  const slots=[...new Set(cells.map(item=>Number(item.slot)))].sort((a,b)=>a-b);
  let previousDay=-1,previousSession=-1;
  let rows='';
  for(const slot of slots){
    const part=scheduleAuditSlotParts(slot,viewer),newDay=part.day!==previousDay,newSession=newDay||part.session!==previousSession;
    rows+=`<tr class="${newDay?'schedule-view-new-day ':''}${newSession?'schedule-view-new-session':''}">`;
    rows+=`<th class="schedule-view-meta day">${newDay?esc(scheduleAuditDayName(part.day)):''}</th>`;
    rows+=`<th class="schedule-view-meta session">${newSession?esc(scheduleAuditSessionName(part.session,viewer.sessions)):''}</th>`;
    rows+=`<th class="schedule-view-meta period">${part.period}</th>`;
    for(const cls of classes)rows+=scheduleAuditCellHtml(byCoordinate.get(`${slot}:${Number(cls.id)}`)||[]);
    rows+='</tr>';previousDay=part.day;previousSession=part.session;
  }
  return `<div class="schedule-view-table-wrap"><table class="schedule-view-table"><thead><tr><th class="schedule-view-meta day">Thứ</th><th class="schedule-view-meta session">Buổi</th><th class="schedule-view-meta period">Tiết</th>${classes.map(cls=>`<th class="schedule-view-class">${esc(cls.name)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function renderScheduleAudit(report){
  const box=$('#scheduleAuditResult');if(!box)return;
  const summary=report.summary||{},viewer=report.viewer||{},issues=report.issues||[];
  const collisionIssues=issues.filter(item=>['teacher_collision','class_collision','room_collision'].includes(item.code));
  const nonCellIssues=issues.filter(item=>!['teacher_collision','class_collision','room_collision'].includes(item.code));
  const conflicts=Number(summary.collisions||collisionIssues.length),affected=Number(viewer.conflict_cells||0);
  const hasConflict=conflicts>0;
  box.innerHTML=`
    <div class="schedule-audit-view-head ${hasConflict?'has-error':'clean'}">
      <div class="schedule-audit-view-summary">
        <span class="schedule-audit-status-icon">${hasConflict?'!':'✓'}</span>
        <div><h2>${hasConflict?`Phát hiện ${conflicts} xung đột trong thời khóa biểu`:'Không phát hiện ô bị trùng'}</h2><p>${esc(report.filename||'File')} · Đã đọc ${Number(summary.recognized_lessons||0)} tiết · ${Number(summary.classes||0)} lớp · ${Number(summary.teachers||0)} giáo viên.</p></div>
      </div>
      <div class="schedule-audit-view-legend"><span class="legend-conflict"></span><b>Ô đỏ = có xung đột</b>${hasConflict?`<small>${affected} ô bị ảnh hưởng</small>`:''}</div>
    </div>
    ${nonCellIssues.length?`<div class="schedule-audit-inline-warning">⚠ Có ${nonCellIssues.length} dữ liệu chưa thể biểu diễn chính xác trên bảng. Các lỗi trùng vẫn được đánh dấu trực tiếp bằng ô đỏ.</div>`:''}
    ${renderScheduleAuditTable(report)}`;
}
function renderScheduleAuditError(message){
  const box=$('#scheduleAuditResult');if(!box)return;
  box.innerHTML=`<div class="schedule-audit-report-head has-error"><div><span class="schedule-audit-status-icon">!</span></div><div><h2>Không thể kiểm tra file</h2><p>${esc(message||'Đã xảy ra lỗi khi đọc thời khóa biểu.')}</p></div></div>`;
}
async function runScheduleAudit(){
  const input=$('#scheduleAuditFile'),button=$('#scheduleAuditButton'),file=scheduleAuditSelectedFile||input?.files?.[0];
  const validationError=scheduleAuditFileValidationError(file);
  if(validationError){renderScheduleAuditError(validationError);return;}
  const runId=++scheduleAuditRunId,drop=$('#scheduleAuditDropzone');
  if(button){button.disabled=true;button.textContent='Đang phân tích…';}
  if(drop)drop.classList.add('is-analyzing');
  const box=$('#scheduleAuditResult');if(box)box.innerHTML='<div class="schedule-audit-loading"><span></span><b>Đang đọc file và dựng thời khóa biểu…</b></div>';
  try{
    const form=new FormData();form.append('file',file,file.name);
    const response=await fetch('/api/schedule-audit',{method:'POST',headers:operationHeaders(),body:form});
    let result={};try{result=await response.json();}catch{}
    if(runId!==scheduleAuditRunId)return;
    if(!response.ok||!result.ok){renderScheduleAuditError(result.message||`Máy chủ trả về lỗi ${response.status}.`);return;}
    renderScheduleAudit(result);
  }catch(error){
    if(runId===scheduleAuditRunId)renderScheduleAuditError(error?.message||'Không thể kết nối tới máy chủ để kiểm tra file.');
  }finally{
    if(runId===scheduleAuditRunId){if(button){button.disabled=false;button.textContent='Kiểm tra lại';}if(drop)drop.classList.remove('is-analyzing');}
  }
}

const scheduleAuditInput=$('#scheduleAuditFile'),scheduleAuditDropzone=$('#scheduleAuditDropzone');
if(scheduleAuditInput)scheduleAuditInput.addEventListener('change',()=>{const file=scheduleAuditInput.files?.[0]||null;if(file)selectScheduleAuditFile(file);});
if(scheduleAuditDropzone){
  let dragDepth=0;
  scheduleAuditDropzone.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();scheduleAuditInput?.click();}});
  scheduleAuditDropzone.addEventListener('dragenter',event=>{event.preventDefault();dragDepth+=1;scheduleAuditDropzone.classList.add('is-dragging');if(event.dataTransfer)event.dataTransfer.dropEffect='copy';});
  scheduleAuditDropzone.addEventListener('dragover',event=>{event.preventDefault();scheduleAuditDropzone.classList.add('is-dragging');if(event.dataTransfer)event.dataTransfer.dropEffect='copy';});
  scheduleAuditDropzone.addEventListener('dragleave',event=>{event.preventDefault();dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)scheduleAuditDropzone.classList.remove('is-dragging');});
  scheduleAuditDropzone.addEventListener('drop',event=>{event.preventDefault();dragDepth=0;scheduleAuditDropzone.classList.remove('is-dragging');const files=Array.from(event.dataTransfer?.files||[]);if(files.length>1){clearScheduleAuditFile(false);renderScheduleAuditError('Mỗi lần chỉ kiểm tra 1 file.');return;}const file=files[0];if(file)selectScheduleAuditFile(file);});
}
document.addEventListener('dragover',event=>{if(Array.from(event.dataTransfer?.types||[]).includes('Files'))event.preventDefault();});
document.addEventListener('drop',event=>{if(!Array.from(event.dataTransfer?.types||[]).includes('Files'))return;if(event.target?.closest?.('#scheduleAuditDropzone'))return;event.preventDefault();});
