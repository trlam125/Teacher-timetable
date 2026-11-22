import { bookAction, extractPages, openDocument } from './documents.js';
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
const statusLabels = { draft: 'Bản nháp', planned: 'Đã có dàn ý', authoring: 'Đang soạn, đã lưu một phần', needs_review: 'Cần xác nhận dàn ý', ready: 'Sẵn sàng tải' };

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
    role.onchange = () => { items.forEach(source => { source.role = role.value; }); $('#cloud-consent').checked = false; };
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
      };
      section.append(excerpt);
    }
    list.append(section);
  }
  const length = sources.reduce((sum, source) => sum + source.text.length, 0);
  $('#source-count').textContent = length ? `${sources.length} đoạn nguồn · ${length.toLocaleString('vi-VN')} / 40.000 ký tự` : 'Chưa chọn tài liệu. Bạn có thể bắt đầu bằng tên bài.';
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
  $('#deck-status').textContent = `${statusLabels[deck.status] || deck.status} · Phiên bản ${deck.version}`;
  const ready = deck.status === 'ready' && Boolean(deck.manifest);
  $('#export-pptx').hidden = !ready;
  $('#export-notes').hidden = !ready;
  $('#continue-deck').hidden = ready || deck.status === 'needs_review';
  $('#continue-deck').textContent = deck.status === 'authoring' ? `Tiếp tục soạn (${deck.manifest.slides.length}/${deck.profile.slide_count})` : deck.blueprint ? 'Soạn slide từ dàn ý' : 'Tiếp tục tạo dàn ý';
  const review = $('#outline-review');
  review.replaceChildren();
  review.hidden = !deck.blueprint?.warnings?.length;
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
  $('#motion-notice').hidden = !ready || deck.profile.motion === 'none' || capabilities.native_motion;
  $('#motion-notice').textContent = 'Bản PowerPoint tương tác cơ bản – không có hiệu ứng động đối tượng. ' + (capabilities.native_motion_message || '');
  const slides = deck.manifest?.slides || deck.blueprint?.slides || [];
  selectedSlide = Math.max(0, Math.min(selectedSlide, slides.length - 1));
  $('#slide-list').replaceChildren();
  slides.forEach((slide, index) => {
    const button = element('button', `${index + 1}. ${slide.title}`);
    button.type = 'button';
    button.setAttribute('aria-current', String(index === selectedSlide));
    button.onclick = () => { selectedSlide = index; showDeck(); };
    $('#slide-list').append(button);
  });
  renderSlide(slides[selectedSlide]);
  $('#slide-form').hidden = !ready;
  $('#ai-edit-form').hidden = !ready;
  $('#edit-proposal').hidden = true;
  if (deck.busy) message('Một lượt AI đang xử lý. Chọn lại bài trong thư viện để cập nhật kết quả.');
  else message('');
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
  if (!slide) { preview.append(element('p', 'Bản nháp đã lưu. Tiếp tục tạo dàn ý khi AI được cấu hình.')); return; }
  renderScene(preview, slide, deck, selectedSlide);
  if (deck.manifest) {
    $('#slide-title').value = slide.title;
    $('#slide-bullets').value = slide.bullets.join('\n');
    $('#slide-notes').value = slide.speaker_notes;
  }
}

form.onsubmit = event => {
  event.preventDefault();
  run(async () => {
    if (!$('#cloud-consent').checked) throw new Error('Hãy đồng ý gửi thông tin bài học tới AI trước khi tạo.');
    if (!await saveProfile()) return;
    showDeck();
    await generate('plan');
  });
};
$('#save-draft').onclick = () => run(async () => { if (await saveProfile()) { showDeck(); message('Đã lưu bản nháp.'); } });
$('#continue-deck').onclick = () => run(async () => {
  if (!deck.profile.consent) throw new Error('Chọn Sửa thông tin bài để xác nhận đồng ý gửi dữ liệu tới AI.');
  await generate(deck.blueprint ? 'author' : 'plan');
});
$('#new-deck').onclick = () => {
  deck = null; sources = []; editingInput = false; selectedSlide = 0; form.reset();
  localStorage.removeItem('studio-current-' + owner);
  renderSources(); showPane('create'); message('');
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
  message('Lưu thay đổi thông tin nguồn sẽ tạo bản nháp mới. Có thể hoàn tác về bài cũ.');
};

async function readFile(file) {
  message('Đang đọc tài liệu trên thiết bị…');
  activeDocument = await openDocument(file);
  $('#cloud-consent').checked = false;
  $('#pdf-picker').hidden = activeDocument.type !== 'pdf';
  if (activeDocument.type === 'pdf') {
    $('#document-name').textContent = `${activeDocument.name} · ${activeDocument.pages} trang PDF`;
    $('#page-first').value = 1;
    $('#page-last').value = Math.min(8, activeDocument.pages);
    $('#page-first').max = activeDocument.pages;
    $('#page-last').max = activeDocument.pages;
    $('#book-toc').replaceChildren(new Option('Chọn khoảng trang bên dưới', ''));
    activeDocument.toc.forEach((item, index) => $('#book-toc').append(new Option(item.title + ' · trang PDF ' + item.page, String(index))));
    message(activeDocument.toc.length ? 'Chọn bài trong mục lục hoặc nhập khoảng trang PDF.' : 'Tệp chưa có bookmark. Hãy xem sách và nhập đúng khoảng trang bài học.');
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
      speaker_notes: $('#slide-notes').value };
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
    const box = $('#edit-proposal');
    box.hidden = false;
    box.replaceChildren(element('h3', 'Xem thay đổi trước khi áp dụng'));
    for (const key of ['title', 'bullets', 'speaker_notes', 'question', 'options', 'explanation']) {
      if (JSON.stringify(proposal[key]) === JSON.stringify(original[key])) continue;
      box.append(element('strong', ({ title: 'Tiêu đề', bullets: 'Nội dung', speaker_notes: 'Ghi chú', question: 'Câu hỏi', options: 'Phương án', explanation: 'Giải thích' })[key]));
      box.append(element('p', 'Hiện tại — ' + String(original[key])), element('p', 'Đề xuất — ' + String(proposal[key])));
    }
    const apply = element('button', 'Áp dụng thay đổi', 'btn');
    apply.onclick = () => run(async () => {
      deck = await api(`/decks/${deck.id}/slides/${proposal.id}`, {
        method: 'PATCH', headers: headers(), body: JSON.stringify({ slide: proposal }),
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
$('#export-pptx').onclick = () => run(async () => {
  message('Đang tạo PowerPoint trên thiết bị…');
  await new Promise(resolve => setTimeout(resolve, 40));
  const { buildDeck, download } = await import('./pptx/export.js');
  const bytes = await buildDeck(deck, { nativeMotion: capabilities.native_motion && !matchMedia('(prefers-reduced-motion: reduce)').matches, origin: location.origin });
  download(bytes, deck.title + '.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation');
  message('Đã tạo tệp PowerPoint và gửi yêu cầu tải xuống trình duyệt.');
});
$('#export-json').onclick = () => run(async () => {
  const { download } = await import('./pptx/export.js');
  download(JSON.stringify(deck, null, 2), deck.title + '.json', 'application/json');
});
$('#export-notes').onclick = () => run(async () => {
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
