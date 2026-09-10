(function () {
  "use strict";

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

  function ensureConfirmModal() {
    let panel = document.querySelector("#operationConfirmModal");
    if (panel) return panel;

    panel = document.createElement("div");
    panel.id = "operationConfirmModal";
    panel.className = "operation-status is-confirm";
    panel.hidden = true;
    panel.innerHTML = `
      <section class="operation-status-card" role="alertdialog" aria-live="assertive">
        <div class="operation-status-icon" aria-hidden="true">
          <span class="operation-status-result"></span>
        </div>
        <div class="operation-status-content">
          <strong class="operation-status-title">Xác nhận thao tác</strong>
          <p class="operation-status-message"></p>
          <div class="operation-status-actions">
            <button type="button" class="btn ghost" data-operation-cancel>Hủy</button>
            <button type="button" class="btn" data-operation-confirm>Đồng ý</button>
          </div>
        </div>
      </section>`;
    panel.addEventListener("click", (event) => {
      if (event.target.closest("[data-operation-confirm]"))
        resolveConfirmation(true);
      if (event.target.closest("[data-operation-cancel]"))
        resolveConfirmation(false);
    });
    document.body.appendChild(panel);
    return panel;
  }

  function ensureToastContainer() {
    let container = document.querySelector("#operationToastContainer");
    if (container) return container;
    container = document.createElement("div");
    container.id = "operationToastContainer";
    container.className = "operation-toast-container";
    document.body.appendChild(container);
    return container;
  }

  function requestLabel(url, method) {
    const path = String(url || "");
    if (path.includes("/generate")) return "Đang xếp thời khóa biểu…";
    if (path.includes("/session-locks")) return "Đang lưu khóa lịch…";
    if (path.includes("/constraints")) return "Đang lưu tiết tránh…";
    if (path.includes("/preferences/") && path.includes("/review"))
      return "Đang duyệt nguyện vọng…";
    if (path.includes("/fixed"))
      return method === "DELETE" ? "Đang bỏ cố định…" : "Đang cố định tiết…";
    if (path.includes("/move")) return "Đang di chuyển tiết học…";
    if (path.includes("/lessons"))
      return method === "DELETE"
        ? "Đang đưa tiết về khay…"
        : "Đang xếp tiết học…";
    if (path.includes("/assignments"))
      return method === "DELETE"
        ? "Đang cập nhật khay tiết…"
        : "Đang lưu phân công…";
    if (path.includes("/entity/"))
      return method === "DELETE" ? "Đang xóa dữ liệu…" : "Đang lưu dữ liệu…";
    return "Đang xử lý yêu cầu…";
  }

  let activePendingToast = null;

  function showPending(message) {
    state.current = { type: "pending" };
    const container = ensureToastContainer();
    if (!activePendingToast) {
      activePendingToast = document.createElement("div");
      activePendingToast.className = "operation-toast is-pending";
      activePendingToast.innerHTML = `
        <div class="operation-toast-icon"><span class="operation-status-spinner"></span></div>
        <div class="operation-toast-body">
          <strong class="operation-toast-title">${esc(message)}</strong>
        </div>`;
      container.appendChild(activePendingToast);
    } else {
      activePendingToast.querySelector(".operation-toast-title").textContent =
        message;
    }
  }

  function hidePending() {
    if (activePendingToast) {
      activePendingToast.classList.add("is-hiding");
      const el = activePendingToast;
      activePendingToast = null;
      setTimeout(() => {
        if (el.parentNode) el.remove();
      }, 240);
    }
    state.current = null;
  }

  function begin(message) {
    if (state.activeRequests === 0) state.startedAt = Date.now();
    state.activeRequests += 1;
    showPending(message || "Đang xử lý…");
  }

  function finish() {
    state.activeRequests = Math.max(0, state.activeRequests - 1);
    if (state.activeRequests > 0) return;
    const remaining = Math.max(0, 280 - (Date.now() - state.startedAt));
    state.hideTimer = setTimeout(() => {
      if (state.activeRequests > 0) return;
      hidePending();
      drainQueue();
    }, remaining);
  }

  function esc(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showToastNotification(kind, title, message) {
    const container = ensureToastContainer();
    const toast = document.createElement("div");
    const duration = kind === "error" ? 4200 : kind === "warning" ? 3800 : 2800;
    toast.className = `operation-toast is-${kind}`;
    toast.innerHTML = `
      <div class="operation-toast-icon">
        <span class="operation-status-result"></span>
      </div>
      <div class="operation-toast-body">
        <strong class="operation-toast-title">${esc(title)}</strong>
        <p class="operation-toast-message">${esc(message)}</p>
      </div>
      <button type="button" class="operation-toast-close" aria-label="Đóng thông báo">×</button>
      <div class="operation-toast-countdown" style="animation-duration: ${duration}ms"></div>`;

    const closeBtn = toast.querySelector(".operation-toast-close");
    let timer = null;

    function dismiss() {
      clearTimeout(timer);
      toast.classList.add("is-hiding");
      setTimeout(() => {
        if (toast.parentNode) toast.remove();
        state.current = null;
        drainQueue();
      }, 240);
    }

    closeBtn.addEventListener("click", dismiss);
    timer = setTimeout(dismiss, duration);
    container.appendChild(toast);
  }

  function hidePanel() {
    clearTimeout(state.hideTimer);
    const modal = document.querySelector("#operationConfirmModal");
    if (modal) modal.hidden = true;
    hidePending();
  }

  function notificationKind(message, requestedKind) {
    if (requestedKind) return requestedKind;
    const normalized = String(message).toLowerCase();
    if (
      ["lỗi", "thất bại", "không thể", "không được", "chưa hoàn tất"].some(
        (word) => normalized.includes(word),
      )
    )
      return "error";
    if (
      ["cảnh báo", "chú ý", "trùng", "xung đột"].some((word) =>
        normalized.includes(word),
      )
    )
      return "warning";
    if (
      ["đã ", "thành công", "hoàn tất"].some((word) =>
        normalized.includes(word),
      )
    )
      return "success";
    return "info";
  }

  function enqueue(item) {
    const last = state.queue[state.queue.length - 1];
    if (
      item.type === "notice" &&
      last?.type === "notice" &&
      last.message === item.message
    )
      return;
    state.queue.push(item);
    drainQueue();
  }

  function notify(message, kind) {
    if (!message) return;
    enqueue({
      type: "notice",
      message: String(message),
      kind: notificationKind(message, kind),
    });
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
          method: "HEAD",
          cache: "no-store",
          credentials: "same-origin",
          headers: { "X-Skip-Operation-Status": "1" },
        });
        clearConnectionAlert();
      } catch (error) {
        if (token !== state.connectionAlertToken) return;
        notify("Mất kết nối tới máy chủ. Vui lòng thử lại.", "error");
      }
    }, 15000);
  }

  function confirmAction(message, options = {}) {
    return new Promise((resolve) => {
      enqueue({
        type: "confirm",
        message: String(message),
        title: options.title || "Xác nhận thao tác",
        confirmText: options.confirmText || "Đồng ý",
        cancelText: options.cancelText || "Hủy",
        resolve,
      });
    });
  }

  function drainQueue() {
    if (state.activeRequests > 0 || state.current || state.queue.length === 0)
      return;
    const item = state.queue.shift();
    state.current = item;

    if (item.type === "confirm") {
      const modal = ensureConfirmModal();
      modal.querySelector("[data-operation-confirm]").textContent =
        item.confirmText;
      modal.querySelector("[data-operation-cancel]").textContent =
        item.cancelText;
      modal.querySelector(".operation-status-title").textContent = item.title;
      modal.querySelector(".operation-status-message").textContent =
        item.message;
      modal.hidden = false;
      modal.querySelector("[data-operation-confirm]").focus();
      return;
    }

    const titles = {
      success: "Hoàn tất",
      error: "Chưa hoàn tất",
      warning: "Cảnh báo",
      info: "Thông báo",
    };
    showToastNotification(
      item.kind,
      titles[item.kind] || "Thông báo",
      item.message,
    );
  }

  function resolveConfirmation(accepted) {
    if (state.current?.type !== "confirm") return;
    const { resolve } = state.current;
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
    const method = String(
      (init && init.method) || (input && input.method) || "GET",
    ).toUpperCase();
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const headers = new Headers(
      (init && init.headers) || (input && input.headers) || undefined,
    );
    const skipOperationStatus = headers.get("X-Skip-Operation-Status") === "1";
    const isMutation = !["GET", "HEAD", "OPTIONS"].includes(method);
    const followsActiveOperation =
      !isMutation && state.current?.type === "pending";

    if (skipOperationStatus) return originalFetch(input, init);
    if (!isMutation && !followsActiveOperation)
      return originalFetch(input, init);
    begin(isMutation ? requestLabel(url, method) : "Đang cập nhật giao diện…");
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

  document.addEventListener("submit", (event) => {
    queueMicrotask(() => {
      if (event.defaultPrevented || state.activeRequests > 0) return;
      const submitterText = (event.submitter?.textContent || "").trim();
      begin(
        submitterText
          ? `Đang thực hiện: ${submitterText}…`
          : "Đang gửi biểu mẫu…",
      );
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.current?.type === "confirm")
      resolveConfirmation(false);
  });

  window.OperationStatus = {
    begin,
    finish,
    notify,
    confirm: confirmAction,
    reset,
  };
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) reset({ clearQueue: true });
  });
})();
