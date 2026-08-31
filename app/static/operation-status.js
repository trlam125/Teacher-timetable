(function () {
  'use strict';

  const originalFetch = window.fetch.bind(window);
  const state = {
    activeRequests: 0,
    visible: false,
    settleTimer: null,
    lastResult: null,
    startedAt: 0,
  };

  function ensurePanel() {
    let panel = document.querySelector('#operationStatus');
    if (panel) return panel;

    panel = document.createElement('div');
    panel.id = 'operationStatus';
    panel.className = 'operation-status';
    panel.hidden = true;
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    panel.setAttribute('aria-busy', 'true');
    panel.innerHTML = `
      <div class="operation-status-card">
        <div class="operation-status-icon" aria-hidden="true">
          <span class="operation-status-spinner"></span>
          <span class="operation-status-result"></span>
        </div>
        <div>
          <strong class="operation-status-title">Đang xử lý</strong>
          <p class="operation-status-message">Vui lòng chờ trong giây lát…</p>
        </div>
      </div>`;
    document.body.appendChild(panel);
    return panel;
  }

  function requestLabel(url, method) {
    const path = String(url || '');
    if (path.includes('/generate')) return 'Đang xếp thời khóa biểu…';
    if (path.includes('/session-locks')) return 'Đang lưu khóa lịch…';
    if (path.includes('/constraints')) return 'Đang lưu tiết tránh…';
    if (path.includes('/preferences/') && path.includes('/review')) return 'Đang duyệt nguyện vọng…';
    if (path.includes('/preferences/')) return 'Đang gửi nguyện vọng…';
    if (path.includes('/teacher-accounts')) return method === 'DELETE' ? 'Đang thu hồi tài khoản…' : 'Đang lưu tài khoản…';
    if (path.includes('/fixed')) return method === 'DELETE' ? 'Đang bỏ cố định…' : 'Đang cố định tiết…';
    if (path.includes('/move')) return 'Đang di chuyển tiết học…';
    if (path.includes('/lessons')) return method === 'DELETE' ? 'Đang đưa tiết về khay…' : 'Đang xếp tiết học…';
    if (path.includes('/assignments')) return method === 'DELETE' ? 'Đang cập nhật khay tiết…' : 'Đang lưu phân công…';
    if (path.includes('/entity/')) return method === 'DELETE' ? 'Đang xóa dữ liệu…' : 'Đang lưu dữ liệu…';
    return 'Đang xử lý yêu cầu…';
  }

  function showPending(message) {
    const panel = ensurePanel();
    const wasVisible = state.visible;
    clearTimeout(state.settleTimer);
    state.visible = true;
    if (!wasVisible) {
      state.startedAt = Date.now();
      state.lastResult = null;
    }
    panel.hidden = false;
    panel.className = 'operation-status is-pending';
    panel.setAttribute('aria-busy', 'true');
    panel.querySelector('.operation-status-title').textContent = message;
    panel.querySelector('.operation-status-message').textContent = 'Vui lòng chờ, không đóng trang hoặc thao tác lặp lại.';
  }

  function begin(message) {
    state.activeRequests += 1;
    showPending(message);
  }

  function resultMessage(payload, response, fallback) {
    if (payload && typeof payload === 'object') {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map(item => item.msg || String(item)).join('; ')
        : payload.detail;
      return payload.message || detail || fallback;
    }
    return fallback || (response.ok ? 'Thao tác đã hoàn tất.' : 'Không thể hoàn tất thao tác.');
  }

  async function readResult(response) {
    try {
      const type = response.headers.get('content-type') || '';
      if (!type.includes('application/json')) return null;
      return await response.clone().json();
    } catch (_error) {
      return null;
    }
  }

  function scheduleSettle() {
    if (state.activeRequests > 0) return;
    clearTimeout(state.settleTimer);
    const elapsed = Date.now() - state.startedAt;
    const minimumPendingTime = Math.max(0, 280 - elapsed);
    state.settleTimer = setTimeout(() => {
      if (state.activeRequests > 0 || !state.visible) return;
      const panel = ensurePanel();
      const result = state.lastResult || {ok: true, message: 'Thao tác đã hoàn tất.'};
      panel.className = `operation-status ${result.ok ? 'is-success' : 'is-error'}`;
      panel.setAttribute('aria-busy', 'false');
      panel.querySelector('.operation-status-title').textContent = result.ok ? 'Hoàn tất' : 'Chưa hoàn tất';
      panel.querySelector('.operation-status-message').textContent = result.message;
      state.settleTimer = setTimeout(() => reset(), result.ok ? 700 : 1200);
    }, minimumPendingTime + 120);
  }

  function finish(result) {
    state.activeRequests = Math.max(0, state.activeRequests - 1);
    if (result && (!state.lastResult || !result.ok || state.lastResult.ok)) {
      state.lastResult = result;
    }
    scheduleSettle();
  }

  function reset() {
    clearTimeout(state.settleTimer);
    const panel = document.querySelector('#operationStatus');
    if (panel) panel.hidden = true;
    state.activeRequests = 0;
    state.visible = false;
    state.lastResult = null;
    state.startedAt = 0;
  }

  window.fetch = async function operationAwareFetch(input, init) {
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const isMutation = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    const followsActiveOperation = !isMutation && state.visible;

    if (!isMutation && !followsActiveOperation) return originalFetch(input, init);
    begin(isMutation ? requestLabel(url, method) : 'Đang cập nhật giao diện…');

    try {
      const response = await originalFetch(input, init);
      const payload = isMutation ? await readResult(response) : null;
      finish(isMutation ? {
        ok: response.ok,
        message: resultMessage(payload, response),
      } : null);
      return response;
    } catch (error) {
      finish({ok: false, message: 'Mất kết nối tới máy chủ. Vui lòng thử lại.'});
      throw error;
    }
  };

  document.addEventListener('submit', event => {
    queueMicrotask(() => {
      if (event.defaultPrevented || state.visible) return;
      const submitterText = (event.submitter && event.submitter.textContent || '').trim();
      const message = submitterText ? `Đang thực hiện: ${submitterText}…` : 'Đang gửi biểu mẫu…';
      showPending(message);
    });
  });

  window.OperationStatus = {begin, finish, reset};
  window.addEventListener('pageshow', event => {
    if (event.persisted) reset();
  });
})();
