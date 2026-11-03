/* Commit-only schedule synchronization, shared by editor and read-only views. */
(() => {
  if (!window.PROJECT_ID || !document.getElementById("scheduleGrid")) return;
  const projectId = Number(window.PROJECT_ID);
  const shareUrl = window.SCHEDULE_LIVE_SHARE_URL;
  const endpoint = shareUrl || `/api/projects/${projectId}/live`;
  const readOnly = Boolean(window.READ_ONLY);
  let knownRevision = data?.schedule_revision ?? null;
  let inFlight = false;
  let pending = false;
  let stopped = false;
  let timer = null;
  let localRequests = 0;
  let localSequence = 0;
  let statusSequence = 0;
  const dirtyInputs = new Map();
  const status = document.createElement("p");
  status.id = "scheduleLiveStatus";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.hidden = true;
  document.getElementById("scheduleGrid").before(status);

  function announce(message, temporary = false) {
    const sequence = ++statusSequence;
    status.textContent = message;
    status.hidden = false;
    if (temporary) window.setTimeout(() => {
      if (sequence === statusSequence) status.hidden = true;
    }, 4000);
  }

  function valueOf(input) {
    if (input.type === "checkbox" || input.type === "radio") return input.checked;
    if (input.multiple && input.selectedOptions) return [...input.selectedOptions].map(option => option.value).join("\u0000");
    return input.value;
  }

  function watchInput(event) {
    if (readOnly) return;
    const input = event.target;
    if (!input?.matches?.("input, textarea, select") || !input.closest("form, dialog")) return;
    if (!dirtyInputs.has(input)) dirtyInputs.set(input, valueOf(input));
  }

  document.addEventListener("focusin", watchInput);
  document.addEventListener("pointerdown", watchInput, true);
  // Existing constraint editors own their draft flags; form baselines cover
  // entity and assignment editors without ever resetting their field values.
  function busy() {
    if (localRequests > 0) return true;
    if (readOnly) return false;
    if (typeof constraintDraftDirty !== "undefined" && constraintDraftDirty) return true;
    if (typeof globalLocksDraftDirty !== "undefined" && globalLocksDraftDirty) return true;
    if (typeof constraintSaveInFlight !== "undefined" && constraintSaveInFlight) return true;
    if (typeof globalSaveInFlight !== "undefined" && globalSaveInFlight) return true;
    if (typeof activeTapAssign !== "undefined" && activeTapAssign) return true;
    if (typeof autoAssignmentDrafts !== "undefined" && autoAssignmentDrafts.size) return true;
    if (typeof autoGradeDrafts !== "undefined" && autoGradeDrafts.size) return true;
    if (document.querySelector("dialog[open]")) return true;
    for (const [input, initial] of dirtyInputs) {
      const dialog = input.closest("dialog");
      if (!input.isConnected || (dialog && !dialog.open)) {
        dirtyInputs.delete(input);
        continue;
      }
      if (valueOf(input) !== initial) return true;
    }
    const focused = document.activeElement;
    return Boolean(focused?.matches?.("input, textarea, select") && focused.closest("form"));
  }

  function schedule(delay = 200) {
    if (stopped) return;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void check(), delay);
  }

  // Keep background responses from racing with a local save or its refresh.
  const previousFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const target = args[0];
    const url = new URL(typeof target === "string" || target instanceof URL ? String(target) : target.url, location.href);
    const method = String(args[1]?.method || target?.method || "GET").toUpperCase();
    const projectRequest = url.origin === location.origin && url.pathname.startsWith(`/api/projects/${projectId}/`) && !url.pathname.endsWith("/live");
    const local = projectRequest && (method !== "GET" || url.pathname.endsWith("/data"));
    if (local) { localRequests++; localSequence++; }
    try {
      return await previousFetch(...args);
    } finally {
      if (local) {
        localRequests--;
        schedule(350);
      }
    }
  };

  function revoke(message) {
    stopped = true;
    window.clearTimeout(timer);
    data = { ...data, lessons: [], assignments: [], teachers: [], classes: [], subjects: [], grades: [] };
    document.getElementById("scheduleGrid").innerHTML = "";
    document.getElementById("unscheduledTray")?.replaceChildren();
    announce(message);
  }

  function apply(payload, sequence) {
    const scroll = captureRefreshScrollState();
    data = payload.data;
    // Coordinate with manual refresh() responses already in flight.
    if (typeof latestAppliedFullRefreshSequence !== "undefined") {
      latestAppliedFullRefreshSequence = Math.max(latestAppliedFullRefreshSequence, sequence);
      Object.keys(data).forEach(key => latestAppliedPartRefreshSequence.set(key, sequence));
    }
    if (!readOnly) renderAll();
    else renderScheduleSelectors();
    const warning = document.getElementById("sharedScheduleWarning");
    if (warning) {
      warning.hidden = !payload.integrity_warning;
      warning.querySelector("[data-live-integrity-message]").textContent = payload.integrity_warning || "";
    }
    restoreRefreshScrollState(scroll);
    requestAnimationFrame(() => restoreRefreshScrollState(scroll));
    knownRevision = payload.revision;
    pending = false;
    announce("Thời khóa biểu đã được cập nhật.", true);
  }

  async function check() {
    if (stopped || document.hidden || navigator.onLine === false) return;
    if (inFlight) { schedule(350); return; }
    if (pending && busy()) {
      announce("Có lịch mới. Trang sẽ cập nhật sau khi bạn hoàn tất thay đổi đang nhập hoặc tinh chỉnh.");
      return;
    }
    inFlight = true;
    const controller = new AbortController();
    let requestTimeout;
    const beforeLocal = localSequence;
    const sequence = typeof refreshRequestSequence !== "undefined" ? ++refreshRequestSequence : 0;
    try {
      const url = `${endpoint}${knownRevision == null ? "" : `?revision=${encodeURIComponent(knownRevision)}`}`;
      const { response, payload } = await Promise.race([
        (async () => {
          const response = await window.fetch(url, { cache: "no-store", headers: operationHeaders(), signal: controller.signal });
          if ([401, 403, 404].includes(response.status)) return { response };
          if (!response.ok) throw new Error("live_refresh_failed");
          return { response, payload: await readApiResponse(response) };
        })(),
        new Promise((_resolve, reject) => {
          requestTimeout = window.setTimeout(() => {
            controller.abort();
            reject(new Error("live_sync_timeout"));
          }, 10000);
        }),
      ]);
      if (response.status === 403 || response.status === 404 || response.status === 401) {
        revoke(shareUrl ? "Liên kết chia sẻ không còn khả dụng." : "Bạn không còn quyền xem thời khóa biểu này. Hãy đăng nhập hoặc kiểm tra lại quyền truy cập.");
        return;
      }
      if (typeof payload.revision !== "string" || typeof payload.changed !== "boolean") throw new Error("invalid_live_response");
      if (!payload.changed) { pending = false; return; }
      pending = true;
      if (payload.retry) { schedule(350); return; }
      if (beforeLocal !== localSequence || (typeof latestAppliedFullRefreshSequence !== "undefined" && latestAppliedFullRefreshSequence > sequence)
          || (typeof latestAppliedPartRefreshSequence !== "undefined" && [...latestAppliedPartRefreshSequence.values()].some(value => value > sequence))) {
        schedule(350);
        return;
      }
      if (busy()) {
        announce("Có lịch mới. Trang sẽ cập nhật sau khi bạn hoàn tất thay đổi đang nhập hoặc tinh chỉnh.");
        return;
      }
      if (!payload.data || Number(payload.data.project?.id) !== projectId || !Array.isArray(payload.data.lessons)) throw new Error("invalid_schedule_payload");
      apply(payload, sequence);
    } catch (_) {
      announce("Chưa đồng bộ được lịch. Trang sẽ tự thử lại khi kết nối ổn định.");
      schedule(2000);
    } finally {
      window.clearTimeout(requestTimeout);
      inFlight = false;
    }
  }

  window.addEventListener("schedule-changed", event => {
    if (Number(event.detail?.project_id) !== projectId || event.detail?.revision === knownRevision) return;
    pending = true;
    schedule();
  });
  window.addEventListener("schedule-realtime-ready", () => schedule(0));
  window.addEventListener("online", () => schedule(0));
  window.addEventListener("pageshow", () => schedule(0));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) schedule(0); });
  document.addEventListener("focusout", () => { if (pending) schedule(350); });
  document.addEventListener("close", () => { if (pending) schedule(350); }, true);
  document.addEventListener("change", () => { if (pending) schedule(350); });
  // Public viewers have no socket. Authenticated viewers also poll as recovery
  // for a missed NOTIFY, a disconnected socket or a server restart.
  window.setInterval(() => void check(), shareUrl ? 5000 : 15000);
  schedule(0);
})();
