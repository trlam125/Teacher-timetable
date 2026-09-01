'use strict';
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const operationHeaders=extra=>({'X-Skip-Operation-Status':'1',...(extra||{})});

let scheduleAuditSelectedFile=null;
let scheduleAuditRunId=0;
let scheduleAuditAiRunId=0;
let scheduleAuditLastReport=null;
let scheduleAuditAiAnalysis=null;
let scheduleAuditAiModel='';
const SCHEDULE_AUDIT_MAX_BYTES=15*1024*1024;
const SCHEDULE_AUDIT_ALLOWED_EXTENSIONS=['xlsx','xlsm','xls','docx','csv','tsv'];

function scheduleAuditAiIsEnabled(){return $('#scheduleAuditAiButton')?.dataset?.enabled==='1';}
function scheduleAuditFileValidationError(file){
  if(!file)return 'Hãy chọn file thời khóa biểu trước khi kiểm tra.';
  if(file.size>SCHEDULE_AUDIT_MAX_BYTES)return 'File vượt quá giới hạn 15 MB.';
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  if(!SCHEDULE_AUDIT_ALLOWED_EXTENSIONS.includes(ext))return 'Định dạng chưa hỗ trợ. Dùng .xlsx, .xlsm, .xls, .docx, .csv hoặc .tsv.';
  return '';
}
function setScheduleAuditFile(file){
  scheduleAuditSelectedFile=file||null;
  const name=$('#scheduleAuditFileName'),drop=$('#scheduleAuditDropzone'),actions=$('#scheduleAuditFileActions'),button=$('#scheduleAuditButton'),aiButton=$('#scheduleAuditAiButton');
  if(name)name.textContent=file?`${file.name} · ${(file.size/1024/1024).toFixed(file.size>=1024*1024?2:3)} MB`:'Chưa chọn file';
  if(drop){drop.classList.toggle('has-file',!!file);drop.setAttribute('aria-label',file?`${file.name} đã sẵn sàng. Bấm để chọn file khác.`:'Kéo thả file thời khóa biểu vào đây hoặc bấm để chọn file.');}
  if(actions)actions.hidden=!file;
  if(button&&!button.disabled)button.textContent=file?'Kiểm tra lại':'Kiểm tra thời khóa biểu';
  if(aiButton&&!aiButton.classList.contains('is-loading')){
    aiButton.disabled=!scheduleAuditAiIsEnabled();
    aiButton.textContent='✦ Phân tích bằng AI';
  }
}
function resetScheduleAuditAiResult(){
  scheduleAuditAiAnalysis=null;scheduleAuditAiModel='';
  const aiBox=$('#scheduleAuditAiResult');
  if(aiBox){aiBox.hidden=true;aiBox.innerHTML='';}
}
function clearScheduleAuditFile(resetResult=true){
  scheduleAuditRunId+=1;scheduleAuditAiRunId+=1;scheduleAuditLastReport=null;resetScheduleAuditAiResult();
  const input=$('#scheduleAuditFile'),box=$('#scheduleAuditResult'),button=$('#scheduleAuditButton'),aiButton=$('#scheduleAuditAiButton'),drop=$('#scheduleAuditDropzone');
  if(input)input.value='';
  setScheduleAuditFile(null);
  if(button){button.disabled=false;button.textContent='Kiểm tra thời khóa biểu';}
  if(aiButton){aiButton.classList.remove('is-loading');aiButton.disabled=!scheduleAuditAiIsEnabled();aiButton.textContent='✦ Phân tích bằng AI';}
  if(drop)drop.classList.remove('is-analyzing','is-dragging');
  if(resetResult&&box)box.innerHTML='<div class="empty-state">Chọn một file thời khóa biểu để hiển thị và kiểm tra.</div>';
}
function selectScheduleAuditFile(file,{autoRun=true}={}){
  const error=scheduleAuditFileValidationError(file);
  if(error){clearScheduleAuditFile(false);renderScheduleAuditError(error);return false;}
  scheduleAuditAiRunId+=1;scheduleAuditLastReport=null;resetScheduleAuditAiResult();
  setScheduleAuditFile(file);
  if(autoRun)runScheduleAudit();
  return true;
}
function scheduleAuditConflictLabel(code){
  return ({teacher_collision:'Trùng giáo viên',class_collision:'Trùng lớp',room_collision:'Trùng phòng'})[code]||'Xung đột';
}
function scheduleAuditAiSeverityLabel(severity){return severity==='warning'?'AI cảnh báo':'AI gợi ý';}
function scheduleAuditAiCategoryLabel(category){
  return ({distribution:'Phân bố lịch',teacher_load:'Tải giáo viên',consecutive:'Tiết liên tiếp',parser_suspicion:'Cần kiểm tra cách đọc ô',other:'Khác'})[category]||'Khác';
}
function scheduleAuditSlotParts(slot,viewer){
  const periods=Number(viewer.periods||1),sessions=Number(viewer.sessions||1),perDay=periods*sessions;
  const day=Math.floor(Number(slot)/perDay),inside=Number(slot)%perDay,session=Math.floor(inside/periods),period=(inside%periods)+1;
  return {day,session,period};
}
function scheduleAuditDayName(day){return ['Thứ 2','Thứ 3','Thứ 4','Thứ 5','Thứ 6','Thứ 7','CN'][day]||`Ngày ${day+1}`;}
function scheduleAuditSessionName(session,sessions){if(Number(sessions)<=1)return '';return session===0?'Sáng':session===1?'Chiều':`Buổi ${session+1}`;}
function scheduleAuditAiMap(ai){
  const map=new Map();
  for(const issue of ai?.issues||[]){
    for(const key of issue.cell_keys||[]){if(!map.has(key))map.set(key,[]);map.get(key).push(issue);}
  }
  return map;
}
function scheduleAuditCellHtml(entries,aiIssues=[]){
  if(!entries?.length)return '<td class="schedule-view-cell empty"></td>';
  const hasConflict=entries.some(item=>(item.conflicts||[]).length);
  const hasAiWarning=aiIssues.some(item=>item.severity==='warning');
  const hasAiSuggestion=aiIssues.length>0&&!hasAiWarning;
  const conflictCodes=[...new Set(entries.flatMap(item=>item.conflicts||[]))];
  const details=[...new Set(entries.flatMap(item=>item.conflict_details||[]))];
  const aiDetails=aiIssues.map(item=>`AI: ${item.title}${item.message?` — ${item.message}`:''}`);
  const title=[...details,...aiDetails,...entries.map(item=>item.source).filter(Boolean)].join('\n');
  const stateClass=hasConflict?' conflict':hasAiWarning?' ai-warning':hasAiSuggestion?' ai-suggestion':'';
  return `<td class="schedule-view-cell${stateClass}"${title?` title="${esc(title)}"`:''}>${entries.map(item=>{
    const raw=item.raw_text||[item.subject_name,item.teacher_name].filter(Boolean).join(' ');
    return `<div class="schedule-view-lesson"><b>${esc(raw)}</b>${item.room?`<small>Phòng ${esc(item.room)}</small>`:''}</div>`;
  }).join('')}${hasConflict?`<div class="schedule-view-conflict-tags">${conflictCodes.map(code=>`<span>! ${esc(scheduleAuditConflictLabel(code))}</span>`).join('')}</div>`:''}${aiIssues.length?`<div class="schedule-view-ai-tags"><span class="${hasAiWarning?'warning':'suggestion'}">✦ ${esc(scheduleAuditAiSeverityLabel(hasAiWarning?'warning':'suggestion'))}</span></div>`:''}</td>`;
}
function renderScheduleAuditTable(report,ai=null){
  const viewer=report.viewer||{},classes=viewer.classes||[],cells=viewer.cells||[];
  if(!classes.length||!cells.length)return '<div class="empty-state">Không có đủ dữ liệu để dựng bảng thời khóa biểu.</div>';
  const byCoordinate=new Map(),aiMap=scheduleAuditAiMap(ai);
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
    for(const cls of classes){const key=`${slot}:${Number(cls.id)}`;rows+=scheduleAuditCellHtml(byCoordinate.get(key)||[],aiMap.get(key)||[]);}
    rows+='</tr>';previousDay=part.day;previousSession=part.session;
  }
  return `<div class="schedule-view-table-wrap"><table class="schedule-view-table"><thead><tr><th class="schedule-view-meta day">Thứ</th><th class="schedule-view-meta session">Buổi</th><th class="schedule-view-meta period">Tiết</th>${classes.map(cls=>`<th class="schedule-view-class">${esc(cls.name)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function renderScheduleAudit(report,ai=scheduleAuditAiAnalysis){
  const box=$('#scheduleAuditResult');if(!box)return;
  const summary=report.summary||{},viewer=report.viewer||{},issues=report.issues||[];
  const collisionIssues=issues.filter(item=>['teacher_collision','class_collision','room_collision'].includes(item.code));
  const nonCellIssues=issues.filter(item=>!['teacher_collision','class_collision','room_collision'].includes(item.code));
  const conflicts=Number(summary.collisions||collisionIssues.length),affected=Number(viewer.conflict_cells||0);
  const hasConflict=conflicts>0,aiMarked=Number(ai?.summary?.marked_cells||0);
  box.innerHTML=`
    <div class="schedule-audit-view-head ${hasConflict?'has-error':'clean'}">
      <div class="schedule-audit-view-summary">
        <span class="schedule-audit-status-icon">${hasConflict?'!':'✓'}</span>
        <div><h2>${hasConflict?`Phát hiện ${conflicts} xung đột trong thời khóa biểu`:'Không phát hiện ô bị trùng'}</h2><p>${esc(report.filename||'File')} · Đã đọc ${Number(summary.recognized_lessons||0)} tiết · ${Number(summary.classes||0)} lớp · ${Number(summary.teachers||0)} giáo viên.</p></div>
      </div>
      <div class="schedule-audit-view-legend"><span class="legend-conflict"></span><b>Đỏ = lỗi rule</b>${hasConflict?`<small>${affected} ô</small>`:''}${ai?`<span class="legend-ai-warning"></span><b>Cam/vàng = AI</b><small>${aiMarked} ô</small>`:''}</div>
    </div>
    ${nonCellIssues.length?`<div class="schedule-audit-inline-warning">⚠ Có ${nonCellIssues.length} dữ liệu chưa thể biểu diễn chính xác trên bảng. Các lỗi trùng vẫn được đánh dấu trực tiếp bằng ô đỏ.</div>`:''}
    ${renderScheduleAuditTable(report,ai)}`;
}
function renderScheduleAuditError(message){
  const box=$('#scheduleAuditResult');if(!box)return;
  box.innerHTML=`<div class="schedule-audit-report-head has-error"><div><span class="schedule-audit-status-icon">!</span></div><div><h2>Không thể kiểm tra file</h2><p>${esc(message||'Đã xảy ra lỗi khi đọc thời khóa biểu.')}</p></div></div>`;
}
function scheduleAuditCellLocation(cellKey,report){
  const [slotRaw,classRaw]=String(cellKey||'').split(':'),slot=Number(slotRaw),classId=Number(classRaw),viewer=report?.viewer||{};
  if(!Number.isFinite(slot)||!Number.isFinite(classId))return '';
  const cls=(viewer.classes||[]).find(item=>Number(item.id)===classId),part=scheduleAuditSlotParts(slot,viewer),session=scheduleAuditSessionName(part.session,viewer.sessions);
  return [scheduleAuditDayName(part.day),session,`Tiết ${part.period}`,cls?.name||`Lớp ${classId}`].filter(Boolean).join(' · ');
}
function renderScheduleAuditAiLoading(){
  const box=$('#scheduleAuditAiResult');if(!box)return;
  box.hidden=false;
  box.innerHTML='<div class="schedule-audit-ai-loading"><span></span><div><b>AI đang phân tích thời khóa biểu…</b><small>Rule thường vẫn giữ nguyên; AI chỉ bổ sung nhận xét.</small></div></div>';
}
function renderScheduleAuditAiError(message){
  const box=$('#scheduleAuditAiResult');if(!box)return;
  box.hidden=false;
  box.innerHTML=`<div class="schedule-audit-ai-head error"><div><span class="schedule-audit-ai-icon">!</span></div><div><h2>AI chưa thể phân tích</h2><p>${esc(message||'Không thể kết nối tới AI.')}</p><small>Phần kiểm tra rule thường phía dưới vẫn sử dụng bình thường.</small></div></div>`;
}
function renderScheduleAuditAiResult(report,ai,model){
  const box=$('#scheduleAuditAiResult');if(!box)return;
  const issues=ai?.issues||[],summary=ai?.summary||{},hasWarnings=Number(summary.warnings||0)>0;
  box.hidden=false;
  box.innerHTML=`
    <div class="schedule-audit-ai-head ${issues.length?'has-findings':'clean'}">
      <div><span class="schedule-audit-ai-icon">✦</span></div>
      <div class="schedule-audit-ai-copy"><div class="schedule-audit-ai-title-row"><h2>Phân tích bằng AI</h2>${model?`<span>${esc(model)}</span>`:''}</div><p>${esc(ai?.overview||'Đã phân tích thời khóa biểu.')}</p><small>AI là lớp kiểm tra bổ sung theo heuristic; lỗi rule cứng vẫn được ưu tiên.</small></div>
      <div class="schedule-audit-ai-counts"><b>${Number(summary.total||issues.length)}</b><span>điểm cần xem</span>${hasWarnings?`<small>${Number(summary.warnings||0)} cảnh báo</small>`:''}</div>
    </div>
    ${issues.length?`<div class="schedule-audit-ai-issues">${issues.map(issue=>{
      const locations=(issue.cell_keys||[]).map(key=>scheduleAuditCellLocation(key,report)).filter(Boolean);
      return `<article class="schedule-audit-ai-issue ${issue.severity==='warning'?'warning':'suggestion'}"><div class="schedule-audit-ai-issue-mark">${issue.severity==='warning'?'!':'✦'}</div><div><div class="schedule-audit-ai-issue-title"><b>${esc(issue.title||'Cần xem lại')}</b><span>${esc(scheduleAuditAiCategoryLabel(issue.category))}</span></div>${issue.message?`<p>${esc(issue.message)}</p>`:''}${issue.suggestion?`<small><b>Gợi ý:</b> ${esc(issue.suggestion)}</small>`:''}${locations.length?`<div class="schedule-audit-ai-locations">${locations.map(location=>`<span>${esc(location)}</span>`).join('')}</div>`:'<div class="schedule-audit-ai-global">Nhận xét toàn cục</div>'}</div></article>`;
    }).join('')}</div>`:'<div class="schedule-audit-ai-empty">✓ AI không phát hiện bất thường đáng chú ý ngoài các kiểm tra rule hiện có.</div>'}`;
}
async function runScheduleAudit(){
  const input=$('#scheduleAuditFile'),button=$('#scheduleAuditButton'),file=scheduleAuditSelectedFile||input?.files?.[0];
  const validationError=scheduleAuditFileValidationError(file);
  if(validationError){renderScheduleAuditError(validationError);return;}
  scheduleAuditAiRunId+=1;resetScheduleAuditAiResult();
  const runId=++scheduleAuditRunId,drop=$('#scheduleAuditDropzone');
  if(button){button.disabled=true;button.textContent='Đang phân tích…';}
  if(drop)drop.classList.add('is-analyzing');
  const box=$('#scheduleAuditResult');if(box)box.innerHTML='<div class="schedule-audit-loading"><span></span><b>Đang đọc file và dựng thời khóa biểu…</b></div>';
  try{
    const form=new FormData();form.append('file',file,file.name);
    const response=await fetch('/api/schedule-audit',{method:'POST',headers:operationHeaders(),body:form});
    let result={};try{result=await response.json();}catch{}
    if(runId!==scheduleAuditRunId)return;
    if(!response.ok||!result.ok){scheduleAuditLastReport=null;renderScheduleAuditError(result.message||`Máy chủ trả về lỗi ${response.status}.`);return;}
    scheduleAuditLastReport=result;
    renderScheduleAudit(result,null);
  }catch(error){
    if(runId===scheduleAuditRunId){scheduleAuditLastReport=null;renderScheduleAuditError(error?.message||'Không thể kết nối tới máy chủ để kiểm tra file.');}
  }finally{
    if(runId===scheduleAuditRunId){if(button){button.disabled=false;button.textContent='Kiểm tra lại';}if(drop)drop.classList.remove('is-analyzing');}
  }
}
async function runScheduleAuditAI(){
  const input=$('#scheduleAuditFile'),button=$('#scheduleAuditAiButton'),file=scheduleAuditSelectedFile||input?.files?.[0];
  const validationError=scheduleAuditFileValidationError(file);
  if(validationError){renderScheduleAuditAiError(validationError);return;}
  if(!scheduleAuditAiIsEnabled()){renderScheduleAuditAiError('Máy chủ chưa cấu hình GEMINI_API_KEY cho chức năng AI.');return;}
  const runId=++scheduleAuditAiRunId;
  if(button){button.disabled=true;button.classList.add('is-loading');button.textContent='✦ AI đang phân tích…';}
  renderScheduleAuditAiLoading();
  try{
    const form=new FormData();form.append('file',file,file.name);
    const response=await fetch('/api/schedule-audit/ai',{method:'POST',headers:operationHeaders(),body:form});
    let result={};try{result=await response.json();}catch{}
    if(runId!==scheduleAuditAiRunId)return;
    if(!response.ok||!result.ok){renderScheduleAuditAiError(result.message||`AI trả về lỗi ${response.status}.`);return;}
    scheduleAuditLastReport=result.report||scheduleAuditLastReport;
    scheduleAuditAiAnalysis=result.ai||{overview:'',issues:[],summary:{}};
    scheduleAuditAiModel=result.model||'';
    if(scheduleAuditLastReport)renderScheduleAudit(scheduleAuditLastReport,scheduleAuditAiAnalysis);
    renderScheduleAuditAiResult(scheduleAuditLastReport,scheduleAuditAiAnalysis,scheduleAuditAiModel);
  }catch(error){
    if(runId===scheduleAuditAiRunId)renderScheduleAuditAiError(error?.message||'Không thể kết nối tới AI để phân tích thời khóa biểu.');
  }finally{
    if(runId===scheduleAuditAiRunId&&button){button.disabled=false;button.classList.remove('is-loading');button.textContent='✦ Phân tích lại bằng AI';}
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
