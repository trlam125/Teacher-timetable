import { bookAction, discoverPdfLessons, extractPages, openDocument, searchPdf } from './documents.js';
import { renderScene } from './pptx/preview.js';

const $ = selector => document.querySelector(selector);
const owner = document.body.dataset.owner;
const form = $('#lesson-form');
let deck = null;
let sources = [];
let selectedSlide = 0;
let capabilities = {};
let working = false;
let editingInput = false;
let activeDocument = null;
let proposal = null;
let proposalStepId = null;
let outlineDraft = null;
let reviewedVersion = '';
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
  document.querySelectorAll('button').forEach(button => { button.disabled = true; });
  try { await action(); }
  catch (error) { message(error.message || 'Thao tác chưa hoàn tất. Hãy thử lại.', true); }
  finally {
    working = false;
    document.querySelectorAll('button').forEach(button => { button.disabled = false; });
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
  };
}

function headers() { return { 'If-Match': String(deck.version) }; }

async function saveProfile() {
  if (sources.length && form.elements.input_mode.value !== 'manual' && ['subject', 'grade', 'lesson_title'].some(key => !form.elements[key].value.trim())) await recognizeSources();
  if (!form.reportValidity()) return false;
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
  do {
    message(kind === 'plan' ? 'AI đang xây dựng dàn ý…' : `AI đang soạn slide… Đã lưu ${deck.manifest?.slides?.length || 0}/${deck.profile.slide_count} slide.`);
    deck = await api(`/decks/${deck.id}/${kind}`, {
      method: 'POST', headers: { ...headers(), 'Idempotency-Key': crypto.randomUUID() },
    });
    showDeck();
  } while (kind === 'author' && deck.status === 'authoring');
  await refreshLibrary();
  showDeck();
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
  $('#edit-instruction').placeholder = deck.profile.grounding === 'strict' ? 'Ví dụ chọn trích đoạn về công thức, đổi hoạt động đọc' : 'Ví dụ thêm một ví dụ gần gũi với học sinh';
  $('#ai-edit-form button').textContent = deck.profile.grounding === 'strict' ? 'Chọn lại trích đoạn bằng AI (1 lượt)' : 'Đề xuất thay đổi bằng AI (1 lượt)';
  renderSourceReview();
  const ready = deck.status === 'ready' && Boolean(deck.manifest);
  const legacyStrict = deck.profile.grounding === 'strict' && deck.blueprint && deck.blueprint.grounding_version !== 'extractive-v1';
  $('#replan-grounded').hidden = !legacyStrict || deck.source_analysis?.unresolved;
  $('#export-pptx').hidden = !ready;
  $('#export-pptx').textContent = nativeMotionAllowed() ? 'Tải PowerPoint có hiệu ứng' : 'Tải PowerPoint';
  $('#export-basic').hidden = !ready || !nativeMotionAllowed();
  $('#export-notes').hidden = !ready;
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
      if (deck.profile.grounding !== 'strict' || strictKinds.has(value)) kind.append(new Option(label, value));
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
  evidence.hidden = !slide || deck.profile.grounding !== 'strict' || !deck.manifest;
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
$('#quiz-options').oninput = () => fillQuizAnswers();

form.onsubmit = event => {
  event.preventDefault();
  run(async () => {
    if (!$('#cloud-consent').checked) throw new Error('Hãy đồng ý gửi thông tin bài học tới AI trước khi tạo.');
    if (!await saveProfile()) return;
    showDeck();
    if (deck.source_analysis?.unresolved) { message('Đã lưu bản nháp. Hãy rà soát các thông tin khác nhau trước khi gọi AI.'); return; }
    await generate('plan');
  });
};
$('#save-draft').onclick = () => run(async () => { if (await saveProfile()) { showDeck(); message('Đã lưu bản nháp.'); } });
$('#recognize-source').onclick = () => run(recognizeSources);
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
form.elements.grounding.onchange = () => { $('#grounding-help').hidden = form.elements.grounding.value !== 'strict'; };
$('#new-deck').onclick = () => {
  deck = null; sources = []; editingInput = false; selectedSlide = 0; form.reset();
  localStorage.removeItem('studio-current-' + owner);
  renderSources(); showPane('create'); message('');
  form.elements.grounding.onchange();
};
$('#edit-input').onclick = () => {
  editingInput = true;
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

async function readFile(file) {
  message('Đang đọc tài liệu trên thiết bị…');
  activeDocument = await openDocument(file);
  $('#cloud-consent').checked = false;
  $('#pdf-picker').hidden = activeDocument.type !== 'pdf';
  if (activeDocument.type === 'pdf') {
    $('#book-search-results').hidden = true; $('#book-search-results').replaceChildren();
    $('#document-name').textContent = `${activeDocument.name} · ${activeDocument.pages} trang PDF`;
    $('#page-first').value = 1;
    $('#page-last').value = Math.min(8, activeDocument.pages);
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
    renderSources(); message('Đã trích văn bản. Mở nguồn bên dưới để kiểm tra.');
  }
}
$('#document-file').onchange = event => { if (event.target.files[0]) run(() => readFile(event.target.files[0])); };
$('#book-toc').onchange = event => {
  if (!event.target.value) return;
  const index = Number(event.target.value);
  const current = activeDocument.toc[index];
  $('#page-first').value = current.page;
  const next = activeDocument.toc.slice(index + 1).find(item => item.page > current.page);
  $('#page-last').value = Math.min(next ? next.page - 1 : activeDocument.pages, current.page + 49);
  if (!form.elements.lesson_title.value.trim()) form.elements.lesson_title.value = current.title.slice(0, 240);
};
$('#discover-lessons').onclick = () => run(async () => {
  const lessons = await discoverPdfLessons((number, total) => message(`Đang nhận diện tiêu đề trên thiết bị… ${number}/${total} trang.`));
  if (!lessons.length) { message('Chưa tìm thấy tiêu đề bài/chương rõ ràng trong lớp chữ. Hãy tìm từ khóa hoặc chọn trang bằng tay.'); return; }
  activeDocument.toc = lessons;
  $('#book-toc').replaceChildren(new Option('Chọn gợi ý rồi kiểm tra khoảng trang', ''));
  lessons.forEach((item, index) => $('#book-toc').append(new Option(item.title + ' · trang PDF ' + item.page, String(index))));
  message(`Đã tìm ${lessons.length} tiêu đề (tối đa 200). Đây là gợi ý từ lớp chữ; kiểm tra khoảng trang, nhất là khi nhiều bài bắt đầu cùng trang. Chưa gửi sách tới server.`);
});
$('#search-book').onclick = () => run(async () => {
  const query = $('#book-search-query').value.trim();
  const results = await searchPdf(query, (number, total) => message(`Đang tìm trong sách trên thiết bị… ${number}/${total} trang.`));
  const box = $('#book-search-results'); box.replaceChildren(); box.hidden = false;
  if (!results.length) box.append(element('p', 'Không tìm thấy trong lớp chữ PDF. Thử từ khóa khác hoặc chọn trang bằng tay.'));
  for (const result of results) {
    const button = element('button', `Chọn trang PDF ${result.page} · ${result.snippet}`); button.type = 'button';
    button.onclick = () => { $('#page-first').value = result.page; $('#page-last').value = result.page; message('Đã chọn trang tìm thấy. Kiểm tra phạm vi rồi trích nội dung cần dùng.'); };
    box.append(button);
  }
  message(`Đã tìm trên thiết bị: ${results.length} trang phù hợp (hiển thị tối đa 40). Chưa gửi các trang này tới server.`);
});
$('#extract-pages').onclick = () => run(async () => {
  const extracted = await extractPages(Number($('#page-first').value), Number($('#page-last').value),
    (page, last) => message(`Đang đọc trang ${page} / ${last} trên thiết bị…`));
  const ids = new Set(extracted.map(source => source.id));
  sources = [...sources.filter(source => !ids.has(source.id)), ...extracted];
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
    open.onclick = () => run(async () => { showPane('create'); await readFile(book.file); });
    const remove = element('button', 'Quên sách', 'studio-text-button');
    remove.onclick = () => run(async () => { await bookAction(owner, 'delete', book); row.remove(); });
    row.append(open, remove); list.append(row);
  }
});
$('#slide-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    const slide = { ...deck.manifest.slides[selectedSlide], title: $('#slide-title').value.trim(),
      bullets: $('#slide-bullets').value.split('\n').map(line => line.trim()).filter(Boolean),
      speaker_notes: $('#slide-notes').value, resource_id: $('#slide-resource').value || null };
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
$('#export-json').onclick = () => run(async () => {
  const { download } = await import('./pptx/export.js');
  download(JSON.stringify(deck, null, 2), deck.title + '.json', 'application/json');
});
$('#export-notes').onclick = () => run(async () => {
  requireContentReview();
  const { download } = await import('./pptx/export.js');
  download(deck.manifest.slides.map((slide, index) => `${index + 1}. ${slide.title}\n${slide.speaker_notes}\n\nGiáo viên — ${slide.teacher_action}\nHọc sinh — ${slide.student_action}`).join('\n\n'), deck.title + '-ghi-chu.txt', 'text/plain;charset=utf-8');
});
if ($('#show-usage')) $('#show-usage').onclick = () => run(async () => {
  const items = await api('/admin/usage');
  showPane('usage');
  $('#quota-description').textContent = `Tối đa ${capabilities.requests_per_user_day} lượt/người/ngày và ${capabilities.requests_per_site_day} lượt/toàn hệ thống/ngày. Lượt lỗi vẫn được tính. Ngày hạn mức theo UTC.`;
  $('#usage-list').replaceChildren();
  for (const item of items) $('#usage-list').append(element('p', `${item.created_at} · ${item.model} · ${item.status} · Mã tra cứu ${item.step_id}`));
});

run(async () => {
  capabilities = await api('/capabilities');
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
