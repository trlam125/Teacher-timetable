(() => {
  const projectId = window.CHATBOT_PROJECT_ID;
  const form = document.querySelector('#chatForm');
  const input = document.querySelector('#chatInput');
  const fileInput = document.querySelector('#chatFile');
  const messages = document.querySelector('#chatMessages');
  const sendButton = document.querySelector('#sendChat');
  const filePreview = document.querySelector('#filePreview');
  const fileName = document.querySelector('#fileName');
  const removeFile = document.querySelector('#removeFile');
  const history = [];

  function addMessage(role, content, extraClass = '') {
    const article = document.createElement('article');
    article.className = `chat-message ${role} ${extraClass}`.trim();
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'assistant' ? 'AI' : 'Bạn';
    const body = document.createElement('div');
    body.className = 'message-body';
    body.textContent = content;
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

  document.querySelector('#clearChat').addEventListener('click', () => {
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
    const attachmentText = selectedFiles.length
      ? `\n\n📎 ${selectedFiles.map(file => file.name).join(', ')}`
      : '';
    addMessage('user', `${prompt}${attachmentText}`);
    input.value = '';
    sendButton.disabled = true;
    const loading = addMessage('assistant', 'Đang đọc dữ liệu và phân tích…', 'chat-loading');

    const payload = new FormData();
    payload.append('message', prompt);
    payload.append('history_json', JSON.stringify(history.slice(-8)));
    selectedFiles.forEach(file => payload.append('files', file));

    try {
      const response = await fetch(`/api/projects/${projectId}/chatbot`, {
        method: 'POST',
        body: payload,
      });
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
