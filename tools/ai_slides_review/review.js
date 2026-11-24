(() => {
  'use strict';
  const packet = JSON.parse(document.querySelector('#packet').textContent);
  const $ = selector => document.querySelector(selector);
  const node = (tag, text) => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; return item; };
  const labels = { knowledge: 'Kiến thức', evidence: 'Phạm vi và chứng cứ', pedagogy: 'Phương pháp sư phạm', vietnamese: 'Tiếng Việt', resources: 'Học liệu', structure: 'Cấu trúc JSON' };
  const hardLabels = { invented_reference: 'Bịa nguồn hoặc trang SGK', locked_input_changed: 'Thay thông tin đã khóa', central_formula_wrong: 'Sai công thức trọng tâm' };
  const desktopLabels = { opens: 'Mở tệp không báo sửa', objects: 'Appear/Fade sau click trong cùng slide', transition: 'Chuyển cảnh Fade', links: 'Quiz và liên kết hoạt động nếu có', notes: 'Notes và nguồn còn đầy đủ', editable: 'Chữ/đối tượng chuẩn sửa được' };
  const key = 'studio-v4-human-review-' + packet.packet_id;
  const blank = record => ({ asset_hashes: record.assets, scores: Object.fromEntries(Object.keys(labels).map(k => [k, null])), hard_fails: Object.fromEntries(Object.keys(hardLabels).map(k => [k, 'pending'])), desktop: { version: '', checks: Object.fromEntries(Object.keys(desktopLabels).map(k => [k, 'pending'])) }, content_read: false, verdict: 'pending', notes: '' });
  let state = { schema_version: 1, packet_id: packet.packet_id, reviewer: { name: '', qualified_reviewer: false }, records: Object.fromEntries(packet.records.map(record => [record.id, blank(record)])) };
  let selected = packet.records.find(record => record.variant === 'edited') || packet.records[0];
  function message(text, error = false) { $('#message').textContent = text; $('#message').dataset.error = error; }
  const sameAssets = (a, b) => a && Object.keys(a).length === Object.keys(b).length && Object.keys(b).every(k => a[k] === b[k]);
  function checkedReport(value) {
    if (value.schema_version !== 1 || value.packet_id !== packet.packet_id || !value.records || !value.reviewer || typeof value.reviewer.name !== 'string' || value.reviewer.name.length > 120 || typeof value.reviewer.qualified_reviewer !== 'boolean') throw new Error('Kết quả không thuộc đúng bộ tệp hoặc sai định dạng.');
    if (Object.keys(value.records).length !== packet.records.length) throw new Error('Kết quả thiếu hoặc thừa phiên bản bài.');
    for (const record of packet.records) {
      const item = value.records[record.id];
      if (!item || !sameAssets(item.asset_hashes, record.assets) || typeof item.content_read !== 'boolean' || !['pending', 'revise', 'accept'].includes(item.verdict) || typeof item.notes !== 'string' || item.notes.length > 8000) throw new Error('Mã tệp hoặc nội dung phiếu không hợp lệ.');
      if (!item.scores || Object.keys(item.scores).length !== Object.keys(labels).length || Object.entries(packet.rubric).some(([k, max]) => item.scores[k] !== null && (!Number.isInteger(item.scores[k]) || item.scores[k] < 0 || item.scores[k] > max))) throw new Error('Điểm nằm ngoài thang chấm.');
      if (!item.hard_fails || Object.keys(item.hard_fails).length !== Object.keys(hardLabels).length || Object.keys(hardLabels).some(k => !['pending', 'clear', 'fail'].includes(item.hard_fails[k]))) throw new Error('Thiếu kiểm tra lỗi loại trực tiếp.');
      if (!item.desktop || typeof item.desktop.version !== 'string' || item.desktop.version.length > 120 || !item.desktop.checks || Object.keys(item.desktop.checks).length !== Object.keys(desktopLabels).length || Object.keys(desktopLabels).some(k => !['pending', 'pass', 'fail'].includes(item.desktop.checks[k]))) throw new Error('Phiếu PowerPoint Desktop không hợp lệ.');
    }
    return value;
  }
  try { const saved = localStorage.getItem(key); if (saved) state = checkedReport(JSON.parse(saved)); } catch { message('Không đọc được bản lưu trên thiết bị. Có thể mở lại JSON đã xuất.', true); }
  function accepted(item) { return item.verdict === 'accept' && item.content_read && Object.values(item.scores).every(v => v !== null) && Object.values(item.hard_fails).every(v => v === 'clear'); }
  function store() { try { localStorage.setItem(key, JSON.stringify(state)); } catch { message('Thiết bị chưa lưu được. Hãy bấm Lưu kết quả JSON để giữ tiến độ.', true); } updateProgress(); }
  function updateProgress() {
    const items = packet.records.filter(record => record.variant === $('#variant').value);
    $('#progress').textContent = `${items.filter(record => accepted(state.records[record.id])).length}/${items.length} phiên bản đã chấp nhận nội dung`;
    document.querySelectorAll('#lessons button').forEach(button => { const item = state.records[button.dataset.id]; button.querySelector('small').textContent = accepted(item) ? 'Đã chấp nhận nội dung' : item.verdict === 'revise' ? 'Cần sửa' : 'Chưa duyệt đủ'; });
    const scores = Object.values(state.records[selected.id].scores);
    $('#total').textContent = scores.every(v => v !== null) ? `Tổng: ${scores.reduce((a, b) => a + b, 0)}/100` : 'Chưa chấm đủ sáu mục';
  }
  function optionsControl(parent, labelsMap, values, current, change) {
    parent.replaceChildren();
    for (const [name, text] of Object.entries(labelsMap)) {
      const label = node('label', text), select = node('select'); select.dataset.field = name;
      for (const [value, caption] of values) { const option = node('option', caption); option.value = value; select.append(option); }
      select.value = current[name]; select.onchange = () => { change(name, select.value); store(); }; label.append(select); parent.append(label);
    }
  }
  function render() {
    const item = state.records[selected.id], variant = selected.variant;
    $('#subject').textContent = `${selected.subject} · ${selected.grade} · bài ${selected.case}`;
    $('#title').textContent = selected.title;
    $('#variant-notice').textContent = variant === 'raw' ? 'AI gốc: dùng để đánh giá model. Có thể còn lỗi kiến thức; chưa được giáo viên duyệt.' : 'Bản Codex đã biên tập: dùng để giáo viên rà soát. Chưa phải nội dung đã nghiệm thu; không dùng điểm bản này để nâng điểm model gốc.';
    $('#pptx-link').href = selected.pptx_path;
    $('#sources').open = false; $('#source-content').replaceChildren();
    const technical = selected.technical;
    $('#source-content').append(node('h3', 'Kết quả kiểm tra tự động'), node('p', `Cấu trúc nội dung: ${technical.json_schema_valid ? 'đạt' : 'chưa đạt'}. Gói PowerPoint/XML: ${technical.pptx_zip_xml_valid ? 'đọc được' : 'chưa đạt'}. ${technical.pptx_pages} trang, ${technical.notes} Notes.`), node('p', 'Kết quả kỹ thuật không xác nhận kiến thức đúng hoặc tệp chạy đúng trong PowerPoint Desktop.'));
    for (const finding of technical.findings) $('#source-content').append(node('p', `${finding.slide_id || 'Toàn bài'}: ${finding.message}`));
    for (const source of selected.profile.sources || []) { $('#source-content').append(node('h3', source.name), node('blockquote', source.text)); }
    if (selected.editorial_changes.length) { $('#source-content').append(node('h3', 'Nhật ký thay đổi của Codex')); for (const change of selected.editorial_changes) $('#source-content').append(node('p', `Slide ${change.slide}: ${change.reason}`)); }
    $('#slides').replaceChildren();
    selected.slides.forEach((slide, index) => {
      const card = node('article'); card.append(node('h3', `${index + 1}. ${slide.title}`));
      const imagePath = selected.deck_path.replace(/\.json$/, `-slide-${String(index + 1).padStart(2, '0')}.png`);
      if (selected.assets[imagePath]) { const image = node('img'); image.src = imagePath; image.alt = `Bản xem trước HTML slide ${index + 1}`; image.loading = 'lazy'; card.append(image); }
      const list = node('ul'); for (const bullet of slide.bullets || []) list.append(node('li', bullet)); card.append(list);
      if (slide.question) { card.append(node('h4', slide.kind === 'quiz' ? 'Quiz' : 'Trường quiz cũ không hiển thị ở layout này')); card.append(node('p', slide.question)); const choices = node('ol'); (slide.options || []).forEach((option, i) => choices.append(node('li', option + (i === slide.correct_option ? ' — được đánh dấu đúng' : '')))); card.append(choices, node('p', slide.explanation)); }
      const notes = node('div', `Notes: ${slide.speaker_notes || '(trống)'}\nGiáo viên: ${slide.teacher_action || '(trống)'}\nHọc sinh: ${slide.student_action || '(trống)'}`); notes.className = 'notes'; card.append(notes); $('#slides').append(card);
    });
    $('#scores').replaceChildren();
    for (const [name, caption] of Object.entries(labels)) { const label = node('label', `${caption} / ${packet.rubric[name]}`), input = node('input'); input.type = 'number'; input.min = 0; input.max = packet.rubric[name]; input.step = 1; input.dataset.score = name; input.value = item.scores[name] ?? ''; input.oninput = () => { const value = input.value === '' ? null : Number(input.value); item.scores[name] = value !== null && Number.isInteger(value) && value >= 0 && value <= packet.rubric[name] ? value : null; store(); }; label.append(input); $('#scores').append(label); }
    optionsControl($('#hard-fails'), hardLabels, [['pending', 'Chưa rà soát'], ['clear', 'Không thấy lỗi'], ['fail', 'Có lỗi']], item.hard_fails, (k, v) => { item.hard_fails[k] = v; });
    optionsControl($('#desktop-checks'), desktopLabels, [['pending', 'Chưa kiểm tra'], ['pass', 'Đạt sau khi tự thử'], ['fail', 'Có lỗi']], item.desktop.checks, (k, v) => { item.desktop.checks[k] = v; });
    $('#content-read').checked = item.content_read; $('#content-read').onchange = event => { item.content_read = event.target.checked; store(); };
    $('#verdict').value = item.verdict; $('#verdict').onchange = event => { item.verdict = event.target.value; store(); };
    $('#review-notes').value = item.notes; $('#review-notes').oninput = event => { item.notes = event.target.value; store(); };
    $('#office-version').value = item.desktop.version; $('#office-version').oninput = event => { item.desktop.version = event.target.value; store(); };
    $('#lessons').replaceChildren();
    const items = packet.records.filter(record => record.variant === variant);
    items.forEach(record => { const button = node('button', `${record.case}. ${record.title}`); button.append(node('small')); button.dataset.id = record.id; button.setAttribute('aria-current', String(record.id === selected.id)); button.onclick = () => { selected = record; render(); }; $('#lessons').append(button); });
    $('#previous').disabled = items.indexOf(selected) === 0; $('#next').disabled = items.indexOf(selected) === items.length - 1;
    updateProgress();
  }
  $('#variant').value = selected.variant;
  $('#variant').onchange = event => { selected = packet.records.find(record => record.variant === event.target.value && record.case === selected.case) || packet.records.find(record => record.variant === event.target.value); render(); };
  for (const [id, direction] of [['#previous', -1], ['#next', 1]]) $(id).onclick = () => { const items = packet.records.filter(record => record.variant === selected.variant); selected = items[items.indexOf(selected) + direction]; render(); };
  $('#reviewer-name').value = state.reviewer.name; $('#qualified-reviewer').checked = state.reviewer.qualified_reviewer;
  $('#reviewer-name').oninput = event => { state.reviewer.name = event.target.value; store(); };
  $('#qualified-reviewer').onchange = event => { state.reviewer.qualified_reviewer = event.target.checked; store(); };
  $('#rubric-form').onsubmit = event => event.preventDefault();
  $('#export-review').onclick = () => { if (!$('#rubric-form').reportValidity()) return; try { checkedReport(state); const data = { ...state, exported_at: new Date().toISOString() }; const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); const anchor = node('a'); anchor.href = url; anchor.download = 'v4-human-review.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); message('Đã xuất kết quả đang ghi. Mục để trống vẫn là chưa duyệt; báo cáo không tự bật phê duyệt trên website.'); } catch (error) { message(error.message, true); } };
  $('#import-review').onchange = async event => { try { const file = event.target.files[0]; if (!file) return; if (file.size > 2 * 1024 * 1024) throw new Error('Tệp JSON vượt 2 MB.'); const value = checkedReport(JSON.parse(await file.text())); state = value; $('#reviewer-name').value = state.reviewer.name; $('#qualified-reviewer').checked = state.reviewer.qualified_reviewer; store(); render(); message('Đã mở đúng kết quả của bộ tệp này.'); } catch (error) { message(error.message, true); } finally { event.target.value = ''; } };
  render();
})();
