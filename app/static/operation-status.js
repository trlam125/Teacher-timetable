(function () {
  'use strict';

  const originalFetch = window.fetch.bind(window);
  const state = {
    activeRequests: 0,
    current: null,
    hideTimer: null,
    queue: [],
    startedAt: 0,
    connectionAlertTimer: null,
    connectionAlertToken: 0,
  };

  function ensurePanel() {
    let panel = document.querySelector('#operationStatus');
    if (panel) return panel;

    panel = document.createElement('div');
    panel.id = 'operationStatus';
    panel.className = 'operation-status';
    panel.hidden = true;
    panel.innerHTML = `
      <section class="operation-status-card" role="status" aria-live="polite">
        <div class="operation-status-icon" aria-hidden="true">
          <span class="operation-status-spinner"></span>
          <span class="operation-status-result"></span>
        </div>
        <div class="operation-status-content">
          <strong class="operation-status-title">Đang xử lý</strong>
          <p class="operation-status-message">Vui lòng chờ trong giây lát…</p>
          <div class="operation-status-actions" hidden>
            <button type="button" class="btn ghost" data-operation-cancel>Hủy</button>
            <button type="button" class="btn" data-operation-confirm>Đồng ý</button>
          </div>
        </div>
      </section>`;
    panel.addEventListener('click', event => {
      if (event.target.closest('[data-operation-confirm]')) resolveConfirmation(true);
      if (event.target.closest('[data-operation-cancel]')) resolveConfirmation(false);
    });
    document.body.appendChild(panel);
    return panel;
  }

  function requestLabel(url, method) {
    const path = String(url || '');
    if (path.includes('/generate')) return 'Đang xếp thời khóa biểu…';
    if (path.includes('/session-locks')) return 'Đang lưu khóa lịch…';
    if (path.includes('/constraints')) return 'Đang lưu tiết tránh…';
    if (path.includes('/preferences/') && path.includes('/review')) return 'Đang duyệt nguyện vọng…';
    if (path.includes('/fixed')) return method === 'DELETE' ? 'Đang bỏ cố định…' : 'Đang cố định tiết…';
    if (path.includes('/move')) return 'Đang di chuyển tiết học…';
    if (path.includes('/lessons')) return method === 'DELETE' ? 'Đang đưa tiết về khay…' : 'Đang xếp tiết học…';
    if (path.includes('/assignments')) return method === 'DELETE' ? 'Đang cập nhật khay tiết…' : 'Đang lưu phân công…';
    if (path.includes('/entity/')) return method === 'DELETE' ? 'Đang xóa dữ liệu…' : 'Đang lưu dữ liệu…';
    return 'Đang xử lý yêu cầu…';
  }

  function setPanel(mode, title, message) {
    const panel = ensurePanel();
    const card = panel.querySelector('.operation-status-card');
    const actions = panel.querySelector('.operation-status-actions');
    clearTimeout(state.hideTimer);
    panel.hidden = false;
    panel.className = `operation-status is-${mode}`;
    card.setAttribute('role', mode === 'confirm' ? 'alertdialog' : 'status');
    card.setAttribute('aria-live', mode === 'error' ? 'assertive' : 'polite');
    panel.querySelector('.operation-status-title').textContent = title;
    panel.querySelector('.operation-status-message').textContent = message;
    actions.hidden = mode !== 'confirm';
  }

  function showPending(message) {
    state.current = {type: 'pending'};
    setPanel('pending', message, 'Vui lòng chờ, không đóng trang hoặc thao tác lặp lại.');
  }

  function begin(message) {
    if (state.activeRequests === 0) state.startedAt = Date.now();
    state.activeRequests += 1;
    showPending(message || 'Đang xử lý…');
  }

  function finish() {
    state.activeRequests = Math.max(0, state.activeRequests - 1);
    if (state.activeRequests > 0) return;
    const remaining = Math.max(0, 320 - (Date.now() - state.startedAt));
    state.hideTimer = setTimeout(() => {
      if (state.activeRequests > 0) return;
      hidePanel();
      drainQueue();
    }, remaining);
  }

  function hidePanel() {
    clearTimeout(state.hideTimer);
    const panel = document.querySelector('#operationStatus');
    if (panel) panel.hidden = true;
    state.current = null;
  }

  function notificationKind(message, requestedKind) {
    if (requestedKind) return requestedKind;
    const normalized = String(message).toLowerCase();
    if (['lỗi', 'thất bại', 'không thể', 'không được', 'chưa hoàn tất'].some(word => normalized.includes(word))) return 'error';
    if (['đã ', 'thành công', 'hoàn tất'].some(word => normalized.includes(word))) return 'success';
    return 'info';
  }

  function enqueue(item) {
    const last = state.queue[state.queue.length - 1];
    if (item.type === 'notice' && last?.type === 'notice' && last.message === item.message) return;
    state.queue.push(item);
    drainQueue();
  }

  function notify(message, kind) {
    if (!message) return;
    enqueue({type: 'notice', message: String(message), kind: notificationKind(message, kind)});
  }

  function clearConnectionAlert() {
    state.connectionAlertToken += 1;
    if (state.connectionAlertTimer) {
      clearTimeout(state.connectionAlertTimer);
      state.connectionAlertTimer = null;
    }
  }

  function scheduleConnectionAlert() {
    if (state.connectionAlertTimer) return;
    const token = ++state.connectionAlertToken;
    state.connectionAlertTimer = setTimeout(async () => {
      state.connectionAlertTimer = null;
      if (token !== state.connectionAlertToken) return;
      try {
        await originalFetch(window.location.href, {
          method: 'HEAD',
          cache: 'no-store',
          credentials: 'same-origin',
          headers: {'X-Skip-Operation-Status': '1'},
        });
        clearConnectionAlert();
      } catch (error) {
        if (token !== state.connectionAlertToken) return;
        notify('Mất kết nối tới máy chủ. Vui lòng thử lại.', 'error');
      }
    }, 15000);
  }

  function confirmAction(message, options = {}) {
    return new Promise(resolve => {
      enqueue({
        type: 'confirm',
        message: String(message),
        title: options.title || 'Xác nhận thao tác',
        confirmText: options.confirmText || 'Đồng ý',
        cancelText: options.cancelText || 'Hủy',
        resolve,
      });
    });
  }

  function drainQueue() {
    if (state.activeRequests > 0 || state.current || state.queue.length === 0) return;
    const item = state.queue.shift();
    state.current = item;
    if (item.type === 'confirm') {
      const panel = ensurePanel();
      panel.querySelector('[data-operation-confirm]').textContent = item.confirmText;
      panel.querySelector('[data-operation-cancel]').textContent = item.cancelText;
      setPanel('confirm', item.title, item.message);
      panel.querySelector('[data-operation-confirm]').focus();
      return;
    }

    const titles = {success: 'Hoàn tất', error: 'Chưa hoàn tất', info: 'Thông báo'};
    setPanel(item.kind, titles[item.kind], item.message);
    const duration = item.kind === 'error' ? 3200 : 1900;
    state.hideTimer = setTimeout(() => {
      hidePanel();
      drainQueue();
    }, duration);
  }

  function resolveConfirmation(accepted) {
    if (state.current?.type !== 'confirm') return;
    const {resolve} = state.current;
    hidePanel();
    resolve(accepted);
    drainQueue();
  }

  function reset(options = {}) {
    hidePanel();
    clearConnectionAlert();
    state.activeRequests = 0;
    state.startedAt = 0;
    if (options.clearQueue) state.queue.length = 0;
    drainQueue();
  }

  window.fetch = async function operationAwareFetch(input, init) {
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const headers = new Headers((init && init.headers) || (input && input.headers) || undefined);
    const skipOperationStatus = headers.get('X-Skip-Operation-Status') === '1';
    const isMutation = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    const followsActiveOperation = !isMutation && state.current?.type === 'pending';

    if (skipOperationStatus) return originalFetch(input, init);
    if (!isMutation && !followsActiveOperation) return originalFetch(input, init);
    begin(isMutation ? requestLabel(url, method) : 'Đang cập nhật giao diện…');
    try {
      const response = await originalFetch(input, init);
      clearConnectionAlert();
      return response;
    } catch (error) {
      scheduleConnectionAlert();
      throw error;
    } finally {
      finish();
    }
  };

  document.addEventListener('submit', event => {
    queueMicrotask(() => {
      if (event.defaultPrevented || state.activeRequests > 0) return;
      const submitterText = (event.submitter?.textContent || '').trim();
      begin(submitterText ? `Đang thực hiện: ${submitterText}…` : 'Đang gửi biểu mẫu…');
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && state.current?.type === 'confirm') resolveConfirmation(false);
  });

  window.OperationStatus = {begin, finish, notify, confirm: confirmAction, reset};
  window.addEventListener('pageshow', event => {
    if (event.persisted) reset({clearQueue: true});
  });
})();
