import { bookAction, discoverPdfLessons, extractPages, openDocument, searchPdf, pdfPageCanvas } from './documents.js';
import { renderScene, preflightDeck } from './pptx/preview.js';
import { driveGeneration } from './generation.js';
import { resourceInfo, resourceHref, manualResource } from './resources.js';
import { setupVoice } from './voice.js';

const $ = selector => document.querySelector(selector);
const owner = document.body.dataset.owner;
const form = $('#lesson-form');
let deck = null;
let sources = [];
let batchDrafts = [];
const batchKey = 'studio-batch-' + owner;

function readBatchQueue() {
  try {
    const value = JSON.parse(localStorage.getItem(batchKey));
    return value?.owner === String(owner) && Array.isArray(value.items) ? value : null;
  } catch { return null; }
}
function renderBatchQueue() {
  const queue = readBatchQueue();
  $('#batch-queue').hidden = !queue?.items.length;
  if (queue) $('#batch-progress').textContent = `${queue.items.filter(item => item.completed).length}/${queue.items.length} bài hoàn tất${queue.requested > queue.items.length ? ' · mới lưu ' + queue.items.length + '/' + queue.requested + ' bản nháp của lô' : ''}${queue.paused ? ' · đã dừng để bạn kiểm tra hoặc tiếp tục' : ''}`;
}
function populateBatchLessons() {
  batchDrafts = []; $('#batch-preview').replaceChildren(); $('#batch-reviewed').checked = false;
  $('#batch-lessons').replaceChildren(...(activeDocument?.toc || []).map((item, index) => new Option(item.title + ' · trang PDF ' + item.page, String(index))));
}
let selectedSlide = 0;
let capabilities = {};
let working = false;
let editingInput = false;
let activeDocument = null;
let proposal = null;
let proposalStepId = null;
let outlineDraft = null;
let reviewedVersion = '';
let generationMode = 'automatic';
const kindLabels = { cover: 'Trang mở đầu', objectives: 'Mục tiêu', hook: 'Khởi động', section: 'Chuyển phần', concept: 'Khái niệm', process: 'Quy trình', compare: 'So sánh', map: 'Bản đồ', experiment: 'Thí nghiệm / mô phỏng', example: 'Ví dụ', chart: 'Biểu đồ', quiz: 'Trắc nghiệm', video: 'Video', summary: 'Tổng kết', sources: 'Nguồn tài liệu' };
const strictKinds = new Set(['cover', 'objectives', 'hook', 'section', 'concept', 'process', 'compare', 'example', 'quiz', 'summary', 'sources']);
const statusLabels = { draft: 'Bản nháp', planned: 'Đã có dàn ý', authoring: 'Đang soạn, đã lưu một phần', needs_review: 'Cần xác nhận dàn ý', needs_source_review: 'Cần rà soát nguồn', ready: 'Sẵn sàng tải' };

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function message(text, error = false) {
  const box = $('#studio-message');
  box.textContent = text;
  box.hidden = !text;
  box.dataset.error = String(error);
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 140000);
  try {
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRF-Token': $('meta[name=csrf-token]').content,
      ...options.headers,
    };
    const response = await fetch('/api/ai-slides' + path, { ...options, headers, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.message || (typeof data.detail === 'string' ? data.detail : 'Thông tin nhập chưa hợp lệ. Hãy kiểm tra các trường.');
      throw new Error((data.code ? `${detail} (${data.code})` : detail) + (data.step_id ? ` · Mã lượt: ${data.step_id}` : ''));
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Kết nối đang quá chậm. Hãy mở lại bài từ thư viện để kiểm tra bước đã lưu.');
    throw error;
  } finally { clearTimeout(timer); }
}

async function run(action) {
  if (working) return;
  working = true;
  const lock = locked => {
    document.querySelectorAll('input,select,textarea').forEach(input => {
      input.inert = locked;
      if (locked) input.setAttribute('aria-disabled', 'true'); else input.removeAttribute('aria-disabled');
    });
    if (locked) document.querySelectorAll('button').forEach(button => { button.disabled = button.id !== 'ocr-cancel'; });
  };
  lock(true);
  const observer = new MutationObserver(() => { if (working) lock(true); });
  observer.observe($('.studio-workspace'), { childList: true, subtree: true });
  try { await action(); }
  catch (error) { message(error.message || 'Thao tác chưa hoàn tất. Hãy thử lại.', true); }
  finally {
    observer.disconnect();
    working = false;
    lock(false);
    document.querySelectorAll('button').forEach(button => { button.disabled = button.dataset.unavailable === 'true'; });
  }
}

function showPane(name) {
  for (const pane of ['create', 'deck', 'usage']) $(`#${pane}-pane`).hidden = pane !== name;
}

async function refreshLibrary() {
  const items = await api('/decks');
  const list = $('#deck-list');
  list.replaceChildren();
  if (!items.length) list.append(element('p', 'Bài đã lưu sẽ xuất hiện ở đây.', 'muted'));
  for (const item of items) {
    const button = element('button', '', 'studio-deck-link');
    button.type = 'button';
    button.append(element('span', item.title), element('small', statusLabels[item.status] || item.status));
    button.setAttribute('aria-current', String(item.id === deck?.id));
    button.onclick = () => run(async () => {
      deck = await api('/decks/' + item.id);
      selectedSlide = 0;
      localStorage.setItem('studio-current-' + owner, deck.id);
      showDeck();
    });
    list.append(button);
  }
}

function renderSources() {
  $('#source-recognition').hidden = true;
  const list = $('#source-list');
  list.replaceChildren();
  const grouped = new Map();
  for (const source of sources) {
    const key = source.fingerprint || source.id;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(source);
  }
  for (const items of grouped.values()) {
    const section = element('details', '', 'studio-source');
    const first = items[0];
    section.append(element('summary', first.name + (first.page ? ` · ${items.length} trang đã chọn` : '')));
    const role = element('select');
    role.setAttribute('aria-label', 'Vai trò của ' + first.name);
    for (const [value, text] of [['primary', 'Nguồn chính'], ['reference', 'Tham khảo']]) {
      const option = element('option', text);
      option.value = value;
      role.append(option);
    }
    role.value = first.role;
    role.onchange = () => { items.forEach(source => { source.role = role.value; }); $('#cloud-consent').checked = false; $('#source-recognition').hidden = true; };
    const remove = element('button', 'Bỏ nguồn này', 'studio-text-button');
    remove.type = 'button';
    remove.onclick = () => { sources = sources.filter(source => !items.includes(source)); $('#cloud-consent').checked = false; renderSources(); };
    section.append(role, remove);
    for (const source of items) {
      if (source.page) section.append(element('strong', 'Trang PDF ' + source.page));
      const excerpt = element('textarea');
      excerpt.value = source.text;
      excerpt.rows = 5;
      excerpt.maxLength = 40000;
      excerpt.setAttribute('aria-label', 'Văn bản sẽ gửi AI từ ' + source.name + (source.page ? ' trang PDF ' + source.page : ''));
      excerpt.oninput = () => {
        source.text = excerpt.value;
        $('#cloud-consent').checked = false;
        $('#source-recognition').hidden = true;
      };
      section.append(excerpt);
    }
    list.append(section);
  }
  const length = sources.reduce((sum, source) => sum + source.text.length, 0);
  $('#source-count').textContent = length ? `${sources.length} đoạn nguồn · ${length.toLocaleString('vi-VN')} / 40.000 ký tự` : 'Chưa chọn tài liệu. Bạn có thể bắt đầu bằng tên bài.';
}

const metadataLabels = { subject: 'Môn học', grade: 'Khối / lớp', lesson_title: 'Tên bài', duration_minutes: 'Thời lượng (phút)' };

async function recognizeSources() {
  if (!sources.length) throw new Error('Hãy đọc trang tài liệu hoặc thêm văn bản trước khi nhận diện.');
  if (!$('#cloud-consent').checked) throw new Error('Hãy xem các đoạn đã chọn và đồng ý gửi tới máy chủ trước khi nhận diện.');
  const hints = Object.fromEntries(Object.keys(metadataLabels).map(key => [key, form.elements[key].value.trim()]));
  hints.duration_minutes = hints.duration_minutes ? Number(hints.duration_minutes) : null;
  hints.locked_fields = [...$('#field-locks').querySelectorAll('input:checked')].map(input => input.value);
  const original = JSON.stringify(sources);
  const result = await api('/analyze-sources', { method: 'POST', body: JSON.stringify({ sources, hints, consent: true }) });
  if (JSON.stringify(sources) !== original) throw new Error('Nguồn đã thay đổi trong khi nhận diện. Hãy kiểm tra và nhận diện lại.');
  const box = $('#source-recognition'); box.replaceChildren(); box.hidden = false;
  box.append(element('strong', 'Gợi ý từ tiêu đề rõ ràng trong nguồn'), element('p', 'Chỉ tự điền ô trống có một gợi ý. Thông tin đã nhập được giữ nguyên; mở nguồn để kiểm tra trích dẫn.'));
  let count = 0;
  for (const [field, items] of Object.entries(result.metadata)) {
    if (items.length === 1 && !form.elements[field].value.trim()) form.elements[field].value = items[0].value;
    for (const item of items) {
      count += 1;
      const row = element('article', '', 'studio-source');
      row.append(element('strong', `${metadataLabels[field]}: ${item.value}`),
        element('p', `${item.name}${item.page ? ' · trang PDF ' + item.page : ''}`), element('blockquote', item.quote));
      const apply = element('button', 'Dùng gợi ý này', 'btn ghost'); apply.type = 'button';
      apply.onclick = () => {
        const locked = [...$('#field-locks').querySelectorAll('input:checked')].some(input => input.value === field);
        if (locked && form.elements[field].value.trim()) { message('Thông tin này đang khóa. Bỏ khóa hoặc sửa trực tiếp trong biểu mẫu để thay đổi.', true); return; }
        form.elements[field].value = item.value;
        message('Đã dùng gợi ý. Kiểm tra thông tin bài trước khi lưu.');
      };
      row.append(apply); box.append(row);
    }
  }
  if (!count) box.append(element('p', 'Chưa thấy tiêu đề rõ ràng. Hãy nhập môn, lớp và tên bài; không tự suy đoán từ nội dung.'));
  if (result.metadata.lesson_title.length > 1) box.append(element('p', 'Phần đã chọn có nhiều tên bài. Chọn đúng bài hoặc thu hẹp nguồn trước khi soạn.'));
  message('Đã nhận diện nguồn đã chọn. Không gọi AI, không dùng lượt.');
}

function renderSourceReview() {
  const analysis = deck.source_analysis;
  const box = $('#source-conflicts'); box.replaceChildren();
  $('#inspect-sources').hidden = !deck.profile.sources.length || deck.busy;
  const insights = $('#source-intelligence'); insights.replaceChildren();
  const intelligence = deck.profile.source_intelligence;
  insights.hidden = !intelligence || intelligence.signature !== analysis?.signature;
  if (!insights.hidden) {
    insights.append(element('strong', 'Gợi ý phân tích nguồn bằng AI'), element('p', 'Trích dẫn đã đối chiếu văn bản. Gợi ý về ý nghĩa có thể sai; thông tin bài và các trường khóa được giữ nguyên. Muốn dùng metadata, chọn Sửa thông tin bài.'));
    for (const item of intelligence.metadata) {
      const source = deck.profile.sources.find(source => source.id === item.source_id);
      insights.append(element('p', `${metadataLabels[item.field] || 'Mục tiêu'}: ${item.value} · ${source?.name || ''}${source?.page ? ' · trang PDF ' + source.page : ''}`), element('blockquote', item.quote));
    }
    for (const warning of intelligence.warnings) insights.append(element('p', warning));
    if (!intelligence.conflicts.length) insights.append(element('p', 'AI chưa chỉ ra mâu thuẫn. Điều này không xác nhận nguồn đầy đủ hoặc đúng kiến thức.'));
  }
  $('#source-review').hidden = !analysis?.conflicts.length && !analysis?.overflow;
  $('#source-discard-label').hidden = !deck.blueprint && !deck.manifest;
  $('#source-discard').checked = false;
  if (analysis?.overflow) box.append(element('p', 'Có quá nhiều biểu thức hoặc thông tin khác nhau để rà soát trong một bài. Hãy thu hẹp các đoạn nguồn.'));
  for (const conflict of analysis?.conflicts || []) {
    const section = element('fieldset'); section.dataset.conflict = conflict.id;
    section.append(element('legend', conflict.label));
    for (const item of conflict.evidence) {
      const label = element('label', '', 'studio-source-choice');
      const radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'conflict-' + conflict.id;
      radio.value = item.id; radio.checked = item.id === conflict.selected_evidence_id;
      radio.required = true;
      // Non-matching metadata can only be changed in the lesson form, including locked fields.
      radio.disabled = !item.selectable;
      const detail = element('span');
      detail.append(element('strong', item.name + (item.page ? ' · trang PDF ' + item.page : '')), element('blockquote', item.quote));
      if (!item.selectable) detail.append(element('small', 'Muốn dùng giá trị này, sửa thông tin bài trước.'));
      label.append(radio, detail); section.append(label);
    }
    box.append(section);
  }
}

function profile() {
  const data = Object.fromEntries(new FormData(form));
  return {
    ...data,
    duration_minutes: Number(data.duration_minutes),
    slide_count: Number(data.slide_count),
    locked_fields: [...$('#field-locks').querySelectorAll('input:checked')].map(input => input.value),
    sources,
    consent: $('#cloud-consent').checked,
    training_consent: $('#training-consent').checked,
    generation_mode: generationMode,
  };
}

function headers() { return { 'If-Match': String(deck.version) }; }

async function saveProfile() {
  if (sources.length && form.elements.input_mode.value !== 'manual' && ['subject', 'grade', 'lesson_title'].some(key => !form.elements[key].value.trim())) await recognizeSources();
  if (!form.checkValidity()) {
    // Inert prevents edits during async work but must not prevent the browser
    // from focusing a missing required field before any request is made.
    form.querySelectorAll('input,select,textarea').forEach(input => { input.inert = false; input.removeAttribute('aria-disabled'); });
    form.reportValidity(); return false;
  }
  if (sources.length && !$('#cloud-consent').checked) throw new Error('Hãy xem nguồn đã chọn và đồng ý trước khi lưu các đoạn này lên tài khoản.');
  const payload = profile();
  if (editingInput && deck) deck = await api(`/decks/${deck.id}/input-profile`, { method: 'PATCH', headers: headers(), body: JSON.stringify(payload) });
  else deck = await api('/decks', { method: 'POST', body: JSON.stringify(payload) });
  editingInput = false;
  localStorage.setItem('studio-current-' + owner, deck.id);
  await refreshLibrary();
  return true;
}

async function generate(kind) {
  let result;
  try {
    result = await driveGeneration(deck, {
      firstStep: kind,
      onProgress: (step, current) => message(step === 'plan' ? 'AI đang xây dựng dàn ý…' : `AI đang soạn slide… Đã lưu ${current.manifest?.slides?.length || 0}/${current.profile.slide_count} slide.`),
      onDeck: current => { deck = current; showDeck(); },
      request: (step, current) => api(`/decks/${current.id}/${step}`, {
        method: 'POST', headers: { 'If-Match': String(current.version), 'Idempotency-Key': crypto.randomUUID() },
      }),
    });
  } catch (error) {
    // Read the saved state once after an ambiguous timeout. Never retry inference.
    try { deck = await api(`/decks/${deck.id}`); } catch { /* Keep the last confirmed snapshot. */ }
    showDeck();
    throw error;
  }
  await refreshLibrary();
  showDeck();
  const messages = {
    ready: 'Đã soạn xong bài và lưu đầy đủ. Hãy xem lại nội dung trước khi tải PowerPoint.',
    outline: 'Đã lưu dàn ý. Bạn có thể chỉnh lại trước khi soạn slide.',
    needs_review: 'Đã lưu dàn ý. Hãy rà soát các lưu ý trước khi tiếp tục soạn.',
    needs_source_review: 'Hãy rà soát thông tin nguồn trước khi tiếp tục gọi AI.',
    needs_consent: 'Chọn Sửa thông tin bài để xác nhận đồng ý gửi dữ liệu tới AI.',
    busy: 'Một lượt AI đang xử lý. Chọn lại bài từ thư viện để cập nhật; chưa gọi thêm lượt mới.',
    needs_replan: 'Dàn ý cũ cần được lập lại theo chế độ trích đoạn trước khi soạn.',
  };
  message(messages[result.state] || 'Đã lưu tiến độ bài giảng.');
}

function showDeck() {
  showPane('deck');
  $('#deck-title').textContent = deck.title;
  $('#deck-log').hidden = true;
  $('#outline-editor').hidden = true;
  $('#edit-outline').hidden = !deck.blueprint;
  $('#presentation-theme').value = deck.profile.theme;
  $('#presentation-motion').value = deck.profile.motion;
  $('#deck-status').textContent = `${statusLabels[deck.status] || deck.status} · Phiên bản ${deck.version}`;
  $('#edit-instruction').placeholder = ['strict', 'verified_expansion'].includes(deck.profile.grounding) ? 'Ví dụ chọn trích đoạn về công thức, đổi hoạt động đọc' : 'Ví dụ thêm một ví dụ gần gũi với học sinh';
  $('#ai-edit-form button').textContent = ['strict', 'verified_expansion'].includes(deck.profile.grounding) ? 'Chọn lại trích đoạn bằng AI (1 lượt)' : 'Đề xuất thay đổi bằng AI (1 lượt)';
  renderSourceReview();
  const ready = deck.status === 'ready' && Boolean(deck.manifest);
  const legacyStrict = ['strict', 'verified_expansion'].includes(deck.profile.grounding) && deck.blueprint && deck.blueprint.grounding_version !== 'extractive-v1';
  $('#replan-grounded').hidden = !legacyStrict || deck.source_analysis?.unresolved;
  $('#export-pptx').hidden = !ready;
  $('#export-pptx').textContent = nativeMotionAllowed() ? 'Tải PowerPoint có hiệu ứng' : 'Tải PowerPoint';
  $('#export-basic').hidden = !ready || !nativeMotionAllowed();
  $('#export-notes').hidden = !ready;
  $('#export-offline').hidden = !ready;
  $('#continue-deck').hidden = ready || deck.status === 'needs_review' || deck.source_analysis?.unresolved || legacyStrict;
  $('#continue-deck').textContent = deck.status === 'authoring' ? `Tiếp tục soạn (${deck.manifest.slides.length}/${deck.profile.slide_count})` : deck.blueprint ? 'Soạn slide từ dàn ý' : 'Tiếp tục tạo dàn ý';
  const review = $('#outline-review');
  review.replaceChildren();
  review.hidden = !deck.blueprint?.warnings?.length || deck.source_analysis?.unresolved;
  if (!review.hidden) {
    review.className = 'studio-notice';
    review.append(element('strong', 'Cần bạn kiểm tra trước khi soạn slide'));
    for (const warning of deck.blueprint.warnings) review.append(element('p', warning));
    const approve = element('button', 'Tôi đã kiểm tra, tiếp tục', 'btn');
    approve.type = 'button';
    approve.onclick = () => run(async () => {
      deck = await api(`/decks/${deck.id}/approve-outline`, { method: 'POST', headers: headers() });
      await generate('author');
    });
    review.append(approve);
  }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  $('#motion-notice').hidden = !ready || deck.profile.motion === 'none' || (capabilities.native_motion && !reduced);
  $('#motion-notice').textContent = capabilities.native_motion && reduced
    ? 'Thiết bị đang bật giảm chuyển động. Bài sẽ được xuất không có hiệu ứng động đối tượng và chuyển cảnh.'
    : 'Bản PowerPoint tương tác cơ bản – không có hiệu ứng động đối tượng. ' + (capabilities.native_motion_message || '');
  const slides = deck.manifest?.slides || deck.blueprint?.slides || [];
  const remembered = localStorage.getItem('studio-slide-' + deck.id);
  const rememberedIndex = slides.findIndex(slide => slide.id === remembered);
  if (rememberedIndex >= 0) selectedSlide = rememberedIndex;
  selectedSlide = Math.max(0, Math.min(selectedSlide, slides.length - 1));
  $('#slide-list').replaceChildren();
  slides.forEach((slide, index) => {
    const button = element('button', `${index + 1}. ${slide.title}`);
    button.type = 'button';
    button.setAttribute('aria-current', String(index === selectedSlide));
    button.onclick = () => { selectedSlide = index; localStorage.setItem('studio-slide-' + deck.id, slide.id); showDeck(); };
    $('#slide-list').append(button);
  });
  renderSlide(slides[selectedSlide]);
  $('#slide-form').hidden = !ready;
  $('#ai-edit-form').hidden = !ready;
  $('#edit-proposal').hidden = true;
  renderContentReview();
  if (deck.busy) message('Một lượt AI đang xử lý. Chọn lại bài trong thư viện để cập nhật kết quả.');
  else message('');
}

$('#presentation-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    deck = await api(`/decks/${deck.id}/presentation`, { method: 'PATCH', headers: headers(), body: JSON.stringify({ theme: $('#presentation-theme').value, motion: $('#presentation-motion').value }) });
    showDeck(); message('Đã lưu giao diện; nội dung bài giảng được giữ nguyên.');
  });
};

function readOutlineDraft() {
  outlineDraft.objectives = $('#outline-objectives').value.split('\n').map(value => value.trim()).filter(Boolean);
  for (const row of $('#outline-rows').children) {
    const slide = outlineDraft.slides.find(item => item.id === row.dataset.slideId);
    slide.title = row.querySelector('[name=outline_title]').value.trim();
    slide.kind = row.querySelector('[name=outline_kind]').value;
    slide.duration_seconds = Number(row.querySelector('[name=outline_seconds]').value);
    slide.source_ids = [...row.querySelectorAll('[name=outline_source]:checked')].map(input => input.value);
  }
}

function outlineTotal() {
  const total = [...$('#outline-rows').querySelectorAll('[name=outline_seconds]')].reduce((sum, input) => sum + Number(input.value), 0);
  const expected = deck.profile.duration_minutes * 60;
  $('#outline-total').textContent = `Tổng thời lượng: ${Math.floor(total / 60)} phút ${total % 60} giây / ${deck.profile.duration_minutes} phút đã chọn.`;
  $('#outline-total').dataset.error = String(Math.abs(total - expected) > 60);
}

function renderOutlineRows() {
  const rows = $('#outline-rows'); rows.replaceChildren();
  for (const [index, slide] of outlineDraft.slides.entries()) {
    const row = element('article', '', 'studio-outline-row'); row.dataset.slideId = slide.id;
    const heading = element('header'); heading.append(element('strong', `Slide ${index + 1}`));
    const moves = element('div');
    for (const [delta, label] of [[-1, 'Đưa slide lên'], [1, 'Đưa slide xuống']]) {
      const button = element('button', label, 'btn ghost'); button.type = 'button';
      button.disabled = index + delta < 0 || index + delta >= outlineDraft.slides.length;
      button.onclick = () => {
        const target = index + delta;
        if (target < 0 || target >= outlineDraft.slides.length) return;
        readOutlineDraft();
        [outlineDraft.slides[index], outlineDraft.slides[target]] = [outlineDraft.slides[target], outlineDraft.slides[index]];
        renderOutlineRows(); $('#outline-rows').children[target].querySelector('input').focus();
      };
      moves.append(button);
    }
    heading.append(moves); row.append(heading);
    const titleLabel = element('label', 'Tiêu đề');
    const title = element('input'); title.name = 'outline_title'; title.value = slide.title; title.maxLength = 160; title.required = true;
    titleLabel.append(title); row.append(titleLabel);
    const fields = element('div', '', 'studio-fields');
    const kindLabel = element('label', 'Mục đích slide'); const kind = element('select'); kind.name = 'outline_kind';
    for (const [value, label] of Object.entries(kindLabels)) {
      if (deck.profile.grounding === 'balanced' || strictKinds.has(value)) kind.append(new Option(label, value));
    }
    kind.value = slide.kind; kindLabel.append(kind);
    const durationLabel = element('label', 'Thời lượng (giây)'); const duration = element('input');
    Object.assign(duration, { name: 'outline_seconds', type: 'number', min: '0', max: '1200', step: '1', required: true, value: String(slide.duration_seconds) });
    duration.oninput = outlineTotal; durationLabel.append(duration); fields.append(kindLabel, durationLabel); row.append(fields);
    if (deck.profile.sources.length) {
      const references = element('fieldset'); references.append(element('legend', 'Đoạn nguồn dùng cho slide'));
      for (const source of deck.profile.sources) {
        const label = element('label'); const input = element('input');
        input.type = 'checkbox'; input.name = 'outline_source'; input.value = source.id; input.checked = slide.source_ids.includes(source.id);
        label.append(input, document.createTextNode(source.name + (source.page ? ` · trang PDF ${source.page}` : ''))); references.append(label);
      }
      row.append(references);
    }
    rows.append(row);
  }
  outlineTotal();
}

$('#edit-outline').onclick = () => {
  outlineDraft = structuredClone(deck.blueprint);
  $('#outline-objectives').value = outlineDraft.objectives.join('\n');
  const locked = deck.profile.locked_fields.includes('objectives');
  $('#outline-objectives').disabled = locked; $('#outline-lock-message').hidden = !locked;
  $('#outline-discard').checked = false;
  $('#outline-discard').required = Boolean(deck.manifest);
  $('#outline-discard-label').hidden = !deck.manifest;
  renderOutlineRows(); $('#outline-editor').hidden = false;
  $('#outline-editor').scrollIntoView({ block: 'start' });
};
$('#cancel-outline').onclick = () => { $('#outline-editor').hidden = true; outlineDraft = null; };
$('#outline-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    readOutlineDraft();
    deck = await api(`/decks/${deck.id}/outline`, { method: 'PATCH', headers: headers(), body: JSON.stringify({ blueprint: outlineDraft, discard_content: $('#outline-discard').checked }) });
    showDeck(); await refreshLibrary(); message('Đã lưu dàn ý. Bạn có thể tiếp tục soạn hoặc hoàn tác về phiên bản trước.');
  });
};

function renderContentReview() {
  const issues = deck.review || [];
  $('#content-review').hidden = !issues.length;
  const box = $('#content-review-items'); box.replaceChildren();
  for (const issue of issues) {
    const row = element('p');
    if (issue.slide_id) {
      const index = deck.manifest.slides.findIndex(slide => slide.id === issue.slide_id);
      const button = element('button', `Xem slide ${index + 1}`, 'studio-text-button'); button.type = 'button';
      button.onclick = () => { selectedSlide = index; localStorage.setItem('studio-slide-' + deck.id, issue.slide_id); showDeck(); };
      row.append(button);
    }
    row.append(document.createTextNode(issue.message)); box.append(row);
  }
  const warning = issues.some(issue => issue.severity === 'warning');
  $('#content-review-ack-label').hidden = !warning;
  $('#content-review-ack').checked = reviewedVersion === `${deck.id}:${deck.version}`;
}
$('#content-review-ack').onchange = () => { reviewedVersion = $('#content-review-ack').checked ? `${deck.id}:${deck.version}` : ''; };
function requireContentReview() {
  if ((deck.review || []).some(issue => issue.severity === 'warning') && !$('#content-review-ack').checked) throw new Error('Hãy rà soát các cảnh báo và đánh dấu xác nhận trước khi tải bài.');
}

$('#show-deck-log').onclick = () => run(async () => {
  const rows = await api(`/decks/${deck.id}/steps`);
  const panel = $('#deck-log');
  panel.replaceChildren(element('strong', 'Nhật ký xử lý bài giảng'));
  if (!rows.length) panel.append(element('p', 'Chưa có lượt gọi AI.'));
  for (const row of rows) {
    const entry = element('p');
    entry.append(element('strong', `${row.kind} · ${row.state} · ${new Date(row.created_at).toLocaleString('vi-VN')}`));
    entry.append(element('br'), document.createTextNode(`Model: ${row.model || 'chưa ghi nhận'} · Phiên bản đầu vào: ${row.input_version} · Mã lượt: ${row.id}`));
    if (row.error_code) entry.append(element('br'), document.createTextNode(`${row.error_code}: ${row.error_message || ''}`));
    panel.append(entry);
  }
  panel.hidden = false;
});

function renderSlide(slide) {
  const preview = $('#slide-preview');
  preview.replaceChildren();
  const evidence = $('#slide-evidence'); evidence.replaceChildren();
  evidence.hidden = !slide || !['strict', 'verified_expansion'].includes(deck.profile.grounding) || !deck.manifest;
  if (!evidence.hidden) {
    const report = deck.grounding_report?.find(item => item.slide_id === slide.id);
    evidence.append(element('strong', report?.verified ? 'Đã đối chiếu trích đoạn với nguồn' : 'Nội dung cần đối chiếu lại với nguồn'));
    evidence.append(element('p', report?.verified ? 'Đây là đối chiếu văn bản, không xác nhận kiến thức trong tài liệu đúng.' : 'Slide có thể thuộc bản cũ hoặc đã sửa tay. Hãy kiểm tra từng ý trước khi tải.'));
    const seen = new Set();
    for (const citation of report?.citations || []) {
      const key = citation.unit_id;
      if (seen.has(key)) continue;
      seen.add(key);
      const source = deck.profile.sources.find(item => item.id === citation.source_id);
      if (deck.profile.grounding === 'verified_expansion' && source?.role === 'reference') evidence.append(element('strong', 'Nguồn bổ sung do giáo viên chọn'));
      evidence.append(element('p', `${source?.name || citation.source_id}${citation.page ? ' · trang PDF ' + citation.page : ''}`), element('blockquote', citation.quote));
    }
  }
  if (!slide) { preview.append(element('p', 'Bản nháp đã lưu. Tiếp tục tạo dàn ý khi AI được cấu hình.')); return; }
  renderScene(preview, slide, deck, selectedSlide);
  if (deck.manifest) {
    $('#slide-title').value = slide.title;
    $('#slide-bullets').value = slide.bullets.join('\n');
    $('#slide-notes').value = slide.speaker_notes;
    $('#slide-resource').value = slide.resource_id || '';
    $('#resource-link-title').value = slide.manual_resource?.title || '';
    $('#resource-link-url').value = slide.manual_resource?.url || '';
    $('#manual-resource-editor').open = Boolean(slide.manual_resource);
    renderResourceDetails();
    $('#quiz-editor').hidden = slide.kind !== 'quiz';
    $('#chart-editor').hidden = slide.kind !== 'chart';
    $('#quiz-question').value = slide.question || '';
    $('#quiz-options').value = (slide.options || []).join('\n');
    fillQuizAnswers(slide.correct_option);
    $('#quiz-explanation').value = slide.explanation || '';
    if (slide.chart_data) {
      $('#chart-series').value = slide.chart_data.series_name;
      $('#chart-type').value = slide.chart_data.chart_type || 'bar';
      $('#chart-origin').value = slide.chart_data.data_origin;
      $('#chart-values').value = slide.chart_data.labels.map((label, index) => `${label} | ${slide.chart_data.values[index]}`).join('\n');
    }
  }
}

function fillQuizAnswers(selected = $('#quiz-correct').value) {
  const options = $('#quiz-options').value.split('\n').map(value => value.trim()).filter(Boolean);
  $('#quiz-correct').replaceChildren(...options.map((value, index) => new Option(`${String.fromCharCode(65 + index)}. ${value}`, String(index))));
  $('#quiz-correct').value = String(selected ?? 0);
}

function renderResourceDetails() {
  const box = $('#resource-details'); box.replaceChildren();
  let own;
  try { own = manualResource($('#resource-link-title').value, $('#resource-link-url').value.trim()); }
  catch (error) { box.hidden = false; box.append(element('p', error.message)); return; }
  const resource = own ? { label: own.title, description: 'Liên kết do giáo viên cung cấp.', credit: 'Giáo viên', internet: true, limitations: 'Chưa xác minh nội dung, quyền sử dụng hoặc khả năng truy cập.' } : resourceInfo($('#slide-resource').value);
  box.hidden = !resource;
  if (!resource) return;
  box.append(element('strong', resource.label), element('p', resource.description), element('p', 'Nguồn: ' + resource.credit));
  box.append(element('p', resource.internet ? 'Cần Internet; mở trên website nguồn, không nhúng trong PowerPoint.' : 'Mở cùng website Smart TKB. Khi tải PowerPoint về máy vẫn cần truy cập được website.'));
  const link = element('a', 'Mở học liệu để xem trước', 'studio-text-button');
  link.href = own?.url || resourceHref(resource.id, location.origin); link.target = '_blank'; link.rel = 'noopener noreferrer';
  box.append(link, element('p', resource.limitations));
}
$('#slide-resource').onchange = renderResourceDetails;
$('#resource-link-url').oninput = renderResourceDetails;
$('#resource-link-title').oninput = renderResourceDetails;
setupVoice({ start: $('#voice-start'), consent: $('#voice-consent'), transcript: $('#voice-transcript'), status: $('#voice-status'), apply: $('#voice-apply'), target: form.elements.must_include });
let ocrSource = null;
let ocrRun = 0;
async function doOCR(fromPDF) {
  const identity = ++ocrRun;
  const { recognizeImage, imageCanvas } = await import('./ocr.js');
  if (identity !== ocrRun) throw new Error('Đã dừng OCR.');
  $('#ocr-reviewed').checked = false; $('#ocr-text').value = ''; ocrSource = null;
  const pageNumber = Number($('#page-first').value);
  const file = $('#ocr-image').files[0];
  const canvas = fromPDF ? await pdfPageCanvas(pageNumber) : await imageCanvas(file);
  if (identity !== ocrRun) throw new Error('Đã dừng OCR.');
  $('#ocr-original').src = canvas.toDataURL('image/png'); $('#ocr-original').hidden = false;
  const result = await recognizeImage(canvas, (stage, percent) => { $('#ocr-status').textContent = `Đang nhận dạng trên thiết bị… ${percent}%`; });
  $('#ocr-text').value = result.text;
  ocrSource = { name: `${fromPDF ? activeDocument.name + ' · trang PDF ' + pageNumber : file.name} (OCR, giáo viên cần đối chiếu)`, page: fromPDF ? pageNumber : null };
  $('#ocr-status').textContent = `Đã có bản OCR${result.confidence === null ? '' : ' · chỉ số nhận dạng ' + Math.round(result.confidence) + '/100 (không phải xác suất đúng)'}. Hãy đối chiếu ảnh và sửa công thức/dấu trước khi thêm nguồn.`;
}
$('#ocr-image-start').onclick = () => run(() => doOCR(false));
$('#ocr-pdf-start').onclick = () => run(() => doOCR(true));
$('#ocr-cancel').onclick = async () => { ocrRun += 1; const { cancelOCR } = await import('./ocr.js'); cancelOCR(); };
$('#ocr-text').oninput = () => { $('#ocr-reviewed').checked = false; };
$('#ocr-add').onclick = () => run(async () => {
  if (!ocrSource || !$('#ocr-text').value.trim() || !$('#ocr-reviewed').checked) throw new Error('Hãy đọc ảnh, sửa và xác nhận đối chiếu kết quả OCR trước khi thêm.');
  sources.push({ id: 'ocr-' + crypto.randomUUID().slice(0, 12), fingerprint: '', role: 'reference', ...ocrSource, text: $('#ocr-text').value.trim() });
  $('#cloud-consent').checked = false; renderSources(); message('Đã thêm văn bản OCR đã xác nhận. Chỉ gửi phần chữ này tới AI khi bạn đồng ý.');
});
$('#quiz-options').oninput = () => fillQuizAnswers();

function startLesson(mode) {
  run(async () => {
    if (!$('#cloud-consent').checked) throw new Error('Hãy đồng ý gửi thông tin bài học tới AI trước khi tạo.');
    generationMode = mode;
    if (!await saveProfile()) return;
    showDeck();
    if (deck.source_analysis?.unresolved) { message('Đã lưu bản nháp. Hãy rà soát các thông tin khác nhau trước khi gọi AI.'); return; }
    await generate('plan');
  });
}
form.onsubmit = event => {
  event.preventDefault();
  startLesson('automatic');
};
$('#create-outline').onclick = () => startLesson('outline');
$('#save-draft').onclick = () => run(async () => { if (await saveProfile()) { showDeck(); message('Đã lưu bản nháp.'); } });
$('#recognize-source').onclick = () => run(recognizeSources);
$('#recognize-source-ai').onclick = () => run(async () => {
  if (!sources.length || !$('#cloud-consent').checked) throw new Error('Hãy thêm, xem và đồng ý gửi các đoạn đã chọn trước khi gọi AI.');
  if (editingInput && deck && (deck.blueprint || deck.manifest) && !confirm('Phân tích nguồn tạo bản nháp từ thông tin hiện tại; bài trước được giữ trong Hoàn tác. Tiếp tục?')) return;
  const sourceSnapshot = JSON.stringify(sources);
  const data = profile();
  const draft = { ...data, subject: data.subject || 'Chưa xác định', grade: data.grade || 'Chưa xác định', lesson_title: data.lesson_title || 'Bản phân tích nguồn',
    locked_fields: data.locked_fields.filter(key => String(data[key] || '').trim()) };
  deck = editingInput && deck ? await api(`/decks/${deck.id}/input-profile`, { method: 'PATCH', headers: headers(), body: JSON.stringify(draft) }) : await api('/decks', { method: 'POST', body: JSON.stringify(draft) });
  editingInput = true;
  localStorage.setItem('studio-current-' + owner, deck.id);
  message('Đã giữ bản nháp; AI đang phân tích nguồn đã chọn…');
  deck = await api(`/decks/${deck.id}/inspect-sources`, { method: 'POST', headers: { ...headers(), 'Idempotency-Key': crypto.randomUUID() }, body: '{}' });
  if (JSON.stringify(sources) !== sourceSnapshot) throw new Error('Nguồn đã đổi trong khi AI phân tích. Kết quả cũ được giữ trong bài nháp; kiểm tra và phân tích lại nguồn hiện tại trước khi dùng.');
  const box = $('#source-recognition'); box.replaceChildren(); box.hidden = false;
  box.append(element('strong', 'Gợi ý từ AI — kiểm tra trước khi dùng'), element('p', 'Trích dẫn đã đối chiếu văn bản; ý nghĩa có thể sai. Chỉ tự điền ô trống; thông tin đã nhập hoặc khóa được giữ.'));
  for (const item of deck.profile.source_intelligence?.metadata || []) {
    const input = form.elements[item.field];
    if (!input) continue;
    if (!input.value.trim()) input.value = item.value;
    const row = element('article', '', 'studio-source');
    row.append(element('strong', `${metadataLabels[item.field] || 'Mục tiêu'}: ${item.value}`), element('blockquote', item.quote));
    const apply = element('button', 'Dùng gợi ý này', 'btn ghost'); apply.type = 'button';
    apply.onclick = () => {
      if ([...$('#field-locks input:checked')].some(lock => lock.value === item.field) && input.value.trim()) { message('Trường đang khóa. Bỏ khóa hoặc sửa trực tiếp nếu muốn đổi.', true); return; }
      input.value = item.value;
    };
    row.append(apply); box.append(row);
  }
  if (!deck.profile.source_intelligence?.metadata.length) box.append(element('p', 'AI chưa có gợi ý đủ căn cứ. Nhập các trường còn thiếu hoặc chọn nguồn rõ hơn.'));
  await refreshLibrary(); message('Đã lưu phân tích nguồn. Kiểm tra metadata, lưu bài rồi rà soát những điểm khác nhau.');
});
$('#inspect-sources').onclick = () => run(async () => {
  const hasContent = Boolean(deck.blueprint || deck.manifest);
  if (hasContent && !confirm('Phân tích lại dùng 1 lượt AI và đưa bài về bản nháp để rà soát nguồn. Bản hiện tại có thể Hoàn tác. Tiếp tục?')) return;
  message('AI đang phân tích các đoạn nguồn đã chọn…');
  deck = await api(`/decks/${deck.id}/inspect-sources`, { method: 'POST', headers: { ...headers(), 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ discard_content: hasContent }) });
  showDeck(); await refreshLibrary(); message('Đã lưu gợi ý phân tích nguồn. Hãy kiểm tra các trích dẫn và lựa chọn ưu tiên.');
});
$('#source-review-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    const resolutions = [...$('#source-conflicts').querySelectorAll('fieldset')].map(section => {
      const selected = section.querySelector('input:checked');
      if (!selected) throw new Error('Hãy chọn thông tin ưu tiên cho từng điểm khác nhau.');
      return { conflict_id: section.dataset.conflict, evidence_id: selected.value };
    });
    deck = await api(`/decks/${deck.id}/source-review`, { method: 'PATCH', headers: headers(), body: JSON.stringify({ resolutions, discard_content: $('#source-discard').checked }) });
    showDeck(); await refreshLibrary(); message(deck.source_analysis?.unresolved ? 'Đã lưu lựa chọn. Vẫn còn nguồn cần rà soát; hãy thu hẹp đoạn tài liệu.' : 'Đã lưu thông tin ưu tiên. Bạn có thể tiếp tục tạo bài; kiến thức vẫn cần giáo viên kiểm tra.');
  });
};
$('#continue-deck').onclick = () => run(async () => {
  if (!deck.profile.consent) throw new Error('Chọn Sửa thông tin bài để xác nhận đồng ý gửi dữ liệu tới AI.');
  await generate(deck.blueprint ? 'author' : 'plan');
});
$('#replan-grounded').onclick = () => {
  if (!confirm('Lập lại dàn ý theo chế độ trích đoạn? Dàn ý và nội dung cũ được giữ trong lịch sử để hoàn tác.')) return;
  run(async () => { await generate('plan'); });
};
form.elements.grounding.onchange = () => { $('#grounding-help').hidden = form.elements.grounding.value === 'balanced'; };
$('#new-deck').onclick = () => {
  deck = null; sources = []; editingInput = false; selectedSlide = 0; form.reset();
  generationMode = 'automatic';
  localStorage.removeItem('studio-current-' + owner);
  renderSources(); showPane('create'); message('');
  form.elements.grounding.onchange();
};
$('#edit-input').onclick = () => {
  editingInput = true;
  generationMode = deck.profile.generation_mode || 'outline';
  for (const [name, value] of Object.entries(deck.profile)) {
    if (name === 'input_mode') $(`input[name=input_mode][value="${value}"]`).checked = true;
    else if (form.elements[name]) form.elements[name].value = value;
  }
  sources = structuredClone(deck.profile.sources);
  $('#cloud-consent').checked = false;
  $('#training-consent').checked = Boolean(deck.profile.training_consent);
  $('#field-locks').querySelectorAll('input').forEach(input => { input.checked = deck.profile.locked_fields.includes(input.value); });
  renderSources(); showPane('create');
  form.elements.grounding.onchange();
  message('Lưu thay đổi thông tin nguồn sẽ tạo bản nháp mới. Có thể hoàn tác về bài cũ.');
};

async function readFile(file, restored = null) {
  message('Đang đọc tài liệu trên thiết bị…');
  activeDocument = null;
  $('#pdf-picker').hidden = true;
  $('#cloud-consent').checked = false;
  activeDocument = await openDocument(file, { styleOnly: $('#pptx-import-mode').value === 'style' });
  populateBatchLessons();
  if (restored && restored.fingerprint !== activeDocument.fingerprint) throw new Error('Tệp khác fingerprint của sách đã lưu. Hãy chọn đúng bản PDF; chỉ mục cũ không được áp dụng.');
  $('#cloud-consent').checked = false;
  $('#pdf-picker').hidden = activeDocument.type !== 'pdf';
  $('#style-reference').hidden = activeDocument.type !== 'style';
  if (activeDocument.type === 'style') {
    const box = $('#style-reference'); box.replaceChildren();
    box.append(element('strong', 'Bảng màu theme: ' + activeDocument.name), element('p', 'Chỉ tham khảo màu trong tệp; không nhập nội dung, template, ảnh hoặc hiệu ứng. Bạn chọn có áp dụng theme gợi ý hay không.'));
    const palette = element('p');
    for (const color of activeDocument.colors) { const swatch = element('span', '#' + color); swatch.style.cssText = `display:inline-block;border-left:18px solid #${color};padding:4px 8px`; palette.append(swatch); }
    const apply = element('button', 'Dùng theme gần màu nhất', 'btn ghost'); apply.type = 'button';
    apply.onclick = () => { form.elements.theme.value = activeDocument.recommended; message('Đã chọn theme gợi ý trong biểu mẫu. Các nội dung khác được giữ.'); };
    box.append(palette, apply); message('Đã đọc bảng màu PPTX trên thiết bị; chưa gửi nội dung hoặc gọi AI.');
  } else if (activeDocument.type === 'pdf') {
    if (restored?.toc?.length) activeDocument.toc = restored.toc;
    populateBatchLessons();
    activeDocument.scope = restored?.scope || null;
    $('#book-search-results').hidden = true; $('#book-search-results').replaceChildren();
    $('#document-name').textContent = `${activeDocument.name} · ${activeDocument.pages} trang PDF`;
    $('#page-first').value = restored?.first || 1;
    $('#page-last').value = restored?.last || Math.min(8, activeDocument.pages);
    activeDocument.first = Number($('#page-first').value); activeDocument.last = Number($('#page-last').value);
    $('#page-first').max = activeDocument.pages;
    $('#page-last').max = activeDocument.pages;
    $('#book-toc').replaceChildren(new Option('Chọn khoảng trang bên dưới', ''));
    activeDocument.toc.forEach((item, index) => $('#book-toc').append(new Option(item.title + ' · trang PDF ' + item.page, String(index))));
    message(activeDocument.toc.length ? 'Chọn bài trong mục lục hoặc nhập khoảng trang PDF.' : 'Tệp chưa có bookmark. Chọn Nhận diện bài / chương trên thiết bị hoặc nhập khoảng trang.');
  } else {
    const sourceId = 'doc-' + activeDocument.fingerprint.slice(0, 16);
    sources = [...sources.filter(source => source.id !== sourceId), {
      id: sourceId, name: activeDocument.name, fingerprint: activeDocument.fingerprint,
      role: 'primary', page: null, text: activeDocument.text,
    }];
    renderSources(); message(activeDocument.warning || 'Đã trích văn bản. Mở nguồn bên dưới để kiểm tra.');
  }
}
$('#document-file').onchange = event => { if (event.target.files[0]) run(() => readFile(event.target.files[0])); };
$('#pptx-import-mode').onchange = () => { const file = $('#document-file').files[0]; if (file?.name.toLowerCase().endsWith('.pptx')) run(() => readFile(file)); };
for (const name of ['#page-first', '#page-last']) $(name).oninput = () => { if (activeDocument) activeDocument.scope = null; $('#book-toc').value = ''; };
async function rememberBookScope() {
  if (!activeDocument) return;
  activeDocument.first = Number($('#page-first').value); activeDocument.last = Number($('#page-last').value);
  await bookAction(owner, 'update', activeDocument);
}
$('#book-toc').onchange = event => {
  if (!event.target.value) return;
  const index = Number(event.target.value);
  const current = activeDocument.toc[index];
  activeDocument.scope = Number.isInteger(current.startOffset) ? current : null;
  $('#page-first').value = current.page;
  const next = activeDocument.toc.slice(index + 1).find(item => item.page > current.page);
  const endPage = current.endPage ? current.endPage - (current.endOffset === 0 && current.endPage > current.page ? 1 : 0) : next ? next.page - 1 : activeDocument.pages;
  $('#page-last').value = Math.min(endPage, current.page + 49);
  if (!form.elements.lesson_title.value.trim()) form.elements.lesson_title.value = current.title.slice(0, 240);
  run(async () => { await rememberBookScope(); message(activeDocument.scope ? 'Đã chọn phần bài theo tiêu đề, kể cả khi chung trang. Xem văn bản trích để kiểm tra ranh giới.' : 'Đã chọn khoảng trang từ bookmark. Kiểm tra phần trích trước khi gửi.'); });
};
$('#discover-lessons').onclick = () => run(async () => {
  const lessons = await discoverPdfLessons((number, total) => message(`Đang nhận diện tiêu đề trên thiết bị… ${number}/${total} trang.`));
  if (!lessons.length) { message('Chưa tìm thấy tiêu đề bài/chương rõ ràng trong lớp chữ. Hãy tìm từ khóa hoặc chọn trang bằng tay.'); return; }
  activeDocument.toc = lessons;
  populateBatchLessons();
  $('#book-toc').replaceChildren(new Option('Chọn gợi ý rồi kiểm tra khoảng trang', ''));
  lessons.forEach((item, index) => $('#book-toc').append(new Option(item.title + ' · trang PDF ' + item.page, String(index))));
  await rememberBookScope();
  message(`Đã tìm ${lessons.length} tiêu đề (tối đa 200). Đây là gợi ý từ lớp chữ; kiểm tra khoảng trang, nhất là khi nhiều bài bắt đầu cùng trang. Chưa gửi sách tới server.`);
});
$('#search-book').onclick = () => run(async () => {
  const query = $('#book-search-query').value.trim();
  const results = await searchPdf(query, (number, total) => message(`Đang tìm trong sách trên thiết bị… ${number}/${total} trang.`));
  const box = $('#book-search-results'); box.replaceChildren(); box.hidden = false;
  if (!results.length) box.append(element('p', 'Không tìm thấy trong lớp chữ PDF. Thử từ khóa khác hoặc chọn trang bằng tay.'));
  for (const result of results) {
    const button = element('button', `Chọn trang PDF ${result.page} · ${result.snippet}`); button.type = 'button';
    button.onclick = () => { activeDocument.scope = null; $('#page-first').value = result.page; $('#page-last').value = result.page; message('Đã chọn trang tìm thấy. Kiểm tra phạm vi rồi trích nội dung cần dùng.'); };
    box.append(button);
  }
  message(`Đã tìm trên thiết bị: ${results.length} trang phù hợp (hiển thị tối đa 40). Chưa gửi các trang này tới server.`);
});
$('#prepare-batch').onclick = () => run(async () => {
  if (activeDocument?.type !== 'pdf') throw new Error('Mở sách PDF và nhận diện mục lục trước.');
  const indices = [...$('#batch-lessons').selectedOptions].map(option => Number(option.value));
  if (!indices.length || indices.length > 20) throw new Error('Chọn 1–20 bài cho mỗi lô. Có thể chuẩn bị lô tiếp theo sau.');
  if (form.elements.lesson_title.value.trim() && $('#field-locks input[value=lesson_title]').checked) throw new Error('Bỏ khóa Tên bài để dùng tên riêng của từng bài trong lô.');
  batchDrafts = []; const box = $('#batch-preview'); box.replaceChildren(); $('#batch-reviewed').checked = false;
  for (const index of indices) {
    const item = activeDocument.toc[index];
    const next = activeDocument.toc.slice(index + 1).find(other => other.page > item.page);
    const last = item.endPage ? item.endPage - (item.endOffset === 0 && item.endPage > item.page ? 1 : 0) : next ? next.page - 1 : activeDocument.pages;
    if (last - item.page > 49) throw new Error('Một bài vượt 50 trang. Chọn phạm vi nhỏ hơn để soạn riêng.');
    const extracted = await extractPages(item.page, last, null, Number.isInteger(item.startOffset) ? item : null);
    const section = element('details'); section.open = true; section.append(element('summary', item.title));
    const fields = extracted.map(source => {
      const label = element('label', `${source.name} · trang PDF ${source.page}`);
      const input = document.createElement('textarea'); input.rows = 4; input.maxLength = 40000; input.value = source.text;
      input.oninput = () => { $('#batch-reviewed').checked = false; }; label.append(input); section.append(label);
      return { source, input };
    });
    batchDrafts.push({ title: item.title, fields }); box.append(section);
  }
  message('Đã trích riêng từng bài trên thiết bị. Kiểm tra/sửa văn bản và xác nhận trước khi lưu lô.');
});
async function resumeBatch() {
  const queue = readBatchQueue();
  if (!queue?.items.length) throw new Error('Chưa có lô bài đã lưu.');
  const { driveBatch } = await import('./batch.js');
  const result = await driveBatch(queue, {
    load: id => api('/decks/' + id),
    request: (step, current) => api(`/decks/${current.id}/${step}`, { method: 'POST', headers: { 'If-Match': String(current.version), 'Idempotency-Key': crypto.randomUUID() } }),
    persist: value => { localStorage.setItem(batchKey, JSON.stringify(value)); renderBatchQueue(); },
    onDeck: current => { deck = current; showDeck(); message(`Đang xử lý lô bài: ${current.title}`); },
  });
  await refreshLibrary(); renderBatchQueue();
  message(result.state === 'ready' ? 'Đã soạn xong lô bài. Mở từng bài để rà soát và tải tệp.' : 'Lô bài đã dừng để rà soát. Xem bài hiện tại, giải quyết cảnh báo rồi chủ động Tiếp tục lô bài.');
}
$('#start-batch').onclick = () => run(async () => {
  if (!batchDrafts.length || !$('#batch-reviewed').checked || !$('#cloud-consent').checked) throw new Error('Xem nguồn từng bài và bật cả xác nhận lô, đồng ý gửi AI trước khi bắt đầu.');
  const previous = readBatchQueue();
  if (previous?.items.some(item => !item.completed)) throw new Error('Còn lô chưa hoàn tất. Tiếp tục lô cũ hoặc Bỏ hàng đợi trước khi tạo lô mới.');
  const base = profile();
  if (!base.subject.trim() || !base.grade.trim()) throw new Error('Nhập môn và lớp dùng chung cho lô.');
  if (base.grounding === 'verified_expansion') throw new Error('Lô sách hiện dùng một nguồn chính mỗi bài. Chọn Cân bằng/Bám nguồn, hoặc soạn từng bài để thêm nguồn tham khảo.');
  const queue = { owner: String(owner), created_at: new Date().toISOString(), requested: batchDrafts.length, paused: null, items: [] };
  for (const item of batchDrafts) {
    const saved = await api('/decks', { method: 'POST', body: JSON.stringify({ ...base, lesson_title: item.title, sources: item.fields.map(({ source, input }) => ({ ...source, text: input.value.trim() })), generation_mode: 'automatic' }) });
    queue.items.push({ id: saved.id, title: saved.title, completed: false });
    localStorage.setItem(batchKey, JSON.stringify(queue)); renderBatchQueue();
  }
  await resumeBatch();
});
$('#resume-batch').onclick = () => run(resumeBatch);
$('#clear-batch').onclick = () => {
  if (!confirm('Bỏ danh sách hàng đợi trên thiết bị? Các bài đã lưu vẫn còn trong thư viện.')) return;
  localStorage.removeItem(batchKey); renderBatchQueue();
};
renderBatchQueue();
$('#extract-pages').onclick = () => run(async () => {
  const extracted = await extractPages(Number($('#page-first').value), Number($('#page-last').value),
    (page, last) => message(`Đang đọc trang ${page} / ${last} trên thiết bị…`), activeDocument?.scope);
  const ids = new Set(extracted.map(source => source.id));
  sources = [...sources.filter(source => !ids.has(source.id)), ...extracted];
  await rememberBookScope();
  $('#cloud-consent').checked = false;
  renderSources(); message('Đã đọc phần được chọn. Kiểm tra văn bản và công thức trước khi gửi AI.');
});
$('#add-paste').onclick = () => {
  const text = $('#pasted-source').value.trim();
  if (!text) return;
  sources.push({ id: 'paste-' + crypto.randomUUID().slice(0, 8), name: 'Văn bản đã dán', fingerprint: '', role: 'reference', page: null, text });
  $('#pasted-source').value = '';
  $('#cloud-consent').checked = false;
  renderSources();
};
$('#save-book').onclick = () => run(async () => {
  activeDocument.first = Number($('#page-first').value); activeDocument.last = Number($('#page-last').value);
  await bookAction(owner, 'save', activeDocument);
  navigator.storage?.persist?.().catch(() => {});
  message('Đã lưu sách trên thiết bị này. Đổi máy hoặc xóa dữ liệu trình duyệt sẽ cần chọn lại tệp.');
});
$('#show-books').onclick = () => run(async () => {
  const books = await bookAction(owner, 'list');
  const list = $('#book-list');
  list.hidden = false;
  list.replaceChildren();
  if (!books.length) list.append(element('p', 'Chưa có sách trên thiết bị này.'));
  for (const book of books) {
    const row = element('div');
    const open = element('button', book.name, 'studio-deck-link');
    open.type = 'button';
    open.onclick = () => run(async () => { showPane('create'); if (!book.file) throw new Error('Chọn Liên kết lại tệp để dùng sách này.'); await readFile(book.file, book); });
    const relink = element('button', 'Liên kết lại tệp', 'studio-text-button'); relink.type = 'button';
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.pdf'; input.hidden = true;
    relink.onclick = () => input.click();
    input.onchange = () => run(async () => { if (!input.files[0]) return; showPane('create'); await readFile(input.files[0], book); await bookAction(owner, 'save', activeDocument); message('Đã liên kết lại đúng tệp và khôi phục chỉ mục/phạm vi đã lưu.'); });
    const remove = element('button', 'Quên sách', 'studio-text-button');
    remove.onclick = () => run(async () => { await bookAction(owner, 'delete', book); row.remove(); });
    row.append(open, relink, input, remove); list.append(row);
  }
});
$('#slide-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    const slide = { ...deck.manifest.slides[selectedSlide], title: $('#slide-title').value.trim(),
      bullets: $('#slide-bullets').value.split('\n').map(line => line.trim()).filter(Boolean),
      speaker_notes: $('#slide-notes').value, resource_id: $('#slide-resource').value || null };
    slide.manual_resource = manualResource($('#resource-link-title').value, $('#resource-link-url').value.trim());
    if (slide.manual_resource) slide.resource_id = null;
    if (slide.kind === 'quiz') {
      slide.question = $('#quiz-question').value.trim();
      slide.options = $('#quiz-options').value.split('\n').map(value => value.trim()).filter(Boolean);
      slide.correct_option = $('#quiz-correct').value === '' ? null : Number($('#quiz-correct').value);
      slide.explanation = $('#quiz-explanation').value.trim();
    }
    if (slide.kind === 'chart') {
      const rows = $('#chart-values').value.split('\n').map(value => value.trim()).filter(Boolean).map(line => {
        const at = line.lastIndexOf('|');
        const label = line.slice(0, at).trim();
        const value = Number(line.slice(at + 1).trim().replace(',', '.'));
        if (at < 1 || !label || !line.slice(at + 1).trim() || !Number.isFinite(value)) throw new Error('Mỗi dòng biểu đồ cần nhãn | giá trị số hợp lệ.');
        return { label, value };
      });
      slide.chart_data = { chart_type: $('#chart-type').value, labels: rows.map(row => row.label), values: rows.map(row => row.value), series_name: $('#chart-series').value.trim(), data_origin: $('#chart-origin').value };
    }
    deck = await api(`/decks/${deck.id}/slides/${slide.id}`, { method: 'PATCH', headers: headers(), body: JSON.stringify({ slide }) });
    showDeck(); message('Đã lưu slide.');
  });
};
$('#ai-edit-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    const original = deck.manifest.slides[selectedSlide];
    message('AI đang đề xuất thay đổi cho slide đã chọn…');
    const response = await api(`/decks/${deck.id}/slides/${original.id}/propose`, {
      method: 'POST', headers: { ...headers(), 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ instruction: $('#edit-instruction').value }),
    });
    proposal = response.proposal;
    proposalStepId = response.step_id;
    const box = $('#edit-proposal');
    box.hidden = false;
    box.replaceChildren(element('h3', 'Xem thay đổi trước khi áp dụng'));
    for (const key of ['title', 'bullets', 'speaker_notes', 'teacher_action', 'student_action', 'question', 'options', 'correct_option', 'explanation']) {
      if (JSON.stringify(proposal[key]) === JSON.stringify(original[key])) continue;
      box.append(element('strong', ({ title: 'Tiêu đề', bullets: 'Nội dung', speaker_notes: 'Ghi chú', teacher_action: 'Hoạt động giáo viên', student_action: 'Hoạt động học sinh', question: 'Câu hỏi', options: 'Phương án', correct_option: 'Đáp án đúng', explanation: 'Giải thích' })[key]));
      const display = value => key === 'correct_option' ? (value == null ? 'Chưa có' : String.fromCharCode(65 + value)) : String(value);
      box.append(element('p', 'Hiện tại — ' + display(original[key])), element('p', 'Đề xuất — ' + display(proposal[key])));
    }
    const apply = element('button', 'Áp dụng thay đổi', 'btn');
    apply.onclick = () => run(async () => {
      deck = await api(`/decks/${deck.id}/slides/${proposal.id}`, {
        method: 'PATCH', headers: headers(), body: JSON.stringify({ slide: proposal, proposal_step_id: proposalStepId }),
      });
      showDeck();
    });
    box.append(apply); message('Đề xuất đã sẵn sàng để bạn kiểm tra.');
  });
};
$('#undo-deck').onclick = () => run(async () => {
  const items = await api(`/decks/${deck.id}/revisions`);
  const prior = items.find(item => item.version < deck.version);
  if (!prior) throw new Error('Chưa có phiên bản trước.');
  deck = await api(`/decks/${deck.id}/restore`, { method: 'POST', headers: headers(), body: JSON.stringify({ version: prior.version }) });
  showDeck(); await refreshLibrary();
});
$('#delete-deck').onclick = () => {
  if (!confirm('Xóa bài giảng này khỏi tài khoản?')) return;
  run(async () => {
    await api('/decks/' + deck.id, { method: 'DELETE', headers: headers() });
    deck = null; sources = []; editingInput = false; selectedSlide = 0;
    form.reset(); renderSources(); showPane('create');
    localStorage.removeItem('studio-current-' + owner);
    await refreshLibrary(); message('Đã xóa bài giảng.');
  });
};
function nativeMotionAllowed() {
  return Boolean(deck && capabilities.native_motion && deck.profile.motion !== 'none' && !matchMedia('(prefers-reduced-motion: reduce)').matches);
}

async function exportPowerPoint(nativeMotion) {
  if (deck.source_analysis?.unresolved) throw new Error('Hãy rà soát nguồn trước khi tải bài.');
  requireContentReview();
  const layoutIssues = await preflightDeck(deck);
  if (layoutIssues.length) throw new Error(`Chưa tải được: ${layoutIssues.map(item => 'slide ' + item.slide + ' ' + item.reason).join('; ')}. Rút gọn chữ hoặc đổi bố cục trước khi tải.`);
  message('Đang tạo PowerPoint trên thiết bị…');
  await new Promise(resolve => setTimeout(resolve, 40));
  const { buildDeck, download } = await import('./pptx/export.js');
  let bytes;
  try {
    bytes = await buildDeck(deck, { nativeMotion, origin: location.origin });
  } catch (error) {
    if (!nativeMotion) throw error;
    $('#motion-notice').hidden = false;
    $('#motion-notice').textContent = 'Không tạo được tệp có hiệu ứng. Bạn có thể chọn Tải PowerPoint không hiệu ứng để lấy bản cơ bản, hoặc thử lại.';
    $('#export-basic').hidden = false;
    throw new Error('Chưa xuất được bản có hiệu ứng. Bạn có thể chọn Tải PowerPoint không hiệu ứng.');
  }
  download(bytes, deck.title + '.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation');
  message(nativeMotion ? 'Đã tạo PowerPoint có hiệu ứng Appear/Fade và chuyển cảnh Fade.' : 'Đã tạo PowerPoint không hiệu ứng và gửi yêu cầu tải xuống trình duyệt.');
}
$('#export-pptx').onclick = () => run(() => exportPowerPoint(nativeMotionAllowed()));
$('#export-basic').onclick = () => run(() => exportPowerPoint(false));
$('#export-offline').onclick = () => run(async () => {
  if (deck.source_analysis?.unresolved) throw new Error('Rà soát nguồn trước khi đóng gói.');
  requireContentReview();
  const issues = await preflightDeck(deck);
  if (issues.length) throw new Error('Một số slide có chữ vượt khung. Rút gọn trước khi đóng gói offline.');
  message('Đang đóng gói PowerPoint, ghi chú và mô phỏng offline…');
  const { buildOfflinePackage } = await import('./offline.js');
  const { download } = await import('./pptx/export.js');
  const bytes = await buildOfflinePackage(deck, { nativeMotion: nativeMotionAllowed(), origin: location.origin });
  download(bytes, deck.title + '-offline.zip', 'application/zip');
  message('Đã tạo gói offline. Giải nén rồi mở index.html; PhET/video/web ngoài vẫn cần Internet.');
});
$('#export-json').onclick = () => run(async () => {
  const { download } = await import('./pptx/export.js');
  download(JSON.stringify(deck, null, 2), deck.title + '.json', 'application/json');
});
$('#export-notes').onclick = () => run(async () => {
  requireContentReview();
  const { download } = await import('./pptx/export.js');
  download(deck.manifest.slides.map((slide, index) => {
    const references = slide.source_ids.map(id => deck.profile.sources.find(source => source.id === id)).filter(Boolean).map(source => `${source.role === 'reference' ? '[Nguồn bổ sung] ' : ''}${source.name}${source.page ? ' · trang PDF ' + source.page : ''}`).join('\n');
    const resource = slide.manual_resource ? `${slide.manual_resource.title}\n${slide.manual_resource.url}\nDo giáo viên cung cấp; chưa xác minh nội dung/quyền sử dụng.` : slide.resource_id ? `${resourceInfo(slide.resource_id).label}\n${resourceInfo(slide.resource_id).credit}\n${resourceHref(slide.resource_id, location.origin)}` : '';
    return `${index + 1}. ${slide.title}\n${slide.speaker_notes}\n\nGiáo viên — ${slide.teacher_action}\nHọc sinh — ${slide.student_action}\n\nNguồn\n${references || 'Không có tài liệu tham chiếu'}${resource ? '\n\nHọc liệu (cần truy cập website)\n' + resource : ''}`;
  }).join('\n\n'), deck.title + '-ghi-chu.txt', 'text/plain;charset=utf-8');
});
if ($('#show-usage')) $('#show-usage').onclick = () => run(async () => {
  const [items, summary] = await Promise.all([api('/admin/usage'), api('/admin/summary')]);
  showPane('usage');
  $('#quota-description').textContent = `Tối đa ${capabilities.requests_per_user_day} lượt/người/ngày và ${capabilities.requests_per_site_day} lượt/toàn hệ thống/ngày. Lượt lỗi vẫn được tính. Ngày hạn mức theo UTC.`;
  $('#usage-list').replaceChildren();
  const totals = $('#usage-summary'); totals.replaceChildren();
  for (const [label, value] of [['Bài giảng đã lưu', summary.decks], ['Lượt xử lý đã ghi', summary.steps], ['Lượt xử lý lỗi', summary.failed_steps], ['Lượt hôm nay (' + summary.day_utc + ' UTC)', summary.requests_today + '/' + summary.site_limit]]) totals.append(element('dt', label), element('dd', String(value)));
  for (const model of summary.models) $('#usage-list').append(element('p', `${model.model} · ${model.status}: ${model.requests} lượt · ${model.input_tokens} token vào / ${model.output_tokens} token ra`));
  for (const item of items) $('#usage-list').append(element('p', `${item.created_at} · ${item.model} · ${item.status} · Mã tra cứu ${item.step_id}`));
});

run(async () => {
  capabilities = await api('/capabilities');
  $('#content-quality-notice').hidden = Boolean(capabilities.content_qa_approved);
  if (!capabilities.ai_configured) {
    $('#configuration-notice').hidden = false;
    $('#configuration-notice').textContent = 'AI chưa được cấu hình. Bạn có thể đọc tài liệu và lưu bản nháp. Quản trị viên cần thêm key và mô hình OpenRouter miễn phí trước khi tạo nội dung.';
  }
  await refreshLibrary();
  const saved = localStorage.getItem('studio-current-' + owner);
  if (saved) {
    try { deck = await api('/decks/' + saved); showDeck(); }
    catch { localStorage.removeItem('studio-current-' + owner); }
  }
});
