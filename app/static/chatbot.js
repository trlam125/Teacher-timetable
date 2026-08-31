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
  const history = [];

  const escapeHtml = value => String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  function renderInline(text) {
    let safe = escapeHtml(text);
    safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');
    safe = safe.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    safe = safe.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    safe = safe.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
    safe = safe.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return safe;
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
    let listType = null;
    let paragraph = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      out.push(`<p>${renderInline(paragraph.join(' '))}</p>`);
      paragraph = [];
    };
    const closeList = () => {
      if (!listType) return;
      out.push(`</${listType}>`);
      listType = null;
    };

    for (const raw of lines) {
      const line = raw.trimEnd();
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        closeList();
        continue;
      }
      if (/^@@CODEBLOCK_\d+@@$/.test(trimmed)) {
        flushParagraph(); closeList(); out.push(trimmed); continue;
      }
      const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        flushParagraph(); closeList();
        const level = heading[1].length;
        out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        continue;
      }
      if (/^---+$/.test(trimmed)) {
        flushParagraph(); closeList(); out.push('<hr>'); continue;
      }
      const bullet = trimmed.match(/^[-*+]\s+(.+)$/);
      const numbered = trimmed.match(/^\d+[.)]\s+(.+)$/);
      if (bullet || numbered) {
        flushParagraph();
        const wanted = bullet ? 'ul' : 'ol';
        if (listType !== wanted) { closeList(); out.push(`<${wanted}>`); listType = wanted; }
        out.push(`<li>${renderInline((bullet || numbered)[1])}</li>`);
        continue;
      }
      const quote = trimmed.match(/^>\s?(.*)$/);
      if (quote) {
        flushParagraph(); closeList(); out.push(`<blockquote>${renderInline(quote[1])}</blockquote>`); continue;
      }
      closeList();
      paragraph.push(trimmed);
    }
    flushParagraph();
    closeList();

    let html = out.join('');
    codeBlocks.forEach((block, index) => {
      html = html.replace(`@@CODEBLOCK_${index}@@`, block);
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
    if (files.length > 3) {
      fileInput.value = '';
      addMessage('assistant', 'Chỉ được đính kèm tối đa 3 tệp.', 'error');
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
    history.length = 0;
    messages.querySelectorAll('.chat-message.user,.chat-message.assistant:not(:first-child),.chat-loading').forEach(item => item.remove());
    fileInput.value = '';
    updateFilePreview();
    input.focus();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const prompt = input.value.trim();
    if (!prompt || sendButton.disabled) return;
    if (!window.CHATBOT_ENABLED) {
      addMessage('assistant', 'Máy chủ chưa có GEMINI_API_KEY.', 'error');
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
    selectedFiles.forEach(file => payload.append('files', file));

    try {
      const response = await fetch(`/api/projects/${projectId}/chatbot`, { method: 'POST', body: payload });
      const result = await response.json().catch(() => ({}));
      loading.remove();
      if (!response.ok) {
        addMessage('assistant', result.detail || result.message || 'Không thể nhận câu trả lời.', 'error');
        return;
      }
      addMessage('assistant', result.answer);
      history.push({ role: 'user', content: prompt }, { role: 'assistant', content: result.answer });
      if (history.length > 8) history.splice(0, history.length - 8);
      fileInput.value = '';
      updateFilePreview();
    } catch (error) {
      loading.remove();
      addMessage('assistant', 'Mất kết nối tới máy chủ. Hãy thử lại.', 'error');
    } finally {
      sendButton.disabled = false;
      input.focus();
    }
  });
})();
