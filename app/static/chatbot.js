(() => {
  const projectId = window.CHATBOT_PROJECT_ID;
  const form = document.querySelector('#chatForm');
  if (!form || !projectId) return;

  const input = document.querySelector('#chatInput');
  const fileInput = document.querySelector('#chatFile');
  const messages = document.querySelector('#chatMessages');
  const sendButton = document.querySelector('#sendChat');
  const filePreview = document.querySelector('#filePreview');
  const fileName = document.querySelector('#fileName');
  const removeFile = document.querySelector('#removeFile');
  const clearChat = document.querySelector('#clearChat');
  const popup = document.querySelector('#chatbotPopup');
  const fab = document.querySelector('#chatbotFab');
  const closeButton = document.querySelector('#chatbotClose');
  const minimizeButton = document.querySelector('#chatbotMinimize');
  const popupStatus = document.querySelector('.chatbot-popup-status');
  const pageStatus = document.querySelector('.chatbot-status');
  const history = [];
  let documentContext = [];

  let requestVersion = 0;
  let activeController = null;
  let activeModel = String(window.CHATBOT_PRIMARY_MODEL || 'gemini-3.7-flash').trim() || 'gemini-3.7-flash';

  const escapeHtml = value => String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  function setConnectionState(connected) {
    const status = popupStatus || pageStatus;
    if (!status) return;
    status.classList.toggle('is-ready', connected);
    status.classList.toggle('is-offline', !connected);
    status.textContent = connected ? 'Sẵn sàng hỗ trợ' : 'Không thể kết nối tới chatbot';
  }

  function renderInline(text) {
    let source = String(text ?? '');
    const protectedParts = [];
    const protect = html => {
      const token = `@@INLINE_${protectedParts.length}@@`;
      protectedParts.push(html);
      return token;
    };

    source = source.replace(/<br\s*\/?>/gi, () => protect('<br>'));
    source = source.replace(/`([^`\n]+)`/g, (_, code) => protect(`<code>${escapeHtml(code)}</code>`));
    source = source.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
      return protect(`<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`);
    });

    let safe = escapeHtml(source);
    safe = safe.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    safe = safe.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    safe = safe.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    safe = safe.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, '$1<em>$2</em>');

    protectedParts.forEach((html, index) => {
      safe = safe.replaceAll(`@@INLINE_${index}@@`, html);
    });
    return safe;
  }

  function splitTableRow(line) {
    let value = String(line).trim();
    if (value.startsWith('|')) value = value.slice(1);
    if (value.endsWith('|') && !value.endsWith('\\|')) value = value.slice(0, -1);

    const cells = [];
    let cell = '';
    for (let index = 0; index < value.length; index += 1) {
      const char = value[index];
      const next = value[index + 1];
      if (char === '\\' && next === '|') {
        cell += '|';
        index += 1;
      } else if (char === '|') {
        cells.push(cell.trim());
        cell = '';
      } else {
        cell += char;
      }
    }
    cells.push(cell.trim());
    return cells;
  }

  function isTableSeparator(line) {
    const cells = splitTableRow(line);
    return cells.length > 0 && cells.every(cell => /^:?-{2,}:?$/.test(cell.trim()));
  }

  function tableAlignment(separatorCell) {
    const value = separatorCell.trim();
    if (value.startsWith(':') && value.endsWith(':')) return 'center';
    if (value.endsWith(':')) return 'right';
    return 'left';
  }

  function renderTable(headerLine, separatorLine, bodyLines) {
    const headers = splitTableRow(headerLine);
    const separators = splitTableRow(separatorLine);
    const alignments = headers.map((_, index) => tableAlignment(separators[index] || '---'));
    const rows = bodyLines.map(splitTableRow);

    const head = headers.map((cell, index) => (
      `<th class="align-${alignments[index]}">${renderInline(cell)}</th>`
    )).join('');

    const body = rows.map(row => {
      const cells = headers.map((_, index) => (
        `<td class="align-${alignments[index]}">${renderInline(row[index] || '')}</td>`
      )).join('');
      return `<tr>${cells}</tr>`;
    }).join('');

    return `<div class="message-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function listIndent(raw) {
    return raw.replace(/\t/g, '    ').length;
  }

  function parseListItem(line) {
    const match = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.+)$/);
    if (!match) return null;
    const ordered = /^\d/.test(match[2]);
    return {
      indent: listIndent(match[1]),
      type: ordered ? 'ol' : 'ul',
      start: ordered ? Number.parseInt(match[2], 10) : null,
      content: match[3],
    };
  }

  function renderListSequence(items, startIndex, baseIndent) {
    let index = startIndex;
    let html = '';

    while (index < items.length && items[index].indent === baseIndent) {
      const type = items[index].type;
      const start = type === 'ol' && Number.isFinite(items[index].start) && items[index].start > 1
        ? ` start="${items[index].start}"`
        : '';
      html += `<${type}${start}>`;

      while (index < items.length) {
        const item = items[index];
        if (item.indent < baseIndent || item.indent > baseIndent || item.type !== type) break;

        html += `<li>${renderInline(item.content)}`;
        index += 1;

        while (index < items.length && items[index].indent > baseIndent) {
          const nestedIndent = items[index].indent;
          const nested = renderListSequence(items, index, nestedIndent);
          html += nested.html;
          index = nested.index;
        }
        html += '</li>';
      }
      html += `</${type}>`;
    }

    return { html, index };
  }

  function renderListItems(items) {
    if (!items.length) return '';
    let index = 0;
    let html = '';
    while (index < items.length) {
      const rendered = renderListSequence(items, index, items[index].indent);
      html += rendered.html;
      if (rendered.index <= index) break;
      index = rendered.index;
    }
    return html;
  }

  function isListContinuationBoundary(lines, index) {
    const trimmed = String(lines[index] || '').trim();
    if (!trimmed) return false;
    if (/^@@CODEBLOCK_\d+@@$/.test(trimmed)) return true;
    if (/^(#{1,3})\s+/.test(trimmed) || /^---+$/.test(trimmed) || /^>\s?/.test(trimmed)) return true;
    return index + 1 < lines.length && lines[index].includes('|') && isTableSeparator(lines[index + 1]);
  }

  function collectListBlock(lines, startIndex) {
    const items = [];
    let index = startIndex;

    while (index < lines.length) {
      const parsed = parseListItem(lines[index]);
      if (parsed) {
        items.push(parsed);
        index += 1;
        continue;
      }

      const trimmed = String(lines[index] || '').trim();
      if (!trimmed) {
        let nextIndex = index + 1;
        while (nextIndex < lines.length && !String(lines[nextIndex] || '').trim()) nextIndex += 1;
        if (nextIndex < lines.length && parseListItem(lines[nextIndex])) {
          index = nextIndex;
          continue;
        }
        break;
      }

      if (!items.length || isListContinuationBoundary(lines, index)) break;

      // Smaller models sometimes wrap a long list item onto a new physical line
      // without repeating the list marker. Keep that text inside the same <li>.
      items[items.length - 1].content += ` ${trimmed}`;
      index += 1;
    }

    return { html: renderListItems(items), index };
  }

  function renderMarkdown(markdown) {
    const source = String(markdown || '').replace(/\r\n?/g, '\n');
    const codeBlocks = [];
    const protectedSource = source.replace(/```[^\n]*\n?([\s\S]*?)```/g, (_, code) => {
      const token = `@@CODEBLOCK_${codeBlocks.length}@@`;
      codeBlocks.push(`<pre><code>${escapeHtml(code.replace(/\n$/, ''))}</code></pre>`);
      return `\n${token}\n`;
    });

    const lines = protectedSource.split('\n');
    const out = [];
    let paragraph = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      out.push(`<p>${renderInline(paragraph.join(' '))}</p>`);
      paragraph = [];
    };

    for (let index = 0; index < lines.length;) {
      const raw = lines[index];
      const line = raw.trimEnd();
      const trimmed = line.trim();

      if (!trimmed) {
        flushParagraph();
        index += 1;
        continue;
      }

      if (/^@@CODEBLOCK_\d+@@$/.test(trimmed)) {
        flushParagraph();
        out.push(trimmed);
        index += 1;
        continue;
      }

      if (index + 1 < lines.length && line.includes('|') && isTableSeparator(lines[index + 1])) {
        flushParagraph();
        const bodyLines = [];
        let bodyIndex = index + 2;
        while (bodyIndex < lines.length) {
          const candidate = lines[bodyIndex];
          if (!candidate.trim() || !candidate.includes('|') || parseListItem(candidate)) break;
          bodyLines.push(candidate);
          bodyIndex += 1;
        }
        out.push(renderTable(line, lines[index + 1], bodyLines));
        index = bodyIndex;
        continue;
      }

      const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        const level = heading[1].length;
        out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      if (/^---+$/.test(trimmed)) {
        flushParagraph();
        out.push('<hr>');
        index += 1;
        continue;
      }

      if (parseListItem(line)) {
        flushParagraph();
        const rendered = collectListBlock(lines, index);
        out.push(rendered.html);
        index = rendered.index;
        continue;
      }

      const quote = trimmed.match(/^>\s?(.*)$/);
      if (quote) {
        flushParagraph();
        const quoteLines = [];
        while (index < lines.length) {
          const current = lines[index].trim().match(/^>\s?(.*)$/);
          if (!current) break;
          quoteLines.push(current[1]);
          index += 1;
        }
        out.push(`<blockquote>${renderInline(quoteLines.join(' '))}</blockquote>`);
        continue;
      }

      paragraph.push(trimmed);
      index += 1;
    }

    flushParagraph();
    let html = out.join('');
    codeBlocks.forEach((block, index) => {
      html = html.replaceAll(`@@CODEBLOCK_${index}@@`, block);
    });
    return html;
  }

  function setPopup(open) {
    if (!popup || !fab) return;
    popup.classList.toggle('is-open', open);
    popup.setAttribute('aria-hidden', String(!open));
    fab.classList.toggle('is-hidden', open);
    fab.setAttribute('aria-expanded', String(open));
    if (open) setTimeout(() => input.focus(), 120);
  }

  window.toggleChatbotPopup = () => setPopup(!(popup && popup.classList.contains('is-open')));
  fab?.addEventListener('click', () => setPopup(true));
  closeButton?.addEventListener('click', () => setPopup(false));
  minimizeButton?.addEventListener('click', () => setPopup(false));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && popup?.classList.contains('is-open')) setPopup(false);
  });

  function addMessage(role, content, extraClass = '') {
    const article = document.createElement('article');
    article.className = `chat-message ${role} ${extraClass}`.trim();
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'assistant' ? 'AI' : 'Bạn';
    const body = document.createElement('div');
    body.className = 'message-body';
    if (role === 'assistant' && !extraClass.includes('error') && !extraClass.includes('chat-loading')) {
      body.innerHTML = renderMarkdown(content);
    } else {
      body.textContent = content;
    }
    article.append(avatar, body);
    messages.appendChild(article);
    messages.scrollTop = messages.scrollHeight;
    return article;
  }

  function updateFilePreview() {
    const files = [...fileInput.files];
    filePreview.hidden = !files.length;
    fileName.textContent = files.length
      ? files.map(file => `${file.name} · ${(file.size / 1024).toFixed(1)} KB`).join(' · ')
      : '';
  }

  fileInput.addEventListener('change', () => {
    const files = [...fileInput.files];
    const allowedExtensions = ['.docx', '.xlsx', '.csv', '.pdf'];
    const hasUnsupportedFile = files.some(file => {
      const name = file.name.toLowerCase();
      return !allowedExtensions.some(extension => name.endsWith(extension));
    });
    if (files.length > 3) {
      fileInput.value = '';
      addMessage('assistant', 'Chỉ được đính kèm tối đa 3 tệp.', 'error');
    } else if (hasUnsupportedFile) {
      fileInput.value = '';
      addMessage('assistant', 'Chỉ hỗ trợ tệp Word (.docx), Excel (.xlsx), CSV hoặc PDF.', 'error');
    } else if (files.some(file => file.size > 5 * 1024 * 1024)) {
      fileInput.value = '';
      addMessage('assistant', 'Mỗi tệp không được vượt quá 5 MB.', 'error');
    } else if (files.reduce((total, file) => total + file.size, 0) > 12 * 1024 * 1024) {
      fileInput.value = '';
      addMessage('assistant', 'Tổng dung lượng tệp không được vượt quá 12 MB.', 'error');
    }
    updateFilePreview();
  });

  removeFile.addEventListener('click', () => {
    fileInput.value = '';
    updateFilePreview();
  });

  document.querySelectorAll('[data-prompt]').forEach(button => {
    button.addEventListener('click', () => {
      input.value = button.dataset.prompt;
      input.focus();
    });
  });

  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  clearChat.addEventListener('click', () => {
    requestVersion += 1;
    activeController?.abort();
    activeController = null;
    history.length = 0;
    documentContext = [];
    messages.querySelectorAll('.chat-message.user,.chat-message.assistant:not(:first-child),.chat-loading').forEach(item => item.remove());
    fileInput.value = '';
    updateFilePreview();
    sendButton.disabled = !window.CHATBOT_ENABLED;
    input.focus();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const prompt = input.value.trim();
    if (!prompt || sendButton.disabled) return;
    if (!window.CHATBOT_ENABLED) {
      setConnectionState(false);
      addMessage('assistant', 'Không thể kết nối tới chatbot. Vui lòng thử lại sau.', 'error');
      return;
    }

    const selectedFiles = [...fileInput.files];
    const attachmentText = selectedFiles.length ? `\n\n📎 ${selectedFiles.map(file => file.name).join(', ')}` : '';
    addMessage('user', `${prompt}${attachmentText}`);
    input.value = '';
    sendButton.disabled = true;
    const loading = addMessage('assistant', 'Đang đọc dữ liệu và phân tích…', 'chat-loading');

    const payload = new FormData();
    payload.append('message', prompt);
    payload.append('history_json', JSON.stringify(history.slice(-8)));
    payload.append('document_context_json', JSON.stringify(documentContext));
    payload.append('preferred_model', activeModel);
    selectedFiles.forEach(file => payload.append('files', file));

    // Tệp đã được chụp vào FormData, nên xóa ngay khỏi bộ soạn thảo sau khi bấm Gửi.
    // File objects trong selectedFiles/FormData vẫn còn nguyên cho request hiện tại.
    fileInput.value = '';
    updateFilePreview();

    const currentVersion = ++requestVersion;
    const controller = new AbortController();
    activeController = controller;
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 150000);

    try {
      const response = await fetch(`/api/projects/${projectId}/chatbot`, {
        method: 'POST',
        body: payload,
        signal: controller.signal,
        headers: {
          'X-Skip-Operation-Status': '1',
        },
      });
      const result = await response.json().catch(() => ({}));
      if (currentVersion !== requestVersion) return;

      loading.remove();
      if (!response.ok) {
        if (response.status === 401) {
          window.location.href = '/login';
          return;
        }
        if (response.status >= 500 || response.status === 403 || response.status === 404) {
          setConnectionState(false);
          addMessage('assistant', 'Không thể kết nối tới chatbot. Vui lòng thử lại sau.', 'error');
        } else {
          addMessage('assistant', result.detail || result.message || 'Không thể xử lý yêu cầu.', 'error');
        }
        return;
      }

      setConnectionState(true);
      if (result.model_used) activeModel = String(result.model_used);
      if (Array.isArray(result.document_context)) documentContext = result.document_context;
      addMessage('assistant', result.answer);
      history.push({ role: 'user', content: prompt }, { role: 'assistant', content: result.answer });
      if (history.length > 8) history.splice(0, history.length - 8);
    } catch (error) {
      if (currentVersion !== requestVersion) return;
      loading.remove();
      if (error?.name === 'AbortError' && !timedOut) return;
      setConnectionState(false);
      addMessage('assistant', 'Không thể kết nối tới chatbot. Vui lòng thử lại sau.', 'error');
    } finally {
      window.clearTimeout(timeoutId);
      if (currentVersion === requestVersion) {
        activeController = null;
        sendButton.disabled = false;
        input.focus();
      }
    }
  });
})();
