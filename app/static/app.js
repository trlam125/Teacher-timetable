const nativeFetch = window.fetch.bind(window); window.fetch = async (...args) => { const response = await nativeFetch(...args); if (response.status === 401) { location.href = '/login'; throw new Error('Phiên đăng nhập đã hết hạn') } return response };
document.head.insertAdjacentHTML('beforeend', `<style>
.global-session-locks{background:var(--card-bg);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:20px}
.global-session-locks h2{margin:0 0 5px;font-size:19px;color:var(--ink)}.global-session-locks p{margin:0 0 14px;color:var(--muted)}
.session-lock-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin-bottom:14px}
.session-lock{border:1px solid var(--line);background:var(--card-bg);color:var(--ink);border-radius:10px;padding:12px;cursor:pointer;text-align:left}
.session-lock b{display:block;color:var(--ink)}.session-lock span{display:block;font-size:13px;color:var(--muted);margin-top:3px}
.session-lock.is-locked{border-color:#fca5a5;background:#fef2f2;color:#b91c1c}
:root.dark-mode .session-lock.is-locked{border-color:#ef4444;background:rgba(239,68,68,.15);color:#fca5a5}
.session-lock.is-locked span{color:inherit}
:root.dark-mode .session-lock.is-locked span{color:#fca5a5}
.global-slot-lock-title{margin-top:18px}.global-slot-lock-title h3{margin:0 0 4px;color:var(--ink)}.global-slot-lock-title p{margin-bottom:12px;color:var(--muted)}
.global-slot-lock-grid{display:grid;border:1px solid var(--line);border-radius:12px;overflow:auto;margin-bottom:14px}
.global-slot-lock-grid .slot-head,.global-slot-lock-grid .slot-period{background:var(--bg);color:var(--ink);font-weight:700;display:grid;place-items:center;min-height:44px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
.global-slot-lock{border:0;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--card-bg);min-height:48px;cursor:pointer;color:var(--muted)}
.global-slot-lock.is-locked{background:#fef2f2;color:#b91c1c;font-weight:800;box-shadow:inset 0 0 0 2px #fca5a5}
:root.dark-mode .global-slot-lock.is-locked{background:rgba(239,68,68,.15);color:#fca5a5;box-shadow:inset 0 0 0 2px #ef4444}
.global-locked-slot{background:repeating-linear-gradient(135deg,#fff7ed,#fff7ed 8px,#ffedd5 8px,#ffedd5 16px)!important}
:root.dark-mode .global-locked-slot{background:repeating-linear-gradient(135deg,#181c24,#181c24 9px,#1e2430 9px,#1e2430 18px)!important}
.global-lock-label{display:block;color:#c2410c;font-size:11px;font-weight:800;text-align:center;margin-bottom:4px}
:root.dark-mode .global-lock-label{color:#f97316}
.block-mode-help{display:block;margin-top:7px;color:var(--muted);line-height:1.45}.block-mode-preview{margin-top:10px;padding:10px 12px;border-radius:10px;background:var(--bg);border:1px solid var(--line);color:var(--ink);font-size:13px}
.schedule-color-legend{display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin:0 0 12px;padding:11px 14px;background:var(--card-bg);border:1px solid var(--line);border-radius:10px;color:var(--muted);font-size:13px}.schedule-color-legend b{color:var(--ink)}.schedule-color-legend span{display:inline-flex;align-items:center;gap:7px}.schedule-color-swatch{width:18px;height:18px;border-radius:5px;border:1px solid #93c5fd;background:#dbeafe}
:root.dark-mode .schedule-color-swatch{border-color:#2563eb;background:#1e3a8a}
.schedule-color-swatch.cluster{border-color:#4ade80;background:#dcfce7}
:root.dark-mode .schedule-color-swatch.cluster{border-color:#10b981;background:#064e3b}
.lesson.lesson-cluster{border-color:#4ade80;background:#dcfce7}.lesson.lesson-cluster b{color:#166534}.lesson.lesson-cluster small{color:#3f6212}
.assignment-bulk-modal{width:min(900px,88vw);max-height:78vh;overflow:auto}
.assignment-bulk-intro{margin:0 0 12px;color:var(--muted)}
.assignment-bulk-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:14px 0}
.assignment-pick-panel{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card-bg)}
.assignment-pick-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 12px;background:var(--bg);border-bottom:1px solid var(--line)}
.assignment-pick-head b{color:var(--ink)}
.assignment-pick-actions{display:flex;gap:6px}.assignment-pick-actions button{border:0;background:transparent;color:var(--primary);cursor:pointer;font-weight:700;font-size:12px;padding:3px}
.assignment-pick-list{max-height:260px;overflow:auto}
.assignment-pick-row{display:flex!important;align-items:center;gap:9px;padding:10px 12px!important;margin:0!important;border-bottom:1px solid var(--line);font-weight:500!important;cursor:pointer}
.assignment-pick-row:last-child{border-bottom:0}.assignment-pick-row:hover{background:var(--bg)}
.assignment-pick-row input{width:17px!important;height:17px!important;margin:0!important;flex:0 0 auto}
.assignment-pick-row span{flex:1}.assignment-pick-row small{font-size:11px;color:var(--primary);background:var(--soft);padding:3px 6px;border-radius:999px}
.assignment-bulk-settings{display:grid;grid-template-columns:minmax(150px,.7fr) minmax(280px,1.3fr);gap:12px;align-items:start}
.assignment-bulk-preview{margin:12px 0 0;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font-size:13px}
.assignment-bulk-empty{padding:18px;text-align:center;color:var(--muted)}
.teacher-subject-picker{margin-top:12px;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card-bg)}
.teacher-subject-picker .assignment-pick-list{max-height:220px}.teacher-subject-help{margin:7px 0 0;color:var(--muted);font-size:12px}
.assignment-subject-item{border-bottom:1px solid var(--line)}.assignment-subject-item:last-child{border-bottom:0}
.assignment-subject-item .assignment-pick-row{border-bottom:0!important}
.assignment-subject-config{display:grid;grid-template-columns:130px minmax(180px,1fr);gap:10px;padding:0 12px 12px 38px;background:var(--bg)}
.assignment-subject-config[hidden]{display:none!important}.assignment-subject-config label{margin:0!important;font-size:12px}
.assignment-subject-config input,.assignment-subject-config select{margin-top:4px!important}
.assignment-subject-config .block-mode-preview{grid-column:1/-1;margin:0}
.assignment-warning{display:block;margin-top:6px;color:#b91c1c;font-weight:700}.assignment-ok{display:block;margin-top:6px;color:#15803d;font-weight:700}
.assignment-filter-panel{display:grid;grid-template-columns:minmax(170px,1fr) minmax(170px,1fr) minmax(190px,1.2fr) minmax(210px,1.25fr) auto;gap:10px;align-items:end;margin:16px 0 12px;padding:14px;border:1px solid var(--line);border-radius:14px;background:var(--card-bg)}
.assignment-filter-panel label{margin:0!important;font-size:12px;color:var(--muted);font-weight:700}.assignment-filter-panel select{margin-top:6px!important;width:100%}
.assignment-filter-summary{margin:0 0 12px;padding:11px 14px;border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--muted);line-height:1.5}.assignment-filter-summary b{color:var(--ink)}
.assignment-filter-summary.has-gap{border-color:#f59e0b;background:#fffbeb;color:#92400e}:root.dark-mode .assignment-filter-summary.has-gap{background:rgba(245,158,11,.12);border-color:#b45309;color:#fcd34d}.assignment-filter-summary.has-gap b{color:inherit}
.assignment-gap-badge{display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;background:#fff7ed;color:#c2410c;font-size:12px;font-weight:800}:root.dark-mode .assignment-gap-badge{background:rgba(234,88,12,.16);color:#fdba74}
.assignment-filter-empty{padding:22px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:12px;background:var(--card-bg)}
@media(max-width:1050px){.assignment-filter-panel{grid-template-columns:repeat(2,minmax(0,1fr))}.assignment-filter-panel .assignment-filter-reset{grid-column:1/-1}}
@media(max-width:620px){.assignment-filter-panel{grid-template-columns:1fr}}
@media(max-width:720px){.assignment-bulk-grid,.assignment-bulk-settings,.assignment-subject-config{grid-template-columns:1fr}.assignment-subject-config{padding-left:12px}.assignment-bulk-modal{width:min(94vw,900px)}}
</style>`);
let data = window.INIT_DATA; let entityType = ''; let entityId = null; let pendingAssignmentGap = null; const $ = s => document.querySelector(s); const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
function confirmAction(message, options) { return window.OperationStatus?.confirm(message, options) ?? Promise.resolve(false) }
function beginTrackedOperation(message) { window.OperationStatus?.begin(message); let finished = false; return () => { if (finished) return; finished = true; window.OperationStatus?.finish() } }
function operationHeaders(headers = {}) { return { ...headers, 'X-Skip-Operation-Status': '1' } }
const actionStateTimers = new WeakMap();
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function actionStateMarkup(state, label) {
  if (state === 'loading') return `<svg class="inline-action-icon inline-action-spinner" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.9-4"></path><polyline points="5 3 5 7 9 7"></polyline><path d="M4 13a8 8 0 0 0 14.9 4"></path><polyline points="19 21 19 17 15 17"></polyline></svg><span>${esc(label)}</span>`;
  if (state === 'success') return `<svg class="inline-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg><span>${esc(label)}</span>`;
  if (state === 'error') return `<svg class="inline-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5"></path><path d="M12 17h.01"></path><circle cx="12" cy="12" r="9"></circle></svg><span>${esc(label)}</span>`;
  return `<span>${esc(label)}</span>`;
}
function ensureInlineActionButton(button) {
  if (!button) return null;
  button.classList.add('inline-action-btn');
  let stage = button.querySelector(':scope > .inline-action-stage');
  if (stage) return stage;
  const idle = (button.textContent || '').trim() || 'Thực hiện';
  button.dataset.actionIdleLabel = button.dataset.actionIdleLabel || idle;
  button.textContent = '';
  stage = document.createElement('span'); stage.className = 'inline-action-stage';
  const content = document.createElement('span'); content.className = 'inline-action-content'; content.textContent = idle;
  stage.appendChild(content); button.appendChild(stage); return stage;
}
function setInlineActionState(button, state, labels = {}, resetAfter = 0) {
  const stage = ensureInlineActionButton(button); if (!stage) return;
  const previousTimer = actionStateTimers.get(button); if (previousTimer) clearTimeout(previousTimer);
  const idle = labels.idle || button.dataset.actionIdleLabel || 'Thực hiện';
  const defaults = { loading: 'Đang xử lý...', success: 'Đã hoàn tất', error: 'Chưa hoàn tất' };
  const label = state === 'idle' ? idle : (labels[state] || defaults[state] || idle);
  stage.querySelectorAll('.inline-action-content.inline-action-leaving').forEach(node => node.remove());
  const current = stage.querySelector('.inline-action-content');
  const next = document.createElement('span'); next.className = `inline-action-content inline-action-enter inline-action-${state}`; next.innerHTML = actionStateMarkup(state, label);
  if (current) { current.classList.add('inline-action-leaving'); const cleanup = () => current.remove(); current.addEventListener('animationend', cleanup, { once: true }); setTimeout(cleanup, 360) }
  stage.appendChild(next); button.dataset.actionState = state; button.disabled = state === 'loading'; button.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
  if (resetAfter > 0) { const timer = setTimeout(() => setInlineActionState(button, 'idle', { idle }), resetAfter); actionStateTimers.set(button, timer) }
}
function showInlineActionFeedback(button, message, kind = 'info', timeout = 4200) {
  if (!button) return;
  let feedback = button.parentElement?.querySelector(':scope > .inline-action-feedback');
  if (!message) { if (feedback) feedback.hidden = true; return }
  if (!feedback) { feedback = document.createElement('span'); feedback.className = 'inline-action-feedback'; button.insertAdjacentElement('afterend', feedback) }
  feedback.className = `inline-action-feedback is-${kind}`; feedback.textContent = String(message); feedback.hidden = false;
  if (timeout > 0) setTimeout(() => { if (feedback.isConnected) feedback.hidden = true }, timeout);
}
function setScheduleFeedback(message, kind = 'info', timeout = 4200) { document.querySelectorAll('[data-schedule-action]').forEach(button => showInlineActionFeedback(button, message, kind, timeout)) }
function setTrayActionStatus(state, message, resetAfter = 0) {
  const panel = $('.manual-tray-panel'); if (!panel) return;
  let status = $('#trayActionStatus'); if (!status) { status = document.createElement('div'); status.id = 'trayActionStatus'; status.className = 'tray-action-status'; panel.querySelector('.manual-tray-head')?.insertAdjacentElement('afterend', status) }
  status.hidden = false; status.className = `tray-action-status is-${state}`;
  status.innerHTML = state === 'loading' ? `<span class="tray-status-spinner" aria-hidden="true"></span><span>${esc(message)}</span>` : `<span aria-hidden="true">${state === 'success' ? '✓' : '!'}</span><span>${esc(message)}</span>`;
  if (resetAfter > 0) setTimeout(() => { if (status.isConnected) status.hidden = true }, resetAfter);
}
function setEntityActionMessage(message, kind = 'error') {
  const form = entityModal?.querySelector('form'); if (!form) return;
  let node = form.querySelector('#entityActionMessage'); if (!node) { node = document.createElement('p'); node.id = 'entityActionMessage'; node.className = 'inline-form-message'; form.querySelector('.row.end')?.insertAdjacentElement('beforebegin', node) }
  if (!message) { node.hidden = true; node.textContent = ''; return } node.hidden = false; node.className = `inline-form-message is-${kind}`; node.textContent = String(message);
}
function entityActionError(button, message) { setInlineActionState(button, 'error', { idle: 'Lưu', error: 'Kiểm tra lại' }, 1800); setEntityActionMessage(message, 'error') }
let scheduleActionTimer = null; let scheduleActionVersion = 0;
function scheduleActionMarkup(state) {
  if (state === 'loading') return `<svg class="schedule-action-icon schedule-action-spinner" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.9-4"></path><polyline points="5 3 5 7 9 7"></polyline><path d="M4 13a8 8 0 0 0 14.9 4"></path><polyline points="19 21 19 17 15 17"></polyline></svg><span>Đang xếp...</span>`;
  if (state === 'success') return `<svg class="schedule-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg><span>Đã xếp xong</span>`;
  if (state === 'error') return `<svg class="schedule-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5"></path><path d="M12 17h.01"></path><circle cx="12" cy="12" r="9"></circle></svg><span>Chưa xếp được</span>`;
  return '<span>Xếp tự động</span>';
}
function setScheduleActionState(state, resetAfter = 0) {
  scheduleActionVersion += 1; const version = scheduleActionVersion;
  if (scheduleActionTimer) { clearTimeout(scheduleActionTimer); scheduleActionTimer = null }
  document.querySelectorAll('[data-schedule-action]').forEach(button => {
    const stage = button.querySelector('.schedule-action-stage'); if (!stage) return;
    stage.querySelectorAll('.schedule-action-content.schedule-action-leaving').forEach(node => node.remove());
    const current = stage.querySelector('.schedule-action-content');
    const next = document.createElement('span'); next.className = `schedule-action-content schedule-action-enter schedule-action-${state}`; next.innerHTML = scheduleActionMarkup(state);
    if (current) { current.classList.add('schedule-action-leaving'); const cleanup = () => current.remove(); current.addEventListener('animationend', cleanup, { once: true }); setTimeout(cleanup, 360) }
    stage.appendChild(next); button.dataset.scheduleState = state; button.disabled = state === 'loading'; button.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
  });
  if (resetAfter > 0) scheduleActionTimer = setTimeout(() => { if (version === scheduleActionVersion) setScheduleActionState('idle') }, resetAfter);
}
function launchConfetti() { const canvas = document.createElement('canvas'); canvas.style.position = 'fixed'; canvas.style.inset = '0'; canvas.style.width = '100vw'; canvas.style.height = '100vh'; canvas.style.pointerEvents = 'none'; canvas.style.zIndex = '999'; document.body.appendChild(canvas); const ctx = canvas.getContext('2d'); let width = canvas.width = window.innerWidth; let height = canvas.height = window.innerHeight; window.addEventListener('resize', () => { width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight }); const colors = ['#2563eb', '#06b6d4', '#10b981', '#f5b83d', '#ec4899', '#8b5cf6']; const particles = []; for (let i = 0; i < 120; i++) { particles.push({ x: Math.random() * width, y: Math.random() * height - height, r: Math.random() * 6 + 4, d: Math.random() * width, color: colors[Math.floor(Math.random() * colors.length)], tilt: Math.random() * 10 - 5, tiltAngleIncremental: Math.random() * 0.07 + 0.02, tiltAngle: 0, velocity: Math.random() * 3 + 2 }) } let animationFrameId; let start = Date.now(); function draw() { ctx.clearRect(0, 0, width, height); let active = false; for (let i = 0; i < particles.length; i++) { const p = particles[i]; p.tiltAngle += p.tiltAngleIncremental; p.y += (Math.cos(p.d) + 3 + p.r / 2) / 2 * p.velocity * 0.7; p.x += Math.sin(p.tiltAngle) * 0.5; if (p.y < height) { active = true } ctx.beginPath(); ctx.lineWidth = p.r; ctx.strokeStyle = p.color; ctx.moveTo(p.x + p.r / 2 + p.tilt, p.y); ctx.lineTo(p.x + p.tilt, p.y + p.tilt + p.r / 2); ctx.stroke() } if (active && Date.now() - start < 3500) { animationFrameId = requestAnimationFrame(draw) } else { cancelAnimationFrame(animationFrameId); canvas.remove() } } draw() }
function captureRefreshScrollState() { const root = document.scrollingElement || document.documentElement, table = document.querySelector('#scheduleGrid .timetable'), content = document.querySelector('.workspace .content'); return { pageTop: root?.scrollTop ?? window.scrollY ?? 0, pageLeft: root?.scrollLeft ?? window.scrollX ?? 0, tableTop: table?.scrollTop ?? null, tableLeft: table?.scrollLeft ?? null, contentTop: content?.scrollTop ?? null, contentLeft: content?.scrollLeft ?? null } }
function restoreRefreshScrollState(state) { if (!state) return; const table = document.querySelector('#scheduleGrid .timetable'), content = document.querySelector('.workspace .content'); if (table && state.tableTop != null) { table.scrollTop = state.tableTop; table.scrollLeft = state.tableLeft || 0 } if (content && state.contentTop != null) { content.scrollTop = state.contentTop; content.scrollLeft = state.contentLeft || 0 } const root = document.scrollingElement || document.documentElement; if (root) { root.scrollTop = state.pageTop || 0; root.scrollLeft = state.pageLeft || 0 } else if (typeof window.scrollTo === 'function') window.scrollTo(state.pageLeft || 0, state.pageTop || 0) }
async function refresh(skipOperationStatus = false) { const scrollState = captureRefreshScrollState(), init = skipOperationStatus ? { headers: operationHeaders() } : undefined; const r = await fetch(`/api/projects/${PROJECT_ID}/data`, init); const result = await r.json().catch(() => null); if (!r.ok) { const error = new Error(result?.message || result?.detail || 'Không thể tải lại dữ liệu từ máy chủ.'); error.isRefreshError = true; throw error } if (!result || typeof result !== 'object' || Array.isArray(result)) { const error = new Error('Dữ liệu trả về từ máy chủ không hợp lệ.'); error.isRefreshError = true; throw error } data = result; renderAll(); restoreRefreshScrollState(scrollState); requestAnimationFrame(() => restoreRefreshScrollState(scrollState)); return data }
function activateWorkspaceTab(tabName) { const b = document.querySelector(`.nav[data-tab="${tabName}"]`); if (!b) return false; document.querySelectorAll('.nav,.tab').forEach(x => x.classList.remove('active')); b.classList.add('active'); const t = $('#' + b.dataset.tab); if (t) t.classList.add('active'); if (b.dataset.tab === 'schedule') renderSchedule(); if (b.dataset.tab === 'constraints') renderConstraintSelectors(); if (b.dataset.tab === 'preferences') loadPreferenceInbox(); return true }
document.querySelectorAll('.nav').forEach(b => b.onclick = () => activateWorkspaceTab(b.dataset.tab));
function activateRequestedWorkspaceTab() { const tab = new URLSearchParams(window.location.search).get('tab'); if (tab) activateWorkspaceTab(tab) }
function table(rows, cols, type) { if (!rows.length) return '<div class="empty-state">Chưa có dữ liệu.</div>'; const canEdit = ['subject', 'teacher', 'grade', 'class'].includes(type); return `<table class="data-table"><thead><tr>${cols.map(c => `<th>${c[0]}</th>`).join('')}<th></th></tr></thead><tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${esc(typeof c[1] === 'function' ? c[1](r) : r[c[1]])}</td>`).join('')}<td><div class="row end">${canEdit ? `<button class="danger-link" onclick="openEntityEdit('${type}',${r.id})">Sửa</button>` : ''}<button class="danger-link" onclick="delEntity('${type}',${r.id},this)">Xóa</button></div></td></tr>`).join('')}</tbody></table>` }
function describeBlockMode(mode, total) { if (mode === 'required_double') { const pairs = Math.floor(total / 2), single = total % 2; return `Bắt buộc tiết đôi · ${pairs ? `${pairs} cặp × 2 tiết` : ''}${pairs && single ? ' + ' : ''}${single ? '1 tiết đơn' : ''}` } if (mode === 'preferred_double') return 'Ưu tiên tiết đôi · có thể tách khi cần'; return 'Tự do · xếp riêng hoặc liền nhau' }
function assignmentFilterState() { return { classId: Number($('#assignmentFilterClass')?.value || 0), subjectId: Number($('#assignmentFilterSubject')?.value || 0), teacherId: Number($('#assignmentFilterTeacher')?.value || 0), status: $('#assignmentFilterStatus')?.value || 'all' } }
function assignmentMissingRows() {
  const assignments = data.assignments || [], classes = data.classes || [], subjects = data.subjects || [], grades = data.grades || [], requirements = data.grade_requirements || [];
  const assignmentByPair = new Map(assignments.map(item => [`${item.class_id}:${item.subject_id}`, item]));
  const requirementsByGrade = new Map();
  requirements.forEach(item => { const key = Number(item.grade_id); if (!requirementsByGrade.has(key)) requirementsByGrade.set(key, []); requirementsByGrade.get(key).push(item) });
  const result = [];
  for (const schoolClass of classes) {
    if (schoolClass.grade_id == null) continue;
    const gradeId = Number(schoolClass.grade_id), grade = grades.find(item => item.id === gradeId);
    for (const requirement of requirementsByGrade.get(gradeId) || []) {
      const subject = subjects.find(item => item.id === requirement.subject_id), assignment = assignmentByPair.get(`${schoolClass.id}:${requirement.subject_id}`);
      if (!assignment) {
        result.push({ issue_type: 'missing', class_id: schoolClass.id, class_name: schoolClass.name, subject_id: requirement.subject_id, subject_name: subject?.name || '?', grade_id: gradeId, grade_name: grade?.name || '?', required_periods: requirement.periods_per_week, required_mode: requirement.block_mode });
        continue;
      }
      if (Number(assignment.periods_per_week) !== Number(requirement.periods_per_week) || String(assignment.block_mode || 'free') !== String(requirement.block_mode || 'free')) {
        result.push({ issue_type: 'mismatch', assignment_id: assignment.id, class_id: schoolClass.id, class_name: schoolClass.name, subject_id: requirement.subject_id, subject_name: subject?.name || '?', grade_id: gradeId, grade_name: grade?.name || '?', required_periods: requirement.periods_per_week, required_mode: requirement.block_mode, assigned_periods: assignment.periods_per_week, assigned_mode: assignment.block_mode || 'free' });
      }
    }
  }
  return result.sort((a, b) => String(a.class_name).localeCompare(String(b.class_name), 'vi') || String(a.subject_name).localeCompare(String(b.subject_name), 'vi'));
}
function assignmentUnassignedClasses() { const assigned = new Set((data.assignments || []).map(item => item.class_id)); return (data.classes || []).filter(item => !assigned.has(item.id)) }
function renderAssignmentFilters() {
  const classEl = $('#assignmentFilterClass'), subjectEl = $('#assignmentFilterSubject'), teacherEl = $('#assignmentFilterTeacher'), statusEl = $('#assignmentFilterStatus'); if (!classEl || !subjectEl || !teacherEl || !statusEl) return;
  const current = { classId: classEl.value, subjectId: subjectEl.value, teacherId: teacherEl.value, status: statusEl.value || 'all' };
  classEl.innerHTML = '<option value="">Tất cả lớp</option>' + opts(data.classes); subjectEl.innerHTML = '<option value="">Tất cả môn</option>' + opts(data.subjects); teacherEl.innerHTML = '<option value="">Tất cả giáo viên</option>' + opts(data.teachers);
  if ([...classEl.options].some(o => o.value === current.classId)) classEl.value = current.classId; if ([...subjectEl.options].some(o => o.value === current.subjectId)) subjectEl.value = current.subjectId; if ([...teacherEl.options].some(o => o.value === current.teacherId)) teacherEl.value = current.teacherId; statusEl.value = current.status;
}
function resetAssignmentFilters() { ['assignmentFilterClass', 'assignmentFilterSubject', 'assignmentFilterTeacher'].forEach(id => { const el = $('#' + id); if (el) el.value = '' }); if ($('#assignmentFilterStatus')) $('#assignmentFilterStatus').value = 'all'; renderAssignmentTable() }
function assignmentSummaryHtml() {
  const issues = assignmentMissingRows(), unassigned = assignmentUnassignedClasses(), requirements = data.grade_requirements || [], classes = data.classes || [], grades = data.grades || [];
  const missing = issues.filter(item => item.issue_type === 'missing'), mismatch = issues.filter(item => item.issue_type === 'mismatch'), affected = new Set(issues.map(item => item.class_id));
  const configuredGrades = new Set(requirements.map(item => Number(item.grade_id))), classesWithoutGrade = classes.filter(item => item.grade_id == null), gradesWithoutProgram = grades.filter(item => !configuredGrades.has(item.id));
  if (!requirements.length) { return '<div class="assignment-filter-summary has-gap"><b>Kiểm tra phân công:</b> Chưa có chương trình môn chuẩn cho khối. Vào <b>Khối / nhóm lớp → Sửa</b> để chọn môn và số tiết/tuần; sau đó hệ thống mới có thể phát hiện thiếu chính xác.</div>' }
  const parts = [];
  if (missing.length) parts.push(`<b>${missing.length}</b> cặp lớp–môn còn thiếu`);
  if (mismatch.length) parts.push(`<b>${mismatch.length}</b> phân công lệch số tiết/chế độ chuẩn`);
  if (unassigned.length) parts.push(`<b>${unassigned.length}</b> lớp chưa có phân công nào`);
  if (classesWithoutGrade.length) parts.push(`<b>${classesWithoutGrade.length}</b> lớp chưa gán khối`);
  if (gradesWithoutProgram.length) parts.push(`<b>${gradesWithoutProgram.length}</b> khối chưa cấu hình chương trình`);
  if (!parts.length) return '<div class="assignment-filter-summary"><b>Kiểm tra phân công:</b> Phân công hiện tại khớp với chương trình môn đã cấu hình cho các khối.</div>';
  return `<div class="assignment-filter-summary has-gap"><b>Kiểm tra phân công:</b> ${parts.join(' · ')}.${affected.size ? ` Có <b>${affected.size} lớp</b> cần kiểm tra.` : ''}</div>`;
}
function assignmentTable() {
  const state = assignmentFilterState();
  if (state.status === 'missing') {
    let rows = assignmentMissingRows();
    if (state.classId) rows = rows.filter(item => item.class_id === state.classId); if (state.subjectId) rows = rows.filter(item => item.subject_id === state.subjectId);
    if (state.teacherId) { const teacher = data.teachers.find(item => item.id === state.teacherId), allowed = new Set((teacher?.subject_ids || []).map(Number)); rows = rows.filter(item => allowed.has(item.subject_id)) }
    if (!rows.length) return '<div class="assignment-filter-empty">Không có cặp lớp–môn nào lệch chương trình với bộ lọc hiện tại.</div>';
    return `<table class="data-table"><thead><tr><th>Lớp</th><th>Khối</th><th>Môn</th><th>Chương trình chuẩn</th><th>Trạng thái</th><th></th></tr></thead><tbody>${rows.map(item => { const required = `${item.required_periods} tiết/tuần · ${describeBlockMode(item.required_mode, item.required_periods)}`; if (item.issue_type === 'mismatch') { const current = `${item.assigned_periods} tiết/tuần · ${describeBlockMode(item.assigned_mode, item.assigned_periods)}`; return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(required)}</td><td><span class="assignment-gap-badge">Đang có: ${esc(current)}</span></td><td><button class="danger-link" onclick="openAssignmentEdit(${item.assignment_id})">Sửa phân công</button></td></tr>` } return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(required)}</td><td><span class="assignment-gap-badge">Chưa phân công</span></td><td><button class="danger-link" onclick="openEntity('assignment',{classId:${item.class_id},subjectId:${item.subject_id}})">+ Thêm phân công</button></td></tr>` }).join('')}</tbody></table>`;
  }
  if (state.status === 'unassigned_class') {
    let rows = assignmentUnassignedClasses(); if (state.classId) rows = rows.filter(item => item.id === state.classId);
    if (!rows.length) return '<div class="assignment-filter-empty">Không có lớp chưa phân công với bộ lọc hiện tại.</div>';
    return `<table class="data-table"><thead><tr><th>Lớp</th><th>Khối</th><th>Trạng thái</th><th></th></tr></thead><tbody>${rows.map(item => { const grade = data.grades.find(g => g.id === item.grade_id); return `<tr><td><b>${esc(item.name)}</b></td><td>${esc(grade?.name || '—')}</td><td><span class="assignment-gap-badge">Chưa có phân công</span></td><td><button class="danger-link" onclick="openEntity('assignment')">+ Thêm phân công</button></td></tr>` }).join('')}</tbody></table>`;
  }
  let rows = data.assignments || []; if (state.classId) rows = rows.filter(item => item.class_id === state.classId); if (state.subjectId) rows = rows.filter(item => item.subject_id === state.subjectId); if (state.teacherId) rows = rows.filter(item => item.teacher_id === state.teacherId);
  if (!rows.length) return `<div class="assignment-filter-empty">${data.assignments?.length ? 'Không có phân công phù hợp với bộ lọc hiện tại.' : 'Chưa có phân công. Hãy gắn lớp – môn – giáo viên và số tiết/tuần trước khi xếp lịch.'}</div>`;
  return `<table class="data-table"><thead><tr><th>Lớp</th><th>Môn</th><th>Giáo viên</th><th>Tiết/tuần</th><th>Chế độ xếp</th><th></th></tr></thead><tbody>${rows.map(item => `<tr><td>${esc(item.class_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(item.teacher_name)}</td><td><b>${item.periods_per_week}</b></td><td>${esc(describeBlockMode(item.block_mode, item.periods_per_week))}</td><td><div class="row end"><button class="danger-link" onclick="openAssignmentEdit(${item.id})">Sửa phân công</button><button class="danger-link" onclick="delEntity('assignment',${item.id},this)">Xóa</button></div></td></tr>`).join('')}</tbody></table>`;
}
function renderAssignmentTable() { const summary = $('#assignmentCompletenessSummary'), table = $('#assignmentTable'); if (summary) summary.innerHTML = assignmentSummaryHtml(); if (table) table.innerHTML = assignmentTable() }
function renderAll() {
  if ($('#subjectTable')) {
    $('#subjectTable').innerHTML = table(data.subjects, [['Tên', 'name'], ['Tên rút gọn', 'short_name'], ['Tiết liên tiếp tối đa', 'max_consecutive']], 'subject');
    $('#departmentTable').innerHTML = table(data.departments, [['Tên tổ', 'name']], 'department');
    $('#teacherTable').innerHTML = table(data.teachers, [['Họ tên', 'name'], ['Tên ngắn', 'short_name'], ['Môn dạy', r => (r.subject_ids || []).map(id => data.subjects.find(x => x.id === id)?.name).filter(Boolean).join(', ') || '—'], ['Tổ', r => data.departments.find(x => x.id === r.department_id)?.name || '—'], ['Tải tuần', r => `${r.assigned_periods || 0}/${r.week_capacity ?? '—'} tiết`], ['Tối đa tiết/ngày', 'max_periods_day']], 'teacher');
    $('#gradeTable').innerHTML = table(data.grades, [['Tên khối/nhóm', 'name'], ['Chương trình', r => { const rows = (data.grade_requirements || []).filter(item => item.grade_id === r.id); return rows.length ? `${rows.length} môn · ${rows.reduce((sum, item) => sum + Number(item.periods_per_week || 0), 0)} tiết/tuần` : 'Chưa cấu hình' }]], 'grade');
    $('#classTable').innerHTML = table(data.classes, [['Tên lớp', 'name'], ['Khối', r => data.grades.find(x => x.id === r.grade_id)?.name || '—']], 'class');
    renderAssignmentFilters();
    renderAssignmentTable();
    if ($('#statLessons')) { $('#statTeachers').textContent = data.teachers.length; $('#statClasses').textContent = data.classes.length; $('#statAssignments').textContent = data.assignments.length; $('#statLessons').textContent = data.lessons.length }
    renderScheduleSelectors(); renderConstraintSelectors();
  }
}
function opts(rows, label = 'name') { return rows.map(x => `<option value="${x.id}">${esc(x[label])}</option>`).join('') }
function blockModeEditor(mode = 'free') { const selected = value => value === mode ? 'selected' : ''; return `<label>Chế độ xếp tiết<select name="block_mode" onchange="updateBlockModePreview(this.form)"><option value="free" ${selected('free')}>Tự do</option><option value="preferred_double" ${selected('preferred_double')}>Ưu tiên tiết đôi</option><option value="required_double" ${selected('required_double')}>Bắt buộc tiết đôi</option></select><small class="block-mode-help">Tự do: các tiết độc lập. Ưu tiên: cố gắng ghép đôi nhưng được tách. Bắt buộc: hệ thống tự chia 2 + 2 + 1.</small></label><div class="block-mode-preview" data-block-preview></div>` }
function updateBlockModePreview(form) { if (!form) return; const total = Number(form.querySelector('[name="periods_per_week"]')?.value || 0), mode = form.querySelector('[name="block_mode"]')?.value || 'free', preview = form.querySelector('[data-block-preview]'); if (preview) preview.textContent = total > 0 ? describeBlockMode(mode, total) : 'Nhập số tiết/tuần để xem cách xếp.' }
function teacherSubjectPicker(selectedIds = []) { const selected = new Set((selectedIds || []).map(Number)); return `<div class="teacher-subject-picker"><div class="assignment-pick-head"><b>Môn giáo viên có thể dạy</b><div class="assignment-pick-actions"><button type="button" onclick="selectTeacherSubjects(this.form,true)">Chọn tất cả</button><button type="button" onclick="selectTeacherSubjects(this.form,false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${data.subjects.length ? data.subjects.map(item => `<label class="assignment-pick-row"><input type="checkbox" name="subject_ids" value="${item.id}" ${selected.has(item.id) ? 'checked' : ''}><span>${esc(item.name)}</span></label>`).join('') : '<div class="assignment-bulk-empty">Chưa có môn học. Hãy thêm môn trước.</div>'}</div></div><p class="teacher-subject-help">Màn phân công chỉ hiển thị các môn được chọn ở đây.</p>` }
function selectTeacherSubjects(form, checked) { if (!form) return; form.querySelectorAll('input[name="subject_ids"]').forEach(input => input.checked = checked) }
function gradeRequirementPicker(selectedRows = []) { const selected = new Map((selectedRows || []).map(item => [Number(item.subject_id), item])); const modeOptions = mode => `<option value="free" ${mode === 'free' ? 'selected' : ''}>Tự do</option><option value="preferred_double" ${mode === 'preferred_double' ? 'selected' : ''}>Ưu tiên tiết đôi</option><option value="required_double" ${mode === 'required_double' ? 'selected' : ''}>Bắt buộc tiết đôi</option>`; return `<div class="teacher-subject-picker"><div class="assignment-pick-head"><b>Chương trình môn chuẩn của khối</b><div class="assignment-pick-actions"><button type="button" onclick="selectGradeRequirements(this.form,true)">Chọn tất cả</button><button type="button" onclick="selectGradeRequirements(this.form,false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${data.subjects.length ? data.subjects.map(item => { const row = selected.get(item.id), checked = !!row, periods = row?.periods_per_week || 1, mode = row?.block_mode || 'free'; return `<div class="assignment-subject-item"><label class="assignment-pick-row"><input type="checkbox" name="grade_subject_ids" value="${item.id}" ${checked ? 'checked' : ''} onchange="toggleGradeRequirement(this)"><span>${esc(item.name)}</span></label><div class="assignment-subject-config" data-grade-subject-settings="${item.id}" ${checked ? '' : 'hidden'}><label>Tiết/tuần<input type="number" name="grade_subject_periods_${item.id}" min="1" max="40" value="${periods}"></label><label>Chế độ xếp<select name="grade_subject_mode_${item.id}">${modeOptions(mode)}</select></label></div></div>` }).join('') : '<div class="assignment-bulk-empty">Chưa có môn học. Hãy thêm môn trước.</div>'}</div></div><p class="teacher-subject-help">Bộ lọc thiếu phân công sẽ so trực tiếp từng lớp trong khối với danh sách này, không suy đoán từ các lớp khác.</p>` }
function toggleGradeRequirement(input) { const box = input.form?.querySelector(`[data-grade-subject-settings="${input.value}"]`); if (box) box.hidden = !input.checked }
function selectGradeRequirements(form, checked) { if (!form) return; form.querySelectorAll('input[name="grade_subject_ids"]').forEach(input => { input.checked = checked; toggleGradeRequirement(input) }) }
function openEntity(type, preset = null) { entityType = type; pendingAssignmentGap = type === 'assignment' && preset ? preset : null; const titles = { subject: 'Thêm môn học', department: 'Thêm tổ chuyên môn', teacher: 'Thêm giáo viên', grade: 'Thêm khối / nhóm', class: 'Thêm lớp', assignment: 'Thêm phân công nhanh' }; $('#modalTitle').textContent = titles[type]; let h = '<label>Tên<input name="name" required></label>'; if (type === 'subject') h += '<label>Tên rút gọn<input name="short_name" required></label><label>Số tiết liên tiếp tối đa<input type="number" name="max_consecutive" value="2" min="1" max="4"></label><p class="muted">Giới hạn số tiết của môn này được phép xếp liền nhau trong cùng một buổi.</p>'; if (type === 'teacher') h = `<label>Họ tên<input name="name" required></label><label>Tên ngắn<input name="short_name" required></label><label>Tổ chuyên môn<select name="department_id"><option value="">Không chọn</option>${opts(data.departments)}</select></label><label>Tối đa tiết/ngày<input type="number" name="max_periods_day" value="5" min="1" max="10"></label>${teacherSubjectPicker()}`; if (type === 'grade') h = `<label>Tên khối / nhóm<input name="name" required></label>${gradeRequirementPicker()}`; if (type === 'class') h = `<label>Tên lớp<input name="name" required></label><label>Khối / nhóm<select name="grade_id"><option value="">Không chọn</option>${opts(data.grades)}</select></label>`; if (type === 'assignment') h = `<div class="assignment-bulk-modal"><p class="assignment-bulk-intro">Chọn giáo viên trước, tick môn và lớp. Nếu các lớp đã có chương trình chuẩn theo khối, số tiết/tuần và chế độ xếp sẽ tự điền theo chương trình; hệ thống không lấy lại số tiết từ một lớp khác của giáo viên.</p><label>Giáo viên<select name="teacher_id" required onchange="renderBulkAssignmentChoices(this.value)"><option value="">Chọn giáo viên</option>${opts(data.teachers)}</select></label><div id="bulkAssignmentChoices"><div class="assignment-bulk-empty">Chọn giáo viên để hiện danh sách môn và lớp.</div></div></div>`; $('#entityFields').innerHTML = h; if (type === 'assignment') { entityModal.querySelector('.modal-form')?.classList.add('assignment-bulk-form') } else { entityModal.querySelector('.modal-form')?.classList.remove('assignment-bulk-form') } entityModal.showModal() }
function editOpts(rows, selected, label = 'name') { return rows.map(x => `<option value="${x.id}" ${x.id === selected ? 'selected' : ''}>${esc(x[label])}</option>`).join('') }
function bulkRequirementForSelection(subjectId, classIds) { if (!classIds.length) return { status: 'none' }; const rows = []; for (const classId of classIds) { const schoolClass = data.classes.find(item => item.id === classId); if (!schoolClass || schoolClass.grade_id == null) return { status: 'missing' }; const requirement = (data.grade_requirements || []).find(item => item.grade_id === schoolClass.grade_id && item.subject_id === subjectId); if (!requirement) return { status: 'missing' }; rows.push(requirement) } const first = rows[0], same = rows.every(item => Number(item.periods_per_week) === Number(first.periods_per_week) && String(item.block_mode || 'free') === String(first.block_mode || 'free')); return same ? { status: 'exact', periods: Number(first.periods_per_week), mode: first.block_mode || 'free' } : { status: 'mixed' } }
function syncBulkCurriculumDefaults(form, force = false) { if (!form) return; const classIds = [...form.querySelectorAll('input[name="class_ids"]:checked')].map(input => Number(input.value)); form.querySelectorAll('input[name="subject_ids"]').forEach(subjectInput => { const subjectId = Number(subjectInput.value), periodInput = form.querySelector(`[name="subject_periods_${subjectId}"]`), modeInput = form.querySelector(`[name="subject_mode_${subjectId}"]`), status = form.querySelector(`[data-subject-curriculum="${subjectId}"]`); if (!periodInput || !modeInput) return; const auto = force || periodInput.dataset.auto !== '0'; const requirement = bulkRequirementForSelection(subjectId, classIds); if (requirement.status === 'exact') { if (auto) { periodInput.value = requirement.periods; modeInput.value = requirement.mode; periodInput.dataset.auto = '1'; modeInput.dataset.auto = '1' } if (status) status.textContent = `Theo chương trình lớp đã chọn: ${requirement.periods} tiết/tuần.` } else if (requirement.status === 'mixed') { if (auto) { periodInput.value = ''; modeInput.value = 'free' } if (status) status.textContent = 'Các lớp đã chọn có chương trình khác nhau cho môn này. Hãy chia lần phân công theo từng khối/chương trình.' } else if (requirement.status === 'missing') { if (auto) { periodInput.value = ''; modeInput.value = 'free' } if (status) status.textContent = 'Có lớp chưa cấu hình chương trình cho môn này; hãy nhập thủ công hoặc cấu hình ở mục Khối / nhóm lớp.' } else { if (auto) { periodInput.value = ''; modeInput.value = 'free' } if (status) status.textContent = 'Chọn lớp để tự điền theo chương trình khối.' } updateBulkSubjectPreview(subjectId, form) }) }
function markBulkSubjectManual(subjectId, form) { const periodInput = form?.querySelector(`[name="subject_periods_${subjectId}"]`), modeInput = form?.querySelector(`[name="subject_mode_${subjectId}"]`); if (periodInput) periodInput.dataset.auto = '0'; if (modeInput) modeInput.dataset.auto = '0'; updateBulkSubjectPreview(subjectId, form); updateBulkAssignmentPreview(form) }
function renderBulkAssignmentChoices(value) { const teacherId = Number(value), box = $('#bulkAssignmentChoices'); if (!box) return; if (!teacherId) { box.innerHTML = '<div class="assignment-bulk-empty">Chọn giáo viên để hiện danh sách môn và lớp.</div>'; return } const teacher = data.teachers.find(item => item.id === teacherId), allowed = new Set((teacher?.subject_ids || []).map(Number)), subjects = data.subjects.filter(item => allowed.has(item.id)).sort((a, b) => a.name.localeCompare(b.name, 'vi')), classes = [...data.classes].sort((a, b) => a.name.localeCompare(b.name, 'vi')); if (!subjects.length) { box.innerHTML = '<div class="assignment-bulk-empty">Giáo viên này chưa được cấu hình môn có thể dạy. Hãy vào mục Giáo viên → Sửa và tick môn trước.</div>'; return } const modeOptions = `<option value="free">Tự do</option><option value="preferred_double">Ưu tiên tiết đôi</option><option value="required_double">Bắt buộc tiết đôi</option>`; const subjectRows = subjects.map(item => `<div class="assignment-subject-item"><label class="assignment-pick-row"><input type="checkbox" name="subject_ids" value="${item.id}" onchange="toggleBulkSubjectSettings(this);syncBulkCurriculumDefaults(this.form);updateBulkAssignmentPreview(this.form)"><span>${esc(item.name)}</span></label><div class="assignment-subject-config" data-subject-settings="${item.id}" hidden><label>Tiết/tuần<input type="number" name="subject_periods_${item.id}" min="1" max="40" value="" placeholder="Theo khối" data-auto="1" oninput="markBulkSubjectManual(${item.id},this.form)"></label><label>Chế độ xếp<select name="subject_mode_${item.id}" data-auto="1" onchange="markBulkSubjectManual(${item.id},this.form)">${modeOptions}</select></label><div class="block-mode-preview" data-subject-preview="${item.id}"></div><small class="teacher-subject-help" data-subject-curriculum="${item.id}">Chọn lớp để tự điền theo chương trình khối.</small></div></div>`).join(''); const classRows = classes.length ? classes.map(item => { const grade = data.grades.find(g => g.id === item.grade_id); return `<label class="assignment-pick-row"><input type="checkbox" name="class_ids" value="${item.id}" onchange="syncBulkCurriculumDefaults(this.form);updateBulkAssignmentPreview(this.form)"><span>${esc(item.name)}${grade ? ` <small>${esc(grade.name)}</small>` : ''}</span></label>` }).join('') : '<div class="assignment-bulk-empty">Chưa có lớp học.</div>'; box.innerHTML = `<div class="assignment-bulk-grid"><div class="assignment-pick-panel"><div class="assignment-pick-head"><b>Môn học của giáo viên</b><div class="assignment-pick-actions"><button type="button" onclick="selectBulkAssignmentGroup('subject_ids',true)">Chọn tất cả</button><button type="button" onclick="selectBulkAssignmentGroup('subject_ids',false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${subjectRows}</div></div><div class="assignment-pick-panel"><div class="assignment-pick-head"><b>Lớp học</b><div class="assignment-pick-actions"><button type="button" onclick="selectBulkAssignmentGroup('class_ids',true)">Chọn tất cả</button><button type="button" onclick="selectBulkAssignmentGroup('class_ids',false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${classRows}</div></div></div><div id="bulkAssignmentPreview" class="assignment-bulk-preview"></div>`; const form = entityModal.querySelector('form'); if (pendingAssignmentGap) { const subjectInput = form.querySelector(`input[name="subject_ids"][value="${pendingAssignmentGap.subjectId}"]`), classInput = form.querySelector(`input[name="class_ids"][value="${pendingAssignmentGap.classId}"]`); if (subjectInput) { subjectInput.checked = true; toggleBulkSubjectSettings(subjectInput) } if (classInput) classInput.checked = true; if (!subjectInput) { box.insertAdjacentHTML('afterbegin', '<div class="assignment-warning" style="padding:10px 12px">Giáo viên này chưa được cấu hình dạy môn đang thiếu. Hãy chọn giáo viên khác hoặc cập nhật môn dạy của giáo viên.</div>') } } syncBulkCurriculumDefaults(form, true); updateBulkAssignmentPreview(form) }
function toggleBulkSubjectSettings(input) { const box = input.form?.querySelector(`[data-subject-settings="${input.value}"]`); if (box) box.hidden = !input.checked; if (input.checked) { syncBulkCurriculumDefaults(input.form); updateBulkSubjectPreview(Number(input.value), input.form) } }
function updateBulkSubjectPreview(subjectId, form) { if (!form) return; const total = Number(form.querySelector(`[name="subject_periods_${subjectId}"]`)?.value || 0), mode = form.querySelector(`[name="subject_mode_${subjectId}"]`)?.value || 'free', preview = form.querySelector(`[data-subject-preview="${subjectId}"]`); if (preview) preview.textContent = total > 0 ? describeBlockMode(mode, total) : 'Chưa có số tiết/tuần.' }
function selectBulkAssignmentGroup(name, checked) { const form = entityModal.querySelector('form'); if (!form) return; form.querySelectorAll(`input[name="${name}"]`).forEach(input => { input.checked = checked; if (name === 'subject_ids') toggleBulkSubjectSettings(input) }); syncBulkCurriculumDefaults(form); updateBulkAssignmentPreview(form) }
function updateBulkAssignmentPreview(form) { const preview = $('#bulkAssignmentPreview'); if (!preview || !form) return; const teacherId = Number(form.querySelector('[name="teacher_id"]')?.value || 0), teacher = data.teachers.find(item => item.id === teacherId), subjectIds = [...form.querySelectorAll('input[name="subject_ids"]:checked')].map(input => Number(input.value)), classIds = [...form.querySelectorAll('input[name="class_ids"]:checked')].map(input => Number(input.value)), total = subjectIds.length * classIds.length; if (!total) { preview.innerHTML = 'Hãy tick ít nhất 1 môn và 1 lớp.'; return } const mixedSubjects = subjectIds.filter(subjectId => bulkRequirementForSelection(subjectId, classIds).status === 'mixed'); if (mixedSubjects.length) { preview.innerHTML = `<span class="assignment-warning">Có ${mixedSubjects.length} môn có số tiết/chế độ khác nhau giữa các lớp đã chọn. Hãy chia lần phân công theo từng khối/chương trình để tránh gán sai.</span>`; return } const subjectSet = new Set(subjectIds), classSet = new Set(classIds), existing = data.assignments.filter(item => subjectSet.has(item.subject_id) && classSet.has(item.class_id)), duplicates = existing.filter(item => item.teacher_id === teacherId).length, conflicts = existing.filter(item => item.teacher_id !== teacherId).length; let addedPeriods = 0; for (const subjectId of subjectIds) { const periods = Number(form.querySelector(`[name="subject_periods_${subjectId}"]`)?.value || 0); for (const classId of classIds) { if (!existing.some(item => item.subject_id === subjectId && item.class_id === classId)) addedPeriods += periods } } const fresh = Math.max(0, total - duplicates - conflicts), current = teacher?.assigned_periods || 0, capacity = teacher?.week_capacity ?? 0, projected = current + addedPeriods; let status = ''; if (conflicts) status = `<span class="assignment-warning">Có ${conflicts} cặp lớp–môn đã thuộc giáo viên khác; hệ thống sẽ không cho lưu cho đến khi xử lý các phân công đó.</span>`; else if (capacity && projected > capacity) status = `<span class="assignment-warning">Tải dự kiến ${projected}/${capacity} tiết/tuần vượt khả năng hiện tại của giáo viên.</span>`; else status = `<span class="assignment-ok">Tải dự kiến: ${projected}/${capacity || '—'} tiết/tuần.</span>`; preview.innerHTML = `Đã chọn <b>${subjectIds.length}</b> môn × <b>${classIds.length}</b> lớp = <b>${total}</b> cặp. ${duplicates ? `Bỏ qua ${duplicates} cặp đã có; ` : ''}dự kiến tạo mới <b>${fresh}</b> phân công, thêm <b>${addedPeriods}</b> tiết/tuần.${status}` }
function openEntityEdit(type, id) { const rows = { subject: data.subjects, teacher: data.teachers, grade: data.grades, class: data.classes }[type] || []; const item = rows.find(x => x.id === Number(id)); if (!item) return; entityType = `${type}_edit`; entityId = item.id; entityModal.querySelector('.modal-form')?.classList.remove('assignment-bulk-form'); const titles = { subject: 'Sửa môn học', teacher: 'Sửa giáo viên', grade: 'Sửa khối / nhóm', class: 'Sửa lớp học' }; $('#modalTitle').textContent = titles[type]; let h = ''; if (type === 'subject') h = `<label>Tên môn học<input name="name" value="${esc(item.name)}" required></label><label>Tên rút gọn<input name="short_name" value="${esc(item.short_name)}" required></label><label>Số tiết liên tiếp tối đa<input type="number" name="max_consecutive" value="${item.max_consecutive}" min="1" max="4" required></label><p class="muted">Giới hạn số tiết của môn này được phép xếp liền nhau trong cùng một buổi.</p>`; if (type === 'teacher') h = `<label>Họ tên<input name="name" value="${esc(item.name)}" required></label><label>Tên ngắn<input name="short_name" value="${esc(item.short_name)}" required></label><label>Tổ chuyên môn<select name="department_id"><option value="">Không chọn</option>${editOpts(data.departments, item.department_id)}</select></label><label>Tối đa tiết/ngày<input type="number" name="max_periods_day" value="${item.max_periods_day}" min="1" max="10" required></label>${teacherSubjectPicker(item.subject_ids || [])}`; if (type === 'grade') h = `<label>Tên khối / nhóm<input name="name" value="${esc(item.name)}" required></label>${gradeRequirementPicker((data.grade_requirements || []).filter(row => row.grade_id === item.id))}`; if (type === 'class') h = `<label>Tên lớp<input name="name" value="${esc(item.name)}" required></label><label>Khối / nhóm<select name="grade_id"><option value="">Không chọn</option>${editOpts(data.grades, item.grade_id)}</select></label>`; $('#entityFields').innerHTML = h; entityModal.showModal() }
function openAssignmentEdit(id) { const item = data.assignments.find(x => x.id === id); if (!item) return; entityType = 'assignment_edit'; $('#modalTitle').textContent = 'Sửa phân công'; $('#entityFields').innerHTML = `<div class="assignment-summary"><b>${esc(item.class_name)} · ${esc(item.subject_name)}</b><span>${esc(item.teacher_name)}</span></div><input type="hidden" name="assignment_id" value="${item.id}"><label>Số tiết/tuần<input type="number" name="periods_per_week" min="1" max="40" value="${item.periods_per_week}" required oninput="updateBlockModePreview(this.form)"></label>${blockModeEditor(item.block_mode)}`; updateBlockModePreview(entityModal.querySelector('form')); entityModal.showModal() }
async function submitEntity(e) {
  e.preventDefault();
  const form = e.target, formData = new FormData(form), o = Object.fromEntries(formData), submitButton = e.submitter || $('#entitySubmitButton');
  setEntityActionMessage(''); setInlineActionState(submitButton, 'loading', { idle: 'Lưu', loading: 'Đang lưu...' });
  for (const k of ['department_id', 'grade_id', 'class_id', 'subject_id', 'teacher_id', 'assignment_id', 'max_periods_day', 'max_consecutive', 'periods_per_week']) if (o[k]) o[k] = Number(o[k]);
  if (entityType === 'teacher' || entityType === 'teacher_edit') o.subject_ids = formData.getAll('subject_ids').map(Number).filter(Boolean);
  if (entityType === 'grade' || entityType === 'grade_edit') {
    o.subject_requirements = formData.getAll('grade_subject_ids').map(Number).filter(Boolean).map(subject_id => ({ subject_id, periods_per_week: Number(form.querySelector(`[name="grade_subject_periods_${subject_id}"]`)?.value || 0), block_mode: form.querySelector(`[name="grade_subject_mode_${subject_id}"]`)?.value || 'free' }));
    if (o.subject_requirements.some(item => !Number.isInteger(item.periods_per_week) || item.periods_per_week < 1)) { entityActionError(submitButton, 'Số tiết/tuần trong chương trình khối phải từ 1 trở lên.'); return }
  }
  try {
    if (entityType === 'assignment') {
      const subject_ids = formData.getAll('subject_ids').map(Number).filter(Boolean), class_ids = formData.getAll('class_ids').map(Number).filter(Boolean);
      if (!o.teacher_id) { entityActionError(submitButton, 'Hãy chọn giáo viên.'); return }
      if (!subject_ids.length) { entityActionError(submitButton, 'Hãy chọn ít nhất một môn học.'); return }
      if (!class_ids.length) { entityActionError(submitButton, 'Hãy chọn ít nhất một lớp.'); return }
      const mixedSubject = subject_ids.find(subject_id => bulkRequirementForSelection(subject_id, class_ids).status === 'mixed');
      if (mixedSubject) { const subject = data.subjects.find(item => item.id === mixedSubject); entityActionError(submitButton, `${subject?.name || 'Môn đã chọn'} có chương trình khác nhau giữa các lớp. Hãy chia lần phân công theo từng khối.`); return }
      const subjects = subject_ids.map(subject_id => ({ subject_id, periods_per_week: Number(form.querySelector(`[name="subject_periods_${subject_id}"]`)?.value || 0), block_mode: form.querySelector(`[name="subject_mode_${subject_id}"]`)?.value || 'free' }));
      if (subjects.some(item => !Number.isInteger(item.periods_per_week) || item.periods_per_week < 1)) { entityActionError(submitButton, 'Số tiết/tuần của mỗi môn phải từ 1 trở lên.'); return }
      const r = await fetch(`/api/projects/${PROJECT_ID}/assignments/bulk`, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ teacher_id: o.teacher_id, class_ids, subjects }) });
      const result = await r.json();
      if (!r.ok) { entityActionError(submitButton, result.message || result.detail || 'Không thể thêm phân công.'); return }
      setInlineActionState(submitButton, 'success', { idle: 'Lưu', success: 'Đã lưu' }); setEntityActionMessage(result.message || `Đã tạo ${result.created || 0} phân công.`, 'success'); await wait(650); entityModal.close(); await refresh(true); return;
    }
    if (entityType === 'assignment_edit') {
      const r = await fetch(`/api/projects/${PROJECT_ID}/assignments/${o.assignment_id}`, { method: 'PUT', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ periods_per_week: o.periods_per_week, block_mode: o.block_mode }) }); const result = await r.json();
      if (!r.ok) { entityActionError(submitButton, result.message || result.detail || 'Không thể cập nhật phân công.'); return }
      setInlineActionState(submitButton, 'success', { idle: 'Lưu', success: 'Đã cập nhật' }); setEntityActionMessage('Đã cập nhật phân công.', 'success'); await wait(650); entityModal.close(); await refresh(true); return;
    }
    if (entityType.endsWith('_edit')) {
      const type = entityType.replace('_edit', ''); const r = await fetch(`/api/projects/${PROJECT_ID}/entity/${type}/${entityId}`, { method: 'PUT', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ type, data: o }) }); const result = await r.json();
      if (!r.ok) { entityActionError(submitButton, result.message || result.detail || 'Không thể cập nhật dữ liệu.'); return }
      setInlineActionState(submitButton, 'success', { idle: 'Lưu', success: 'Đã cập nhật' }); setEntityActionMessage('Đã cập nhật dữ liệu.', 'success'); await wait(650); entityModal.close(); await refresh(true); return;
    }
    const r = await fetch(`/api/projects/${PROJECT_ID}/entity`, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ type: entityType, data: o }) }); const result = await r.json();
    if (!r.ok) { entityActionError(submitButton, result.message || result.detail || 'Không thể lưu dữ liệu.'); return }
    setInlineActionState(submitButton, 'success', { idle: 'Lưu', success: 'Đã lưu' }); setEntityActionMessage('Đã lưu dữ liệu.', 'success'); await wait(650); entityModal.close(); await refresh(true);
  } catch (error) { entityActionError(submitButton, 'Mất kết nối tới máy chủ. Vui lòng thử lại.'); }
}
async function delEntity(type, id, button) {
  if (!await confirmAction('Xóa mục này?', { confirmText: 'Xóa' })) return;
  setInlineActionState(button, 'loading', { idle: 'Xóa', loading: 'Đang xóa...' });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/entity/${type}/${id}`, { method: 'DELETE', headers: operationHeaders() }); const result = await r.json().catch(() => ({}));
    if (r.ok) { setInlineActionState(button, 'success', { idle: 'Xóa', success: 'Đã xóa' }); await wait(450); await refresh(true) }
    else { setInlineActionState(button, 'error', { idle: 'Xóa', error: 'Không thể xóa' }, 2200); showInlineActionFeedback(button, result.message || result.detail || 'Không thể xóa dữ liệu. Vui lòng thử lại.', 'error', 5000) }
  } catch { setInlineActionState(button, 'error', { idle: 'Xóa', error: 'Lỗi kết nối' }, 2200); showInlineActionFeedback(button, 'Mất kết nối tới máy chủ.', 'error', 5000) }
}
async function generateSchedule(allowRebuild = false) {
  setScheduleActionState('loading'); setScheduleFeedback('', 'info', 0);
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/generate`, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ allow_rebuild: allowRebuild }) }); const j = await r.json();
    if (r.ok) { try { await refresh(true) } catch { setScheduleActionState('error', 2200); setScheduleFeedback('Máy chủ đã xếp lịch nhưng không thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ thời khóa biểu.', 'error', 6500); return } renderSchedule(); setScheduleActionState('success', 1400); setScheduleFeedback(j.message || 'Đã xếp thời khóa biểu thành công.', 'success', 2600); launchConfetti() }
    else if (j.requires_confirmation && !allowRebuild) { setScheduleActionState('idle'); if (await confirmAction(`${j.message}\n\nBạn có đồng ý xếp lại phần không cố định không?`, { title: 'Xếp lại thời khóa biểu', confirmText: 'Xếp lại' })) return generateSchedule(true) }
    else { setScheduleActionState('error', 1800); setScheduleFeedback(j.message || 'Xếp thời khóa biểu thất bại; lịch hiện tại được giữ nguyên.', 'error', 5200) }
  } catch { setScheduleActionState('error', 1800); setScheduleFeedback('Mất kết nối tới máy chủ. Không thể xếp thời khóa biểu.', 'error', 5200) }
}
function goToAssignments() { document.querySelector('.nav[data-tab="assignments"]')?.click() }
function renderManualTray() {
  const tray = $('#unscheduledTray'), scheduledBox = $('#scheduledAssignmentTray'), coverageBox = $('#assignmentCoverage'), vt = $('#viewType'), ve = $('#viewEntity'); if (!tray) return;
  const coverage = data.coverage || {};
  const duplicates = coverage.duplicate_assignments || [];
  const overloaded = coverage.over_capacity_teachers || [];
  const overloadedClasses = coverage.over_capacity_classes || [];
  const groups = [['Giáo viên chưa phân công', coverage.unassigned_teachers || []], ['Môn chưa phân công', coverage.unassigned_subjects || []], ['Lớp chưa phân công', coverage.unassigned_classes || []]].filter(([, rows]) => rows.length);
  const duplicateHtml = duplicates.length ? `<div><b>Không thể xếp do phân công lớp–môn bị trùng</b><p>${duplicates.map(row => `${esc(row.class_name)} – ${esc(row.subject_name)}: ID ${(row.assignment_ids || []).join(', ')}`).join('; ')}. Hãy xóa hoặc chuyển để mỗi lớp–môn chỉ còn một giáo viên.</p></div>` : '';
  const overloadHtml = overloaded.length ? `<div><b>Không thể xếp đầy đủ do giáo viên quá tải</b><p>${overloaded.map(row => `${esc(row.teacher_name)}: ${row.assigned}/${row.capacity} tiết (dư ${row.excess})`).join('; ')}. Hãy giảm/chuyển phân công, tăng giới hạn tiết/ngày hoặc bỏ bớt tiết tránh.</p></div>` : '';
  const classOverloadHtml = overloadedClasses.length ? `<div><b>Không thể xếp đầy đủ do lớp vượt số ô học</b><p>${overloadedClasses.map(row => `${esc(row.class_name)}: ${row.assigned}/${row.capacity} tiết (dư ${row.excess})`).join('; ')}. Hãy giảm phân công hoặc bỏ bớt khóa/tiết tránh của lớp.</p></div>` : '';
  const gapsHtml = groups.length ? `<div><b>Dữ liệu chưa có phân công</b><p>Giáo viên, môn hoặc lớp chỉ xuất hiện trên thời khóa biểu sau khi được tạo ở mục Phân công.</p>${groups.map(([label, rows]) => `<div><strong>${label}:</strong> ${rows.map(row => esc(row.name)).join(', ')}</div>`).join('')}</div>` : '';
  coverageBox.innerHTML = (duplicateHtml || overloadHtml || classOverloadHtml || gapsHtml) ? `<div class="coverage-warning">${duplicateHtml}${overloadHtml}${classOverloadHtml}${gapsHtml}<button class="btn ghost" onclick="goToAssignments()">Đến mục Phân công</button></div>` : '';
  const counts = {}; data.lessons.forEach(lesson => counts[lesson.assignment_id] = (counts[lesson.assignment_id] || 0) + 1);
  let rows = data.assignments.map(item => ({ ...item, scheduled: counts[item.id] || 0, remaining: Math.max(0, item.periods_per_week - (counts[item.id] || 0)) }));
  if (vt && ve && vt.value === 'class') rows = rows.filter(item => item.class_id === Number(ve.value));
  if (vt && ve && vt.value === 'teacher') rows = rows.filter(item => item.teacher_id === Number(ve.value));
  if (!rows.length) {
    scheduledBox.innerHTML = '';
    const filtered = vt && ve && (vt.value === 'class' || vt.value === 'teacher');
    tray.innerHTML = `<div class="empty-state">${filtered ? 'Không có phân công cho ' + (vt.value === 'class' ? 'lớp' : 'giáo viên') + ' đang chọn.' : 'Chưa có phân công để xếp. Hãy tạo phân công lớp – môn – giáo viên – số tiết/tuần.'}</div>`;
    return
  }
  const scheduled = rows.filter(item => item.scheduled > 0), pending = rows.filter(item => item.remaining > 0);
  scheduledBox.innerHTML = scheduled.length ? `<div class="scheduled-label">Đang có trên lịch · kéo cả thẻ xuống khay để thu hồi toàn bộ phân công</div><div class="scheduled-cards">${scheduled.map(item => `<div class="scheduled-assignment" draggable="false" data-drag-payload="scheduled-assignment:${item.id}"><div><b>${esc(item.subject_short)}</b><small>${esc(item.class_name)} · ${esc(item.teacher_short)}</small></div><span>${item.scheduled}/${item.periods_per_week} tiết</span></div>`).join('')}</div>` : '';
  const hint = '<div class="tray-drop-hint">Thả tiết trên thời khóa biểu hoặc thẻ “đang có trên lịch” vào đây để đưa về khay</div>';
  tray.innerHTML = hint + pending.map(item => `<div class="tray-lesson" draggable="false" data-drag-payload="assignment:${item.id}"><div><b>${esc(item.subject_short)}</b><small>${esc(item.class_name)} · ${esc(item.teacher_short)}</small></div><span>Còn ${item.remaining}</span></div>`).join('');
}
function renderScheduleSelectors() { const vt = $('#viewType'), ve = $('#viewEntity'), search = $('#viewSearch'); if (!vt || !ve) return; if (vt.value === 'overview') { ve.innerHTML = '<option value="all">Toàn trường</option>'; ve.disabled = true; ve.style.display = 'none'; if (search) { search.value = ''; search.disabled = true } } else { ve.disabled = false; ve.style.display = ''; if (search) search.disabled = false; const source = vt.value === 'teacher' ? data.teachers : vt.value === 'subject' ? data.subjects : data.classes; const query = (search?.value || '').trim().toLocaleLowerCase('vi'); const rows = query ? source.filter(item => String(item.name || '').toLocaleLowerCase('vi').includes(query)) : source; const old = ve.value; ve.innerHTML = opts(rows); if ([...ve.options].some(x => x.value === old)) ve.value = old } vt.onchange = () => { if (search) search.value = ''; renderScheduleSelectors(); renderSchedule() }; ve.onchange = () => { renderSchedule(); renderManualTray() }; if (search) search.oninput = () => { renderScheduleSelectors(); renderSchedule() }; renderSchedule(); renderManualTray() }
function clusteredLessonIds() { const marked = new Set(), eligible = new Set(data.assignments.filter(item => item.block_mode === 'preferred_double' || item.block_mode === 'required_double').map(item => item.id)), groups = new Map(), pps = data.project.periods, ppd = data.project.sessions * pps; for (const lesson of data.lessons) { if (!eligible.has(lesson.assignment_id)) continue; const day = Math.floor(lesson.slot / ppd), inside = lesson.slot % ppd, session = Math.floor(inside / pps), key = `${lesson.assignment_id}:${day}:${session}`; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(lesson) } for (const lessons of groups.values()) { lessons.sort((left, right) => left.slot - right.slot); let run = []; const markRun = () => { if (run.length === 2) run.forEach(lesson => marked.add(lesson.id)); run = [] }; for (const lesson of lessons) { if (run.length && lesson.slot !== run[run.length - 1].slot + 1) markRun(); run.push(lesson) } markRun() } return marked }
function renderSchedule(preserveScroll = false) { const box = $('#scheduleGrid'), vt = $('#viewType'), ve = $('#viewEntity'); if (!box || !vt || !ve) return; const currentTable = box.querySelector('.timetable'), scrollState = preserveScroll && currentTable ? { top: currentTable.scrollTop, left: currentTable.scrollLeft } : null; if (vt.value !== 'overview' && !ve.value) { box.innerHTML = '<div class="empty-state">Không tìm thấy đối tượng phù hợp với bộ lọc hiện tại.</div>'; return } const days = data.project.days, pps = data.project.periods, sessions = data.project.sessions, clustered = clusteredLessonIds(), legend = '<div class="schedule-color-legend"><b>Chú thích màu</b><span><i class="schedule-color-swatch"></i>Tiết đơn</span><span><i class="schedule-color-swatch cluster"></i>Tiết đang được ghép đôi</span></div>'; let html = `<div class="timetable ${vt.value === 'overview' ? 'overview-timetable' : ''}" style="grid-template-columns:90px repeat(${days},minmax(135px,1fr))"><div class="cell head">Tiết</div>`; for (let d = 0; d < days; d++)html += `<div class="cell head">${['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'CN'][d]}</div>`; for (let s = 0; s < sessions; s++) { for (let p = 0; p < pps; p++) { html += `<div class="cell period">${sessions > 1 ? (s === 0 ? 'S' : 'C') + ' ' : ''}${p + 1}</div>`; for (let d = 0; d < days; d++) { const slot = d * (sessions * pps) + s * pps + p; const lessons = data.lessons.filter(l => l.slot === slot).filter(l => { const a = data.assignments.find(x => x.id === l.assignment_id); if (!a) return false; if (vt.value === 'overview') return true; return vt.value === 'class' ? a.class_id === Number(ve.value) : vt.value === 'subject' ? a.subject_id === Number(ve.value) : a.teacher_id === Number(ve.value) }).sort((left, right) => { const a = data.assignments.find(x => x.id === left.assignment_id), b = data.assignments.find(x => x.id === right.assignment_id); return (a?.class_name || '').localeCompare(b?.class_name || '', 'vi') }); html += `<div class="cell available" data-slot="${slot}" ondragover="event.preventDefault()" ondrop="dropLesson(event,${slot})">${lessons.map(l => lessonHtml(l, vt.value, clustered.has(l.id))).join('')}</div>` } } } html += '</div>'; box.innerHTML = legend + html; if (scrollState) { const nextTable = box.querySelector('.timetable'); if (nextTable) { nextTable.scrollTop = scrollState.top; nextTable.scrollLeft = scrollState.left } } }
function lessonHtml(l, view, inCluster = false) { const a = data.assignments.find(x => x.id === l.assignment_id); if (!a) return ''; const detail = `${a.class_name} · ${a.teacher_short}`; const actions = window.READ_ONLY || l._syncing ? '' : l.locked ? `<button class="lesson-remove" title="Bỏ cố định tiết/cặp này" onclick="event.stopPropagation();unfixGroup(${a.id},${l.slot},this)">🔓</button>` : `<button class="lesson-pin" title="Cố định tiết/cặp này" onclick="event.stopPropagation();setFixed(${a.id},${l.slot},this)">📌</button><button class="lesson-remove" title="Gỡ tiết" onclick="event.stopPropagation();removeLesson(${l.id})">×</button>`; const dragPayload = !window.READ_ONLY && !l.locked && !l._syncing ? ` data-drag-payload="${l.id}"` : ''; const syncing = l._syncing ? `<span class="lesson-sync-indicator" role="status" aria-live="polite" title="Đang lưu thay đổi"><span class="lesson-sync-spinner" aria-hidden="true"></span><span class="lesson-sync-text">Đang lưu</span></span>` : ''; return `<div class="lesson ${view === 'overview' ? 'lesson-overview' : ''} ${inCluster ? 'lesson-cluster' : ''} ${l._syncing ? 'lesson-syncing' : ''}" draggable="false"${dragPayload}><b>${esc(a.subject_short)}</b><small>${esc(detail)}</small>${l.locked ? ' <span title="Tiết cố định">🔒</span>' : ''}${syncing}${actions}</div>` }
function showToast(message, type = 'info', duration = 3200) {
  if (!message) return;
  let container = document.getElementById('appToastContainer');
  if (!container) { container = document.createElement('div'); container.id = 'appToastContainer'; container.className = 'app-toast-container'; document.body.appendChild(container) }
  const toast = document.createElement('div'); toast.className = `app-toast is-${type}`;
  const icon = type === 'error' || type === 'warning' ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' : type === 'success' ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>' : '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  toast.innerHTML = `<span class="app-toast-icon">${icon}</span><span class="app-toast-text">${esc(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => { toast.classList.add('is-hiding'); setTimeout(() => { if (toast.isConnected) toast.remove() }, 300) }, duration);
}
let optimisticLessonId = -1;
const pendingDropPayloads = new Set();
function renderOptimisticSchedule() { renderSchedule(true); renderManualTray() }
function showDropConflict(slot, message) {
  const text = message || 'Không thể xếp tiết';
  const cell = document.querySelector(`.cell.available[data-slot="${slot}"]`);
  if (cell) { cell.title = text; cell.classList.add('conflict-shake'); setTimeout(() => cell.classList.remove('conflict-shake'), 600) }
  showToast(text, 'warning', 3600);
}
async function dropLessonPayload(raw, slot) {
  if (window.READ_ONLY || !raw || pendingDropPayloads.has(raw)) return; const isNew = raw.startsWith('assignment:'); const rawId = isNew ? raw.slice('assignment:'.length) : raw; if (!/^\d+$/.test(rawId)) return;
  const id = Number(rawId), endpoint = isNew ? `/api/projects/${PROJECT_ID}/lessons` : `/api/projects/${PROJECT_ID}/move`;
  let optimisticLesson = null, oldSlot = null;
  if (isNew) {
    const assignment = data.assignments.find(item => item.id === id); if (!assignment) return;
    optimisticLesson = { id: optimisticLessonId--, assignment_id: id, slot, locked: false, _syncing: true }; data.lessons.push(optimisticLesson); renderOptimisticSchedule();
  } else {
    optimisticLesson = data.lessons.find(item => item.id === id); if (!optimisticLesson || optimisticLesson.locked || optimisticLesson._syncing) return; if (optimisticLesson.slot === slot) return;
    oldSlot = optimisticLesson.slot; optimisticLesson.slot = slot; optimisticLesson._syncing = true; renderOptimisticSchedule();
  }
  pendingDropPayloads.add(raw);
  const payload = isNew ? { assignment_id: id, slot } : { lesson_id: id, slot };
  try {
    const r = await fetch(endpoint, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(payload) }); const j = await r.json().catch(() => ({}));
    if (r.ok) {
      let stateWasReplaced = false;
      if (isNew) {
        const live = data.lessons.find(item => item.id === optimisticLesson.id);
        if (live) { live.id = Number(j.id) || live.id; delete live._syncing } else stateWasReplaced = true;
      } else {
        const live = data.lessons.find(item => item.id === id);
        if (live && live._syncing) { live.slot = slot; delete live._syncing } else stateWasReplaced = true;
      }
      if (stateWasReplaced) { try { await refresh(true) } catch { renderOptimisticSchedule() } } else renderOptimisticSchedule();
      return;
    }
    if (isNew) data.lessons = data.lessons.filter(item => item.id !== optimisticLesson.id);
    else { const live = data.lessons.find(item => item.id === id); if (live && live._syncing) { live.slot = oldSlot; delete live._syncing } }
    renderOptimisticSchedule(); showDropConflict(slot, j.message || j.detail || 'Không thể xếp tiết');
  } catch {
    if (isNew) data.lessons = data.lessons.filter(item => item.id !== optimisticLesson.id);
    else { const live = data.lessons.find(item => item.id === id); if (live && live._syncing) { live.slot = oldSlot; delete live._syncing } }
    renderOptimisticSchedule(); showDropConflict(slot, 'Mất kết nối tới máy chủ');
  } finally {
    pendingDropPayloads.delete(raw);
  }
}
async function dropLesson(e, slot) { return dropLessonPayload(e?.dataTransfer?.getData('text/plain') || '', slot) }
async function removeLesson(id) {
  setTrayActionStatus('loading', 'Đang đưa tiết về khay…');
  try { const r = await fetch(`/api/projects/${PROJECT_ID}/lessons/${id}`, { method: 'DELETE', headers: operationHeaders() }); const j = await r.json(); if (r.ok) { await refresh(true); setTrayActionStatus('success', j.message || 'Đã đưa tiết về khay', 1800) } else setTrayActionStatus('error', j.message || 'Không thể gỡ tiết', 3600) }
  catch { setTrayActionStatus('error', 'Mất kết nối tới máy chủ. Không thể đưa tiết về khay.', 3600) }
}
async function setFixed(assignmentId, slot, button) {
  const original = button?.textContent || '📌'; if (button) { button.disabled = true; button.textContent = '…' }
  try { const r = await fetch(`/api/projects/${PROJECT_ID}/fixed`, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ assignment_id: assignmentId, slot }) }); const j = await r.json(); if (r.ok) { await refresh(true) } else if (button) { button.disabled = false; button.textContent = '!'; button.title = j.message || j.detail || 'Không thể cố định tiết'; setTimeout(() => { if (button.isConnected) { button.textContent = original; button.disabled = false } }, 1400) } } catch { if (button) { button.disabled = false; button.textContent = '!'; button.title = 'Mất kết nối tới máy chủ' } }
}
async function unfixGroup(assignmentId, slot, button) {
  const original = button?.textContent || '🔓'; if (button) { button.disabled = true; button.textContent = '…' }
  try { const r = await fetch(`/api/projects/${PROJECT_ID}/fixed/${assignmentId}/${slot}`, { method: 'DELETE', headers: operationHeaders() }); const j = await r.json(); if (r.ok) { await refresh(true) } else if (button) { button.disabled = false; button.textContent = '!'; button.title = j.message || j.detail || 'Không thể bỏ cố định'; setTimeout(() => { if (button.isConnected) { button.textContent = original; button.disabled = false } }, 1400) } } catch { if (button) { button.disabled = false; button.textContent = '!'; button.title = 'Mất kết nối tới máy chủ' } }
}
async function returnAssignmentToTray(id) {
  setTrayActionStatus('loading', 'Đang đưa phân công về khay…');
  try { const r = await fetch(`/api/projects/${PROJECT_ID}/assignments/${id}/lessons`, { method: 'DELETE', headers: operationHeaders() }); const j = await r.json(); if (r.ok) { await refresh(true); setTrayActionStatus('success', j.message || 'Đã đưa phân công về khay', 1800) } else setTrayActionStatus('error', j.message || 'Không thể đưa phân công về khay', 3600) }
  catch { setTrayActionStatus('error', 'Mất kết nối tới máy chủ. Không thể đưa phân công về khay.', 3600) }
}
async function returnAllToTray(button) {
  if (!await confirmAction('Đưa toàn bộ tiết chưa cố định về khay? Các tiết đã cố định sẽ được giữ nguyên. Phân công và số tiết/tuần không thay đổi.', { title: 'Đưa lịch về khay', confirmText: 'Đưa về khay' })) return;
  setInlineActionState(button, 'loading', { idle: 'Đưa tiết chưa cố định về khay', loading: 'Đang đưa về khay...' });
  try { const r = await fetch(`/api/projects/${PROJECT_ID}/lessons`, { method: 'DELETE', headers: operationHeaders() }); const j = await r.json(); if (r.ok) { await refresh(true); setInlineActionState(button, 'success', { idle: 'Đưa tiết chưa cố định về khay', success: 'Đã đưa về khay' }, 1800); showInlineActionFeedback(button, j.message || 'Đã đưa các tiết chưa cố định về khay.', 'success', 2600) } else { setInlineActionState(button, 'error', { idle: 'Đưa tiết chưa cố định về khay', error: 'Chưa đưa được' }, 2200); showInlineActionFeedback(button, j.message || 'Không thể đưa lịch về khay.', 'error', 5000) } }
  catch { setInlineActionState(button, 'error', { idle: 'Đưa tiết chưa cố định về khay', error: 'Lỗi kết nối' }, 2200); showInlineActionFeedback(button, 'Mất kết nối tới máy chủ.', 'error', 5000) }
}
async function dropToTrayPayload(raw) { if (window.READ_ONLY || !raw || raw.startsWith('assignment:')) return; if (raw.startsWith('scheduled-assignment:')) { await returnAssignmentToTray(Number(raw.split(':')[1])); return } if (/^\d+$/.test(raw)) await removeLesson(Number(raw)) }
async function dropToTray(e) { return dropToTrayPayload(e?.dataTransfer?.getData('text/plain') || '') }
function constraintStateMarkup(blocked, label) {
  const icon = blocked ? '<svg class="constraint-state-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>' : '<svg class="constraint-state-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>';
  return `${icon}<span>${esc(label)}</span>`;
}
function animateConstraintState(host, blocked, label) {
  if (!host) return;
  let stage = host.querySelector(':scope > .constraint-state-stage');
  if (!stage) { stage = document.createElement('span'); stage.className = 'constraint-state-stage'; host.textContent = ''; host.appendChild(stage) }
  stage.querySelectorAll('.constraint-state-content.constraint-state-leaving').forEach(node => node.remove());
  const current = stage.querySelector('.constraint-state-content');
  const next = document.createElement('span'); next.className = `constraint-state-content constraint-state-enter ${blocked ? 'is-blocked' : 'is-allowed'}`; next.innerHTML = constraintStateMarkup(blocked, label);
  if (current) { current.classList.add('constraint-state-leaving'); const cleanup = () => current.remove(); current.addEventListener('animationend', cleanup, { once: true }); setTimeout(cleanup, 360) }
  stage.appendChild(next);
}
function setGlobalSlotLockState(button, locked, animate = true) {
  if (!button) return; button.classList.toggle('is-locked', locked);
  if (animate) animateConstraintState(button, locked, locked ? 'Đã khóa' : 'Cho phép');
  else button.innerHTML = `<span class="constraint-state-stage"><span class="constraint-state-content ${locked ? 'is-blocked' : 'is-allowed'}">${constraintStateMarkup(locked, locked ? 'Đã khóa' : 'Cho phép')}</span></span>`;
}
function setSessionLockState(button, locked, animate = true) {
  if (!button) return; button.classList.toggle('is-locked', locked); const label = button.dataset.label; let host = button.querySelector('.session-lock-state');
  if (!host) { const old = button.querySelector('span'); host = document.createElement('span'); host.className = 'session-lock-state'; if (old) old.replaceWith(host); else button.appendChild(host) }
  if (animate) animateConstraintState(host, locked, label);
  else host.innerHTML = `<span class="constraint-state-stage"><span class="constraint-state-content ${locked ? 'is-blocked' : 'is-allowed'}">${constraintStateMarkup(locked, label)}</span></span>`;
}
function toggleConstraintCell(cell) { const blocked = !cell.classList.contains('blocked'); cell.classList.toggle('blocked', blocked); cell.setAttribute('aria-pressed', blocked ? 'true' : 'false'); animateConstraintState(cell, blocked, blocked ? 'Tiết tránh' : 'Có thể xếp') }
function ensureGlobalSessionLockPanel() { const section = $('#constraints'); if (!section) return null; let panel = $('#globalSessionLocks'); if (panel) return panel; panel = document.createElement('div'); panel.id = 'globalSessionLocks'; panel.className = 'global-session-locks'; panel.innerHTML = '<h2>Khóa lịch toàn trường</h2><p>Chọn khóa nguyên buổi hoặc chỉ khóa từng tiết. Xếp tự động và kéo thả đều tuân thủ các khóa này.</p><div id="sessionLockGrid" class="session-lock-grid"></div><div class="global-slot-lock-title"><h3>Khóa từng tiết</h3><p>Nhấn vào từng ô để khóa hoặc mở khóa riêng tiết đó.</p></div><div id="globalSlotLockGrid" class="global-slot-lock-grid"></div><div class="row end"><button class="btn" type="button" onclick="saveGlobalSessionLocks(this)">Lưu khóa lịch</button></div>'; const toolbar = section.querySelector('.constraint-toolbar'); section.insertBefore(panel, toolbar); return panel }
function toggleSessionLock(button) { const locked = !button.classList.contains('is-locked'), key = Number(button.dataset.sessionLock); setSessionLockState(button, locked); document.querySelectorAll(`[data-global-session="${key}"]`).forEach(slot => setGlobalSlotLockState(slot, locked)) }
function toggleGlobalSlotLock(button) { const selected = !button.classList.contains('is-locked'); setGlobalSlotLockState(button, selected); const key = Number(button.dataset.globalSession), slots = [...document.querySelectorAll(`[data-global-session="${key}"]`)], sessionButton = document.querySelector(`[data-session-lock="${key}"]`), locked = slots.length > 0 && slots.every(slot => slot.classList.contains('is-locked')); if (sessionButton) setSessionLockState(sessionButton, locked) }
function renderGlobalSessionLocks() { if (!ensureGlobalSessionLockPanel()) return; const grid = $('#sessionLockGrid'), slotGrid = $('#globalSlotLockGrid'), blocked = new Set(data.project.blocked_slots || []), days = data.project.days, sessions = data.project.sessions, pps = data.project.periods, ppd = sessions * pps, dayNames = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật']; let html = ''; for (let day = 0; day < days; day++)for (let session = 0; session < sessions; session++) { const key = day * sessions + session, start = day * ppd + session * pps, locked = Array.from({ length: pps }, (_, index) => start + index).every(slot => blocked.has(slot)), sessionName = sessions === 1 ? 'Cả buổi' : session === 0 ? 'Buổi sáng' : 'Buổi chiều'; html += `<button type="button" class="session-lock ${locked ? 'is-locked' : ''}" data-session-lock="${key}" data-label="${sessionName}" onclick="toggleSessionLock(this)"><b>${dayNames[day]}</b><span class="session-lock-state"><span class="constraint-state-stage"><span class="constraint-state-content ${locked ? 'is-blocked' : 'is-allowed'}">${constraintStateMarkup(locked, sessionName)}</span></span></span></button>` } grid.innerHTML = html; slotGrid.style.gridTemplateColumns = `90px repeat(${days},minmax(90px,1fr))`; let slotHtml = '<div class="slot-head">Tiết</div>' + dayNames.slice(0, days).map(day => `<div class="slot-head">${day}</div>`).join(''); for (let session = 0; session < sessions; session++)for (let period = 0; period < pps; period++) { slotHtml += `<div class="slot-period">${sessions > 1 ? (session === 0 ? 'S' : 'C') + ' ' : ''}${period + 1}</div>`; for (let day = 0; day < days; day++) { const slot = day * ppd + session * pps + period, key = day * sessions + session, locked = blocked.has(slot); slotHtml += `<button type="button" class="global-slot-lock ${locked ? 'is-locked' : ''}" data-global-slot="${slot}" data-global-session="${key}" onclick="toggleGlobalSlotLock(this)"><span class="constraint-state-stage"><span class="constraint-state-content ${locked ? 'is-blocked' : 'is-allowed'}">${constraintStateMarkup(locked, locked ? 'Đã khóa' : 'Cho phép')}</span></span></button>` } } slotGrid.innerHTML = slotHtml }
async function saveGlobalSessionLocks(button) {
  const sessions = [...document.querySelectorAll('[data-session-lock].is-locked')].map(button => Number(button.dataset.sessionLock)), slots = [...document.querySelectorAll('[data-global-slot].is-locked')].map(button => Number(button.dataset.globalSlot));
  setInlineActionState(button, 'loading', { idle: 'Lưu khóa lịch', loading: 'Đang lưu...' });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/session-locks`, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ sessions, slots }) }); const result = await r.json();
    if (r.ok) { await refresh(true); setInlineActionState(button, 'success', { idle: 'Lưu khóa lịch', success: 'Đã lưu' }, 1700); showInlineActionFeedback(button, result.removed ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.` : 'Khóa lịch đã được lưu.', 'success', 2800) }
    else { setInlineActionState(button, 'error', { idle: 'Lưu khóa lịch', error: 'Chưa lưu được' }, 2200); showInlineActionFeedback(button, result.message || result.detail || 'Không thể lưu khóa lịch.', 'error', 5000) }
  }
  catch { setInlineActionState(button, 'error', { idle: 'Lưu khóa lịch', error: 'Lỗi kết nối' }, 2200); showInlineActionFeedback(button, 'Mất kết nối tới máy chủ.', 'error', 5000) }
}
function renderConstraintSelectors() { renderGlobalSessionLocks(); const type = $('#constraintType'), ent = $('#constraintEntity'); if (!type || !ent) return; const rows = type.value === 'teacher' ? data.teachers : data.classes; const old = ent.value; ent.innerHTML = opts(rows); if ([...ent.options].some(o => o.value === old)) ent.value = old; type.onchange = () => { renderConstraintSelectors(); renderConstraintGrid() }; ent.onchange = renderConstraintGrid; renderConstraintGrid() }
function renderConstraintGrid() { const box = $('#constraintGrid'), type = $('#constraintType'), ent = $('#constraintEntity'); if (!box) return; if (!ent?.value) { box.innerHTML = '<div class="empty-state">Hãy thêm giáo viên hoặc lớp học trước khi thiết lập tiết tránh.</div>'; return } const obj = (type.value === 'teacher' ? data.teachers : data.classes).find(x => x.id === Number(ent.value)); const blocked = new Set(obj?.unavailable || []), days = data.project.days, pps = data.project.periods, sessions = data.project.sessions; let h = `<div class="timetable constraint-timetable" style="grid-template-columns:90px repeat(${days},minmax(110px,1fr))"><div class="cell head">Tiết</div>`; for (let d = 0; d < days; d++)h += `<div class="cell head">${['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'CN'][d]}</div>`; for (let s = 0; s < sessions; s++)for (let p = 0; p < pps; p++) { h += `<div class="cell period">${sessions > 1 ? (s ? 'C' : 'S') + ' ' : ''}${p + 1}</div>`; for (let d = 0; d < days; d++) { const slot = d * (sessions * pps) + s * pps + p, isBlocked = blocked.has(slot); h += `<div role="button" tabindex="0" aria-pressed="${isBlocked ? 'true' : 'false'}" data-cslot="${slot}" onclick="toggleConstraintCell(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();toggleConstraintCell(this)}" class="cell available constraint-state-cell ${isBlocked ? 'blocked' : ''}"><span class="constraint-state-stage"><span class="constraint-state-content ${isBlocked ? 'is-blocked' : 'is-allowed'}">${constraintStateMarkup(isBlocked, isBlocked ? 'Tiết tránh' : 'Có thể xếp')}</span></span></div>` } } h += '</div>'; box.innerHTML = h }
async function saveConstraints(button) {
  const entity = $('#constraintEntity'); if (!entity?.value) { setInlineActionState(button, 'error', { idle: 'Lưu ràng buộc', error: 'Chọn đối tượng' }, 1800); showInlineActionFeedback(button, 'Hãy chọn giáo viên hoặc lớp học trước.', 'error', 4200); return }
  const slots = [...document.querySelectorAll('[data-cslot].blocked')].map(x => Number(x.dataset.cslot)); setInlineActionState(button, 'loading', { idle: 'Lưu ràng buộc', loading: 'Đang lưu...' });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/constraints`, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ entity_type: $('#constraintType').value, entity_id: Number(entity.value), slots }) }); const result = await r.json();
    if (r.ok) { await refresh(true); setInlineActionState(button, 'success', { idle: 'Lưu ràng buộc', success: 'Đã lưu' }, 1700); showInlineActionFeedback(button, result.removed ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.` : 'Đã lưu tiết tránh.', 'success', 2800) }
    else { setInlineActionState(button, 'error', { idle: 'Lưu ràng buộc', error: 'Chưa lưu được' }, 2200); showInlineActionFeedback(button, result.message || result.detail || 'Không thể lưu tiết tránh.', 'error', 5000) }
  }
  catch { setInlineActionState(button, 'error', { idle: 'Lưu ràng buộc', error: 'Lỗi kết nối' }, 2200); showInlineActionFeedback(button, 'Mất kết nối tới máy chủ.', 'error', 5000) }
}
function preferenceSlotLabel(slot) { const ppd = data.project.sessions * data.project.periods, day = Math.floor(slot / ppd), inside = slot % ppd, session = Math.floor(inside / data.project.periods), period = inside % data.project.periods; return `${['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'][day]} · ${data.project.sessions > 1 ? (session ? 'Chiều' : 'Sáng') + ' · ' : ''}Tiết ${period + 1}` }
async function loadPreferenceInbox() { const box = $('#preferenceInbox'); if (!box) return; box.innerHTML = '<div class="empty-state">Đang tải nguyện vọng lịch sử…</div>'; const r = await fetch(`/api/projects/${PROJECT_ID}/preferences`); if (!r.ok) { box.innerHTML = '<div class="empty-state">Không thể tải nguyện vọng lịch sử.</div>'; return } const result = await r.json(); if (!result.items.length) { box.innerHTML = '<div class="empty-state">Không có nguyện vọng lịch sử.</div>'; return } const statuses = { pending: 'Chờ duyệt', accepted: 'Đã ghi nhận', rejected: 'Đã từ chối', superseded: 'Đã thay thế' }; box.innerHTML = `<div class="preference-list">${result.items.map(item => `<article class="preference-card"><div class="preference-card-head"><div><h3>${esc(item.teacher_name)}</h3><small>${esc(item.created_at.replace('T', ' '))}</small></div><span class="status status-${item.status}">${statuses[item.status] || esc(item.status)}</span></div><div class="preference-detail"><b>Tiết mong muốn</b><div class="slot-chips">${item.preferred_slots.length ? item.preferred_slots.map(slot => `<span class="slot-chip preferred">${preferenceSlotLabel(slot)}</span>`).join('') : '<span class="muted">Không đăng ký</span>'}</div></div><div class="preference-detail"><b>Tiết cần tránh</b><div class="slot-chips">${item.unavailable_slots.length ? item.unavailable_slots.map(slot => `<span class="slot-chip blocked">${preferenceSlotLabel(slot)}</span>`).join('') : '<span class="muted">Không đăng ký</span>'}</div></div>${item.note ? `<p class="preference-note">${esc(item.note)}</p>` : ''}${item.status === 'pending' ? `<div class="row end"><button class="btn ghost" onclick="reviewPreference(${item.id},'reject',this)">Từ chối</button><button class="btn" onclick="reviewPreference(${item.id},'accept',this)">Ghi nhận</button></div>` : ''}</article>`).join('')}</div>` }
async function reviewPreference(id, action, button) {
  const idle = action === 'accept' ? 'Ghi nhận' : 'Từ chối', loading = action === 'accept' ? 'Đang ghi nhận...' : 'Đang từ chối...', success = action === 'accept' ? 'Đã ghi nhận' : 'Đã từ chối'; setInlineActionState(button, 'loading', { idle, loading });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/preferences/${id}/review`, { method: 'POST', headers: operationHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ action }) }); const result = await r.json();
    if (r.ok) { setInlineActionState(button, 'success', { idle, success }); await wait(600); await refresh(true); await loadPreferenceInbox() }
    else { setInlineActionState(button, 'error', { idle, error: 'Chưa cập nhật' }, 2200); showInlineActionFeedback(button, result.message || result.detail || 'Không thể cập nhật nguyện vọng.', 'error', 5000) }
  }
  catch { setInlineActionState(button, 'error', { idle, error: 'Lỗi kết nối' }, 2200); showInlineActionFeedback(button, 'Mất kết nối tới máy chủ.', 'error', 5000) }
}
async function copyShare(button) {
  try { await navigator.clipboard.writeText(window.SHARE_URL); setInlineActionState(button, 'success', { idle: 'Chia sẻ', success: 'Đã sao chép' }, 1700) }
  catch { setInlineActionState(button, 'error', { idle: 'Chia sẻ', error: 'Không sao chép được' }, 2200) }
}
function markGlobalBlockedSlots() { const blocked = new Set(data.project.blocked_slots || []), sessions = data.project.sessions, pps = data.project.periods, ppd = sessions * pps; for (const slot of blocked) { const day = Math.floor(slot / ppd), inside = slot % ppd, session = Math.floor(inside / pps), start = day * ppd + session * pps, wholeSession = Array.from({ length: pps }, (_, index) => start + index).every(value => blocked.has(value)), label = wholeSession ? 'KHÓA BUỔI' : 'KHÓA TIẾT'; document.querySelectorAll(`[data-slot="${slot}"]`).forEach(cell => { cell.classList.add('global-locked-slot'); cell.title = wholeSession ? 'Buổi này đã bị khóa' : 'Tiết này đã bị khóa'; if (!cell.querySelector('.global-lock-label')) cell.insertAdjacentHTML('afterbegin', `<span class="global-lock-label">${label}</span>`) }) } }
const renderScheduleWithoutGlobalLocks = renderSchedule;
renderSchedule = function (...args) { renderScheduleWithoutGlobalLocks(...args); markGlobalBlockedSlots() };
renderAll();
renderScheduleSelectors();
renderConstraintSelectors();
activateRequestedWorkspaceTab();

entityModal?.addEventListener('close', () => { setEntityActionMessage(''); const button = $('#entitySubmitButton'); if (button) setInlineActionState(button, 'idle', { idle: 'Lưu' }) });

document.addEventListener('pointerdown', event => { const target = event.target.closest('.btn,.nav'); if (!target) return; const rect = target.getBoundingClientRect(), ripple = document.createElement('span'); ripple.className = 'button-ripple'; ripple.style.left = `${event.clientX - rect.left}px`; ripple.style.top = `${event.clientY - rect.top}px`; target.appendChild(ripple); setTimeout(() => ripple.remove(), 700) });
const DRAG_WHEEL_SCROLL_MULTIPLIER = 1.7;
const DRAG_EDGE_SCROLL_MULTIPLIER = 1.0;
const dragAutoScroll = { frame: 0 };
const pointerDrag = { active: false, pointerId: null, source: null, payload: '', ghost: null, target: null, lastX: 0, lastY: 0, startX: 0, startY: 0, offsetX: 0, offsetY: 0, didMove: false, oldUserSelect: '' };
function stopDragAutoScroll() { if (dragAutoScroll.frame) { cancelAnimationFrame(dragAutoScroll.frame); dragAutoScroll.frame = 0 } }
function dragScrollableAncestorAt(clientX = pointerDrag.lastX, clientY = pointerDrag.lastY, axis = 'y') {
  let node = document.elementFromPoint(clientX, clientY);
  while (node && node !== document.body && node !== document.documentElement) {
    if (node instanceof HTMLElement) {
      const style = getComputedStyle(node), overflow = axis === 'y' ? style.overflowY : style.overflowX;
      const canScroll = /auto|scroll|overlay/.test(overflow) && (axis === 'y' ? node.scrollHeight > node.clientHeight + 1 : node.scrollWidth > node.clientWidth + 1);
      if (canScroll) return node
    }
    node = node.parentElement
  }
  return null
}
function scrollElementBy(target, top = 0, left = 0) {
  if (!target) return false;
  const beforeTop = target.scrollTop, beforeLeft = target.scrollLeft;
  if (top) target.scrollTop = beforeTop + top;
  if (left) target.scrollLeft = beforeLeft + left;
  return target.scrollTop !== beforeTop || target.scrollLeft !== beforeLeft
}
function scrollDragViewport(top = 0, left = 0) {
  let moved = false;
  if (top) {
    const vertical = dragScrollableAncestorAt(pointerDrag.lastX, pointerDrag.lastY, 'y');
    if (vertical) moved = scrollElementBy(vertical, top, 0) || moved
  }
  if (left) {
    const horizontal = dragScrollableAncestorAt(pointerDrag.lastX, pointerDrag.lastY, 'x');
    if (horizontal) moved = scrollElementBy(horizontal, 0, left) || moved
  }
  if ((top || left) && !moved) {
    const scroller = document.scrollingElement || document.documentElement;
    moved = scrollElementBy(scroller, top, left) || moved;
    if (!moved && typeof window.scrollBy === 'function') window.scrollBy({ top, left, behavior: 'auto' })
  }
  return moved
}
function dragEdgeScrollSpeed() {
  if (!pointerDrag.active || !Number.isFinite(pointerDrag.lastY)) return 0;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0; if (!viewportHeight) return 0;
  const edge = Math.max(90, Math.min(150, viewportHeight * 0.16)), y = pointerDrag.lastY;
  if (y < edge) { const strength = Math.max(0, Math.min(1, (edge - y) / edge)); return -(3 + 17 * strength * strength) * DRAG_EDGE_SCROLL_MULTIPLIER }
  if (y > viewportHeight - edge) { const strength = Math.max(0, Math.min(1, (y - (viewportHeight - edge)) / edge)); return (3 + 17 * strength * strength) * DRAG_EDGE_SCROLL_MULTIPLIER }
  return 0
}
function clearPointerDropTarget() { if (pointerDrag.target) pointerDrag.target.classList.remove('drag-over'); pointerDrag.target = null }
function canDropPointerPayload(payload, target) {
  if (!payload || !target) return false;
  if (target.classList.contains('unscheduled-tray')) return !payload.startsWith('assignment:');
  if (target.classList.contains('cell') && target.classList.contains('available')) return !payload.startsWith('scheduled-assignment:');
  return false
}
function pointerDropTargetAt(clientX, clientY) {
  const hit = document.elementFromPoint(clientX, clientY), target = hit?.closest?.('.cell.available,.unscheduled-tray') || null;
  return canDropPointerPayload(pointerDrag.payload, target) ? target : null
}
function updatePointerDropTarget(clientX = pointerDrag.lastX, clientY = pointerDrag.lastY) {
  if (!pointerDrag.active) return;
  const next = pointerDropTargetAt(clientX, clientY); if (next === pointerDrag.target) return;
  clearPointerDropTarget(); pointerDrag.target = next; if (next) next.classList.add('drag-over')
}
function scrollDragPage(top = 0) {
  if (!top) return false;
  const root = document.scrollingElement || document.documentElement;
  const body = document.body;
  const current = Math.max(window.scrollY || 0, root?.scrollTop || 0, body?.scrollTop || 0);
  const docHeight = Math.max(root?.scrollHeight || 0, body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0);
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  const maxTop = Math.max(0, docHeight - viewportHeight);
  const next = Math.max(0, Math.min(maxTop, current + top));
  if (next !== current) {
    if (root) root.scrollTop = next;
    if (body && body !== root) body.scrollTop = next;
    window.scrollTo(window.scrollX || 0, next);
    return true
  }
  const content = document.querySelector('.workspace .content');
  if (content && content.scrollHeight > content.clientHeight + 1 && scrollElementBy(content, top, 0)) return true;
  const workspace = document.querySelector('.workspace');
  if (workspace && workspace.scrollHeight > workspace.clientHeight + 1 && scrollElementBy(workspace, top, 0)) return true;
  return false
}
function runDragAutoScroll() {
  if (!pointerDrag.active) { dragAutoScroll.frame = 0; return }
  const speed = dragEdgeScrollSpeed();
  if (speed) { scrollDragViewport(speed, 0); updatePointerDropTarget(pointerDrag.lastX, pointerDrag.lastY) }
  dragAutoScroll.frame = requestAnimationFrame(runDragAutoScroll)
}
function startDragAutoScroll() { if (pointerDrag.active && !dragAutoScroll.frame) dragAutoScroll.frame = requestAnimationFrame(runDragAutoScroll) }
function updateDragAutoScroll(clientY) { if (Number.isFinite(clientY)) pointerDrag.lastY = clientY; startDragAutoScroll() }
function normalizedWheelDelta(value, mode) { if (mode === 1) return value * 18; if (mode === 2) return value * (window.innerHeight || 600); return value }
function makePointerDragGhost(source, event) {
  const rect = source.getBoundingClientRect(), ghost = source.cloneNode(true);
  pointerDrag.offsetX = event.clientX - rect.left; pointerDrag.offsetY = event.clientY - rect.top;
  ghost.removeAttribute('data-drag-payload'); ghost.removeAttribute('id'); ghost.classList.remove('dragging'); ghost.setAttribute('aria-hidden', 'true');
  Object.assign(ghost.style, { position: 'fixed', left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`, boxSizing: 'border-box', margin: '0', zIndex: '2147483000', pointerEvents: 'none', opacity: '0.94', transform: 'rotate(1.5deg) scale(1.02)', boxShadow: '0 18px 42px rgba(15,23,42,.26)', transition: 'none' });
  document.body.appendChild(ghost); pointerDrag.ghost = ghost
}
function movePointerDragGhost(clientX, clientY) {
  if (!pointerDrag.ghost) return;
  pointerDrag.ghost.style.left = `${clientX - pointerDrag.offsetX}px`; pointerDrag.ghost.style.top = `${clientY - pointerDrag.offsetY}px`
}
function beginPointerDrag(event, source) {
  pointerDrag.active = true; pointerDrag.pointerId = event.pointerId; pointerDrag.source = source; pointerDrag.payload = source.dataset.dragPayload || ''; pointerDrag.lastX = pointerDrag.startX = event.clientX; pointerDrag.lastY = pointerDrag.startY = event.clientY; pointerDrag.didMove = false;
  pointerDrag.oldUserSelect = document.body.style.userSelect; document.body.style.userSelect = 'none'; source.classList.add('dragging'); document.body.classList.add('is-dragging'); makePointerDragGhost(source, event); movePointerDragGhost(event.clientX, event.clientY); updateDragAutoScroll(event.clientY); updatePointerDropTarget(event.clientX, event.clientY);
  try { source.setPointerCapture?.(event.pointerId) } catch { }
}
function clearPointerDrag() {
  stopDragAutoScroll(); clearPointerDropTarget(); pointerDrag.source?.classList.remove('dragging'); pointerDrag.ghost?.remove(); document.body.classList.remove('is-dragging'); document.body.style.userSelect = pointerDrag.oldUserSelect;
  pointerDrag.active = false; pointerDrag.pointerId = null; pointerDrag.source = null; pointerDrag.payload = ''; pointerDrag.ghost = null; pointerDrag.didMove = false; document.querySelectorAll('.drag-over').forEach(item => item.classList.remove('drag-over'))
}
function finishPointerDrag(event, cancel = false) {
  if (!pointerDrag.active || (event?.pointerId != null && pointerDrag.pointerId !== event.pointerId)) return;
  if (event?.clientX != null && event?.clientY != null) { pointerDrag.lastX = event.clientX; pointerDrag.lastY = event.clientY; updatePointerDropTarget(event.clientX, event.clientY) }
  const payload = pointerDrag.payload, target = pointerDrag.target, shouldDrop = !cancel && pointerDrag.didMove && target;
  clearPointerDrag();
  if (!shouldDrop) return;
  if (target.classList.contains('unscheduled-tray')) { dropToTrayPayload(payload); return }
  const slot = Number(target.dataset.slot); if (Number.isInteger(slot)) dropLessonPayload(payload, slot)
}
document.addEventListener('pointerdown', event => {
  if (window.READ_ONLY || event.button !== 0 || pointerDrag.active || event.target.closest('button,a,input,select,textarea,label')) return;
  const source = event.target.closest('[data-drag-payload]'); if (!source || !source.dataset.dragPayload) return;
  event.preventDefault(); beginPointerDrag(event, source)
}, { capture: true });
document.addEventListener('pointermove', event => {
  if (!pointerDrag.active || event.pointerId !== pointerDrag.pointerId) return;
  pointerDrag.lastX = event.clientX; pointerDrag.lastY = event.clientY;
  if (Math.hypot(event.clientX - pointerDrag.startX, event.clientY - pointerDrag.startY) > 3) pointerDrag.didMove = true;
  movePointerDragGhost(event.clientX, event.clientY); updatePointerDropTarget(event.clientX, event.clientY); updateDragAutoScroll(event.clientY); event.preventDefault()
}, { capture: true });
document.addEventListener('pointerup', event => finishPointerDrag(event, false), { capture: true });
document.addEventListener('pointercancel', event => finishPointerDrag(event, true), { capture: true });
window.addEventListener('blur', () => finishPointerDrag(null, true));
document.addEventListener('keydown', event => { if (event.key === 'Escape' && pointerDrag.active) { event.preventDefault(); finishPointerDrag(null, true) } }, { capture: true });
function handlePointerDragWheel(event) {
  if (!pointerDrag.active) return;
  const top = normalizedWheelDelta(event.deltaY, event.deltaMode) * DRAG_WHEEL_SCROLL_MULTIPLIER, left = normalizedWheelDelta(event.deltaX, event.deltaMode) * DRAG_WHEEL_SCROLL_MULTIPLIER; if (!top && !left) return;
  event.preventDefault(); event.stopPropagation(); pointerDrag.didMove = true;
  scrollDragViewport(top, left);
  requestAnimationFrame(() => {
    if (!pointerDrag.active) return;
    updatePointerDropTarget(pointerDrag.lastX, pointerDrag.lastY);
    updateDragAutoScroll(pointerDrag.lastY)
  })
}
window.addEventListener('wheel', handlePointerDragWheel, { capture: true, passive: false });
