const nativeFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const response = await nativeFetch(...args);
  if (response.status === 401) {
    location.href = "/login";
    throw new Error("Phiên đăng nhập đã hết hạn");
  }
  return response;
};
async function readApiResponse(response) {
  const raw = await response.text();
  if (!raw) return { ok: response.ok, status: response.status };
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !("status" in parsed)) {
      parsed.status = response.status;
    }
    return parsed;
  } catch (error) {
    const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        detail:
          response.status === 404
            ? "Không tìm thấy dữ liệu yêu cầu."
            : `Máy chủ trả về lỗi ${statusLabel}.`,
      };
    }
    const invalid = new Error(
      `Phản hồi từ máy chủ không hợp lệ (${statusLabel}). Vui lòng tải lại trang và thử lại.`,
    );
    invalid.isInvalidServerResponse = true;
    invalid.cause = error;
    throw invalid;
  }
}
function formatApiDetail(detail) {
  if (detail == null) return "";
  if (typeof detail === "string" || typeof detail === "number")
    return String(detail).trim();
  if (Array.isArray(detail))
    return detail.map(formatApiDetail).filter(Boolean).join("; ");
  if (typeof detail === "object") {
    const nestedMessage = formatApiDetail(detail.message || detail.detail);
    if (nestedMessage) return nestedMessage;
    const message = typeof detail.msg === "string" ? detail.msg.trim() : "";
    if (message) {
      const location = Array.isArray(detail.loc)
        ? detail.loc.filter((part) => !["body", "query", "path"].includes(String(part)))
        : [];
      const field = location.length
        ? String(location[location.length - 1]).replace(/_/g, " ")
        : "";
      return field ? `${field}: ${message}` : message;
    }
    return "";
  }
  return String(detail).trim();
}
function apiErrorMessage(payload, fallback) {
  if (payload && typeof payload === "object") {
    const message = formatApiDetail(payload.message);
    if (message) return message;
    const detail = formatApiDetail(payload.detail);
    if (detail) return detail;
    const error = formatApiDetail(payload.error);
    if (error) return error;
  } else {
    const message = formatApiDetail(payload);
    if (message) return message;
  }
  return fallback;
}
function requestFailureMessage(error, fallback = "Mất kết nối tới máy chủ.") {
  return error?.isInvalidServerResponse || error?.message?.startsWith("Phản hồi từ máy chủ")
    ? error.message
    : fallback;
}
let data = window.INIT_DATA;
var PROJECT_ID = window.PROJECT_ID || window.INIT_DATA?.project?.id;
let entityType = "";
let entityId = null;
let pendingAssignmentGap = null;
let constraintDraftDirty = false;
let globalLocksDraftDirty = false;
let activeTapAssign = null;
const $ = (s) => document.querySelector(s);
const entityModal = $("#entityModal");
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>'"]/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
      c
      ],
  );
function projectMaxConsecutive() {
  return Math.max(1, Number(data?.project?.periods) || 1);
}
function projectMaxPeriodsDay() {
  return Math.max(
    1,
    (Number(data?.project?.sessions) || 1) *
    (Number(data?.project?.periods) || 1),
  );
}
function confirmAction(message, options = {}) {
  const customConfirm = window.OperationStatus?.confirm;
  if (typeof customConfirm === "function") {
    return customConfirm(message, options);
  }
  return Promise.resolve(window.confirm(String(message)));
}
function operationHeaders(headers = {}) {
  return { ...headers, "X-Skip-Operation-Status": "1" };
}
async function postJsonWithDisplacementConfirmation(url, payload, options = {}) {
  const send = async (confirmDisplacement = false, confirmedAffectedLessons = null) => {
    const response = await fetch(url, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        ...payload,
        confirm_displacement: confirmDisplacement,
        confirmed_affected_lessons: confirmedAffectedLessons,
      }),
    });
    return { response, result: await readApiResponse(response) };
  };

  let confirmDisplacement = false;
  let confirmedAffectedLessons = null;
  for (let attemptIndex = 0; attemptIndex < 3; attemptIndex++) {
    const attempt = await send(confirmDisplacement, confirmedAffectedLessons);
    if (!attempt.response.ok && attempt.result?.requires_confirmation) {
      const affected = Number(attempt.result.affected_lessons) || 0;
      const confirmed = await confirmAction(
        attempt.result.message ||
        `Thay đổi này sẽ đưa ${affected} tiết đang xếp về khay. Bạn có muốn tiếp tục không?`,
        {
          title: options.title || "Xác nhận thay đổi lịch",
          confirmText: options.confirmText || "Tiếp tục",
        },
      );
      if (!confirmed) return { ...attempt, cancelled: true };
      confirmDisplacement = true;
      confirmedAffectedLessons = affected;
      continue;
    }
    return { ...attempt, cancelled: false };
  }
  throw new Error("Lịch thay đổi liên tục trong lúc xác nhận. Hãy thử lưu lại.");
}

const actionStateTimers = new WeakMap();
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function actionStateMarkup(state, label) {
  if (state === "loading")
    return `<svg class="inline-action-icon inline-action-spinner" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.9-4"></path><polyline points="5 3 5 7 9 7"></polyline><path d="M4 13a8 8 0 0 0 14.9 4"></path><polyline points="19 21 19 17 15 17"></polyline></svg><span>${esc(label)}</span>`;
  if (state === "success")
    return `<svg class="inline-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg><span>${esc(label)}</span>`;
  if (state === "error")
    return `<svg class="inline-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5"></path><path d="M12 17h.01"></path><circle cx="12" cy="12" r="9"></circle></svg><span>${esc(label)}</span>`;
  return `<span>${esc(label)}</span>`;
}
function ensureInlineActionButton(button) {
  if (!button) return null;
  button.classList.add("inline-action-btn");
  let stage = button.querySelector(":scope > .inline-action-stage");
  if (stage) return stage;
  const idle = (button.textContent || "").trim() || "Thực hiện";
  button.dataset.actionIdleLabel = button.dataset.actionIdleLabel || idle;
  button.textContent = "";
  stage = document.createElement("span");
  stage.className = "inline-action-stage";
  const content = document.createElement("span");
  content.className = "inline-action-content";
  content.textContent = idle;
  stage.appendChild(content);
  button.appendChild(stage);
  return stage;
}
function setInlineActionState(button, state, labels = {}, resetAfter = 0) {
  const stage = ensureInlineActionButton(button);
  if (!stage) return;
  const previousTimer = actionStateTimers.get(button);
  if (previousTimer) clearTimeout(previousTimer);
  const idle = labels.idle || button.dataset.actionIdleLabel || "Thực hiện";
  const defaults = {
    loading: "Đang xử lý...",
    success: "Đã hoàn tất",
    error: "Chưa hoàn tất",
  };
  const label =
    state === "idle" ? idle : labels[state] || defaults[state] || idle;
  stage
    .querySelectorAll(".inline-action-content.inline-action-leaving")
    .forEach((node) => node.remove());
  const current = stage.querySelector(".inline-action-content");
  const next = document.createElement("span");
  next.className = `inline-action-content inline-action-enter inline-action-${state}`;
  next.innerHTML = actionStateMarkup(state, label);
  if (current) {
    current.classList.add("inline-action-leaving");
    const cleanup = () => current.remove();
    current.addEventListener("animationend", cleanup, { once: true });
    setTimeout(cleanup, 360);
  }
  stage.appendChild(next);
  button.dataset.actionState = state;
  button.disabled = state === "loading";
  button.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  if (resetAfter > 0) {
    const timer = setTimeout(
      () => setInlineActionState(button, "idle", { idle }),
      resetAfter,
    );
    actionStateTimers.set(button, timer);
  }
}
function showInlineActionFeedback(
  button,
  message,
  kind = "info",
  timeout = 4200,
) {
  if (!button) return;
  let feedback = button.parentElement?.querySelector(
    ":scope > .inline-action-feedback",
  );
  if (!message) {
    if (feedback) feedback.hidden = true;
    return;
  }
  if (!feedback) {
    feedback = document.createElement("span");
    feedback.className = "inline-action-feedback";
    button.insertAdjacentElement("afterend", feedback);
  }
  feedback.className = `inline-action-feedback is-${kind}`;
  feedback.textContent = String(message);
  feedback.hidden = false;
  if (timeout > 0)
    setTimeout(() => {
      if (feedback.isConnected) feedback.hidden = true;
    }, timeout);
}
function setScheduleFeedback(message, kind = "info", timeout = 4200) {
  // Không chèn trạng thái cạnh nút Xếp tự động nữa. Mọi kết quả được đưa vào
  // toast ở góc trên bên phải để nội dung trang không bị dịch/chèn thêm dòng.
  document
    .querySelectorAll("[data-schedule-action]")
    .forEach((button) => {
      const feedback = button.parentElement?.querySelector(
        ":scope > .inline-action-feedback",
      );
      if (feedback) feedback.hidden = true;
    });
  if (message) showToast(message, kind, timeout);
}
function setTrayActionStatus(state, message, resetAfter = 0) {
  // Trạng thái hoàn tất/lỗi của thao tác khay dùng toast thay cho dòng chữ
  // nằm trong panel. Loading đã được thể hiện ngay trên nút/thao tác hiện tại.
  const status = $("#trayActionStatus");
  if (status) status.hidden = true;
  if (!message || state === "loading") return;
  showToast(
    message,
    state === "success" ? "success" : state === "error" ? "error" : "info",
    resetAfter || 3600,
  );
}
function setEntityActionMessage(message, kind = "error") {
  const form = entityModal?.querySelector("form");
  if (!form) return;
  let node = form.querySelector("#entityActionMessage");
  if (!node) {
    node = document.createElement("p");
    node.id = "entityActionMessage";
    node.className = "inline-form-message";
    form.querySelector(".row.end")?.insertAdjacentElement("beforebegin", node);
  }
  if (!message) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  node.hidden = false;
  node.className = `inline-form-message is-${kind}`;
  node.textContent = String(message);
}
function entityActionError(button, message) {
  setInlineActionState(
    button,
    "error",
    { idle: "Lưu", error: "Kiểm tra lại" },
    1800,
  );
  setEntityActionMessage(message, "error");
}
let scheduleActionTimer = null;
let scheduleActionVersion = 0;
function scheduleActionMarkup(state) {
  if (state === "loading")
    return `<svg class="schedule-action-icon schedule-action-spinner" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.9-4"></path><polyline points="5 3 5 7 9 7"></polyline><path d="M4 13a8 8 0 0 0 14.9 4"></path><polyline points="19 21 19 17 15 17"></polyline></svg><span>Đang xếp...</span>`;
  if (state === "success")
    return `<svg class="schedule-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg><span>Đã xếp xong</span>`;
  if (state === "error")
    return `<svg class="schedule-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5"></path><path d="M12 17h.01"></path><circle cx="12" cy="12" r="9"></circle></svg><span>Chưa xếp được</span>`;
  return "<span>Xếp tự động</span>";
}
function setScheduleActionState(state, resetAfter = 0) {
  scheduleActionVersion += 1;
  const version = scheduleActionVersion;
  if (scheduleActionTimer) {
    clearTimeout(scheduleActionTimer);
    scheduleActionTimer = null;
  }
  document.querySelectorAll("[data-schedule-action]").forEach((button) => {
    const stage = button.querySelector(".schedule-action-stage");
    if (!stage) return;
    stage
      .querySelectorAll(".schedule-action-content.schedule-action-leaving")
      .forEach((node) => node.remove());
    const current = stage.querySelector(".schedule-action-content");
    const next = document.createElement("span");
    next.className = `schedule-action-content schedule-action-enter schedule-action-${state}`;
    next.innerHTML = scheduleActionMarkup(state);
    if (current) {
      current.classList.add("schedule-action-leaving");
      const cleanup = () => current.remove();
      current.addEventListener("animationend", cleanup, { once: true });
      setTimeout(cleanup, 360);
    }
    stage.appendChild(next);
    button.dataset.scheduleState = state;
    button.disabled = state === "loading";
    button.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  });
  if (resetAfter > 0)
    scheduleActionTimer = setTimeout(() => {
      if (version === scheduleActionVersion) setScheduleActionState("idle");
    }, resetAfter);
}
function launchConfetti() {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;

  document.querySelectorAll(".schedule-confetti-canvas").forEach((node) =>
    node.remove(),
  );
  const canvas = document.createElement("canvas");
  canvas.className = "schedule-confetti-canvas";
  canvas.style.position = "fixed";
  canvas.style.inset = "0";
  canvas.style.width = "100vw";
  canvas.style.height = "100vh";
  canvas.style.pointerEvents = "none";
  canvas.style.zIndex = "999";
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    canvas.remove();
    return;
  }

  let width = 0;
  let height = 0;
  const resizeCanvas = () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  };
  resizeCanvas();
  window.addEventListener("resize", resizeCanvas, { passive: true });

  const colors = [
    "#2563eb",
    "#06b6d4",
    "#10b981",
    "#f5b83d",
    "#ec4899",
    "#8b5cf6",
  ];
  const particles = [];
  for (let i = 0; i < 120; i++) {
    particles.push({
      x: Math.random() * width,
      y: Math.random() * height - height,
      r: Math.random() * 6 + 4,
      d: Math.random() * width,
      color: colors[Math.floor(Math.random() * colors.length)],
      tilt: Math.random() * 10 - 5,
      tiltAngleIncremental: Math.random() * 0.07 + 0.02,
      tiltAngle: 0,
      velocity: Math.random() * 3 + 2,
    });
  }

  let animationFrameId = null;
  const startedAt = performance.now();
  const cleanup = () => {
    if (animationFrameId != null) cancelAnimationFrame(animationFrameId);
    window.removeEventListener("resize", resizeCanvas);
    canvas.remove();
  };
  function draw(now) {
    if (!canvas.isConnected) {
      cleanup();
      return;
    }
    ctx.clearRect(0, 0, width, height);
    let active = false;
    for (const particle of particles) {
      particle.tiltAngle += particle.tiltAngleIncremental;
      particle.y +=
        ((Math.cos(particle.d) + 3 + particle.r / 2) / 2) *
        particle.velocity *
        0.7;
      particle.x += Math.sin(particle.tiltAngle) * 0.5;
      if (particle.y < height) active = true;
      ctx.beginPath();
      ctx.lineWidth = particle.r;
      ctx.strokeStyle = particle.color;
      ctx.moveTo(particle.x + particle.r / 2 + particle.tilt, particle.y);
      ctx.lineTo(
        particle.x + particle.tilt,
        particle.y + particle.tilt + particle.r / 2,
      );
      ctx.stroke();
    }
    if (active && now - startedAt < 3500)
      animationFrameId = requestAnimationFrame(draw);
    else cleanup();
  }
  animationFrameId = requestAnimationFrame(draw);
}

function captureRefreshScrollState() {
  const root =
    document.scrollingElement || document.documentElement || document.body,
    table = document.querySelector("#scheduleGrid .timetable"),
    content = document.querySelector(".workspace .content");
  const tableRect = table ? table.getBoundingClientRect() : null;
  return {
    pageTop: window.pageYOffset ?? window.scrollY ?? root?.scrollTop ?? 0,
    pageLeft: window.pageXOffset ?? window.scrollX ?? root?.scrollLeft ?? 0,
    tableTop: table ? table.scrollTop : null,
    tableLeft: table ? table.scrollLeft : null,
    tableRectTop: tableRect ? tableRect.top : null,
    contentTop: content ? content.scrollTop : null,
    contentLeft: content ? content.scrollLeft : null,
  };
}
function restoreRefreshScrollState(state) {
  if (!state) return;
  const apply = () => {
    const table = document.querySelector("#scheduleGrid .timetable"),
      content = document.querySelector(".workspace .content"),
      root =
        document.scrollingElement || document.documentElement || document.body;

    if (table) {
      const top = state.tableTop ?? table.scrollTop;
      const left = state.tableLeft ?? table.scrollLeft;
      try {
        table.scrollTo({ top, left, behavior: "instant" });
      } catch {
        table.scrollTop = top;
        table.scrollLeft = left;
      }
    }

    if (content && (state.contentTop != null || state.contentLeft != null)) {
      const top = state.contentTop ?? content.scrollTop;
      const left = state.contentLeft ?? content.scrollLeft;
      try {
        content.scrollTo({ top, left, behavior: "instant" });
      } catch {
        content.scrollTop = top;
        content.scrollLeft = left;
      }
    }

    let targetPageTop = state.pageTop ?? 0;
    let targetPageLeft = state.pageLeft ?? 0;

    if (state.tableRectTop != null && table) {
      const currentRect = table.getBoundingClientRect();
      const deltaY = currentRect.top - state.tableRectTop;
      if (Math.abs(deltaY) > 1) {
        targetPageTop += deltaY;
      }
    }

    try {
      window.scrollTo({
        top: targetPageTop,
        left: targetPageLeft,
        behavior: "instant",
      });
    } catch {
      window.scrollTo(targetPageLeft, targetPageTop);
    }
    if (root) {
      root.scrollTop = targetPageTop;
      root.scrollLeft = targetPageLeft;
    }
  };

  apply();
  requestAnimationFrame(apply);
}
let refreshRequestSequence = 0;
let latestFullRefreshSequence = 0;
const latestPartRefreshSequence = new Map();

async function refresh(skipOperationStatus = false, parts = null) {
  const scrollState = captureRefreshScrollState(),
    init = skipOperationStatus ? { headers: operationHeaders() } : undefined,
    requestedParts = Array.isArray(parts)
      ? [...new Set(parts.filter(Boolean))].sort()
      : [],
    query = requestedParts.length
      ? `?parts=${encodeURIComponent(requestedParts.join(","))}`
      : "",
    sequence = ++refreshRequestSequence,
    isFullRefresh = requestedParts.length === 0;

  if (isFullRefresh) {
    latestFullRefreshSequence = sequence;
  } else {
    requestedParts.forEach((part) =>
      latestPartRefreshSequence.set(part, sequence),
    );
  }

  const requestWasSuperseded = () =>
    isFullRefresh
      ? sequence !== latestFullRefreshSequence
      : latestFullRefreshSequence > sequence ||
      requestedParts.every(
        (part) => (latestPartRefreshSequence.get(part) || 0) !== sequence,
      );

  let r;
  try {
    r = await fetch(`/api/projects/${PROJECT_ID}/data${query}`, init);
  } catch (error) {
    if (requestWasSuperseded()) return data;
    throw error;
  }
  const result = await readApiResponse(r);
  if (!r.ok) {
    if (requestWasSuperseded()) return data;
    const error = new Error(
      apiErrorMessage(result, "Không thể tải lại dữ liệu từ máy chủ."),
    );
    error.isRefreshError = true;
    throw error;
  }
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    if (requestWasSuperseded()) return data;
    const error = new Error("Dữ liệu trả về từ máy chủ không hợp lệ.");
    error.isRefreshError = true;
    throw error;
  }

  const appliedParts = [];
  if (isFullRefresh) {
    // Một full refresh cũ không được phép ghi đè full refresh mới hơn. Với
    // từng phần dữ liệu, giữ lại kết quả của partial refresh được gửi sau nó.
    if (sequence !== latestFullRefreshSequence) return data;
    const merged = { ...data };
    Object.entries(result).forEach(([key, value]) => {
      const newerPartial = latestPartRefreshSequence.get(key) || 0;
      if (newerPartial > sequence) return;
      merged[key] = value;
      appliedParts.push(key);
    });
    data = merged;
  } else {
    // Nếu một full refresh mới hơn đã được gửi, hoặc có partial refresh mới
    // hơn cho cùng phần, response hiện tại đã lỗi thời và phải bỏ qua.
    if (latestFullRefreshSequence > sequence) return data;
    const patch = {};
    requestedParts.forEach((part) => {
      if ((latestPartRefreshSequence.get(part) || 0) !== sequence) return;
      if (!Object.prototype.hasOwnProperty.call(result, part)) return;
      patch[part] = result[part];
      appliedParts.push(part);
    });
    if (!appliedParts.length) return data;
    data = { ...data, ...patch };
  }

  if (typeof clearTapAssign === "function") clearTapAssign();
  if (appliedParts.length === 1 && appliedParts[0] === "lessons") {
    renderScheduleAfterLessonChange();
  } else {
    renderAll();
  }
  restoreRefreshScrollState(scrollState);
  requestAnimationFrame(() => restoreRefreshScrollState(scrollState));
  return data;
}
async function refreshAfterSuccessfulMutation(parts = null, message = null) {
  try {
    await refresh(true, parts);
    return true;
  } catch (error) {
    const detail = error?.message || requestFailureMessage(error);
    showToast(
      message ||
      `Thay đổi đã được lưu trên máy chủ nhưng giao diện chưa thể đồng bộ dữ liệu mới: ${detail}`,
      "warning",
      6000,
    );
    return false;
  }
}
function restoreTransientActionButton(button, original, message, delay = 1400) {
  const errorMessage = message || "Thao tác chưa hoàn tất.";
  showToast(errorMessage, "error", Math.max(3600, delay + 1200));
  if (!button) return;

  const originalTitle = button.title || "";
  const originalAriaLabel = button.getAttribute("aria-label") || "";
  button.disabled = false;
  button.textContent = "!";
  button.title = errorMessage;
  button.setAttribute("aria-label", errorMessage);

  setTimeout(() => {
    if (!button.isConnected) return;
    button.textContent = original;
    button.title = originalTitle;
    if (originalAriaLabel) button.setAttribute("aria-label", originalAriaLabel);
    else button.removeAttribute("aria-label");
    button.disabled = false;
  }, delay);
}
function hasUnsavedConstraintChanges() {
  return constraintDraftDirty || globalLocksDraftDirty;
}
function discardUnsavedConstraintChanges() {
  constraintDraftDirty = false;
  globalLocksDraftDirty = false;
}
async function confirmDiscardConstraintChanges(message) {
  if (!hasUnsavedConstraintChanges()) return true;
  return confirmAction(
    message ||
    "Bạn có thay đổi ràng buộc chưa lưu. Nếu tiếp tục, các thay đổi này sẽ bị bỏ.",
    { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
  );
}
function syncMobileNavSelect(tabName = null) {
  const select = document.querySelector("#mobileNavSelect");
  if (!select) return;
  const activeTab =
    tabName || document.querySelector(".nav.active")?.dataset.tab || "overview";
  if ([...select.options].some((option) => option.value === activeTab)) {
    select.value = activeTab;
  }
}

let currentWorkspaceTabTransition = null;

function cancelCurrentWorkspaceTabTransition() {
  if (currentWorkspaceTabTransition) {
    currentWorkspaceTabTransition.cleanup();
    currentWorkspaceTabTransition = null;
  }
}

async function activateWorkspaceTab(tabName, options = {}) {
  const b = document.querySelector(`.nav[data-tab="${tabName}"]`);
  if (!b) {
    syncMobileNavSelect();
    return false;
  }
  const currentActiveNav = document.querySelector(".nav.active");
  const current = currentActiveNav?.dataset.tab;
  if (current === tabName) {
    syncMobileNavSelect(tabName);
    return true;
  }
  if (current === "constraints" && tabName !== "constraints") {
    const confirmed = await confirmDiscardConstraintChanges(
      "Bạn có thay đổi trong Ràng buộc chưa lưu. Rời tab này sẽ bỏ các thay đổi đó.",
    );
    if (!confirmed) {
      syncMobileNavSelect(current);
      return false;
    }
    discardUnsavedConstraintChanges();
  }
  if (typeof clearTapAssign === "function") clearTapAssign();

  // If an animation is in progress, finalize it cleanly immediately
  cancelCurrentWorkspaceTabTransition();

  const tabOld = current ? document.getElementById(current) : null;
  const tabNew = document.getElementById(tabName);

  document
    .querySelectorAll(".nav")
    .forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  syncMobileNavSelect(b.dataset.tab);

  const stage =
    document.getElementById("workspaceTabsStage") ||
    document.querySelector(".workspace .content");
  const prefersReduced = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;

  // Immediate mode for first load, reduced motion, or missing elements
  if (!tabOld || !tabNew || !stage || prefersReduced || options.immediate) {
    document
      .querySelectorAll(".tab")
      .forEach((x) =>
        x.classList.remove(
          "active",
          "is-sliding-out",
          "is-sliding-in",
        ),
      );
    if (tabNew) tabNew.classList.add("active");
    if (tabName === "schedule") renderSchedule();
    if (tabName === "constraints") renderConstraintSelectors({ force: true });
    if (tabName === "preferences") loadPreferenceInbox();
    return true;
  }

  // Pre-render hooks so content is ready as it slides in
  if (tabName === "schedule") renderSchedule();
  if (tabName === "constraints") renderConstraintSelectors({ force: true });
  if (tabName === "preferences") loadPreferenceInbox();

  // Reset scroll of the incoming tab to the top so it enters cleanly
  tabNew.scrollTop = 0;

  // Determine direction based on nav order
  const navTabs = [...document.querySelectorAll(".nav[data-tab]")].map(
    (el) => el.dataset.tab,
  );
  const oldIndex = navTabs.indexOf(current);
  const newIndex = navTabs.indexOf(tabName);
  const isMovingDown =
    newIndex >= 0 && oldIndex >= 0 ? newIndex > oldIndex : true;

  const startNewY = isMovingDown ? "100%" : "-100%";
  const endOldY = isMovingDown ? "-100%" : "100%";
  const shadowClass = isMovingDown ? "shadow-top" : "shadow-bottom";

  // Pre-set offscreen transform, opacity fade, and soft blur BEFORE displaying
  tabNew.style.transform = `translateY(${startNewY})`;
  tabNew.style.opacity = "0.2";
  tabNew.style.filter = "blur(3px)";

  tabOld.style.transform = "translateY(0)";
  tabOld.style.opacity = "1";
  tabOld.style.filter = "blur(0px)";

  tabOld.classList.remove("active");
  tabOld.classList.add("is-sliding-out");

  tabNew.classList.add("active", "is-sliding-in", shadowClass);

  // Force reflow so browser commits the initial state
  void tabNew.offsetHeight;

  const duration = 420;
  const easing = "cubic-bezier(0.76, 0, 0.24, 1)";

  let animOld = null;
  let animNew = null;
  let cleaned = false;

  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    if (animOld) {
      try {
        animOld.cancel();
      } catch (_) { }
    }
    if (animNew) {
      try {
        animNew.cancel();
      } catch (_) { }
    }
    tabOld.style.transform = "";
    tabOld.style.opacity = "";
    tabOld.style.filter = "";

    tabNew.style.transform = "";
    tabNew.style.opacity = "";
    tabNew.style.filter = "";

    tabOld.classList.remove("is-sliding-out");
    tabNew.classList.remove("is-sliding-in", "shadow-top", "shadow-bottom");
    currentWorkspaceTabTransition = null;
  };

  currentWorkspaceTabTransition = { cleanup };

  if (typeof tabNew.animate === "function") {
    animOld = tabOld.animate(
      [
        { transform: "translateY(0)", opacity: 1, filter: "blur(0px)" },
        {
          transform: `translateY(${endOldY})`,
          opacity: 0.2,
          filter: "blur(3px)",
        },
      ],
      { duration, easing, fill: "forwards" },
    );

    animNew = tabNew.animate(
      [
        {
          transform: `translateY(${startNewY})`,
          opacity: 0.2,
          filter: "blur(3px)",
        },
        { transform: "translateY(0)", opacity: 1, filter: "blur(0px)" },
      ],
      { duration, easing, fill: "forwards" },
    );

    animNew.onfinish = cleanup;
  } else {
    tabOld.style.transition = `transform ${duration}ms ${easing}, opacity ${duration}ms ${easing}, filter ${duration}ms ${easing}`;
    tabNew.style.transition = `transform ${duration}ms ${easing}, opacity ${duration}ms ${easing}, filter ${duration}ms ${easing}`;
    requestAnimationFrame(() => {
      tabOld.style.transform = `translateY(${endOldY})`;
      tabOld.style.opacity = "0.2";
      tabOld.style.filter = "blur(3px)";

      tabNew.style.transform = "translateY(0)";
      tabNew.style.opacity = "1";
      tabNew.style.filter = "blur(0px)";
      setTimeout(cleanup, duration + 20);
    });
  }

  return true;
}
document
  .querySelectorAll(".nav")
  .forEach((b) => (b.onclick = () => void activateWorkspaceTab(b.dataset.tab)));
document.querySelector("#mobileNavSelect")?.addEventListener("change", (event) => {
  void activateWorkspaceTab(event.target.value);
});
syncMobileNavSelect();
function activateRequestedWorkspaceTab() {
  const tab = new URLSearchParams(window.location.search).get("tab");
  if (tab) void activateWorkspaceTab(tab, { immediate: true });
}
window.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedConstraintChanges()) return;
  event.preventDefault();
  event.returnValue = "";
});
function bulkEntityToolbar(type) {
  return `<div class="entity-bulk-toolbar" data-bulk-toolbar="${type}"><span class="entity-bulk-count"><b data-bulk-count>0</b> mục được chọn</span><button class="btn ghost entity-bulk-delete" type="button" onclick="deleteSelectedEntities('${type}',this)" disabled>Xóa đã chọn</button></div>`;
}
function bulkEntityHeader(type) {
  return `<th class="entity-select-col"><input class="entity-select-all" type="checkbox" aria-label="Chọn tất cả" onchange="toggleAllEntityRows('${type}',this.checked)"></th>`;
}
function bulkEntityCell(type, id) {
  return `<td class="entity-select-col"><input class="entity-row-select" type="checkbox" data-entity-id="${Number(id)}" aria-label="Chọn mục này" onchange="syncEntityBulkControls('${type}')"></td>`;
}
function bulkEntityTableShell(type, tableHtml) {
  return `<div class="entity-table-shell" data-bulk-table="${type}">${bulkEntityToolbar(type)}${tableHtml}</div>`;
}
function table(rows, cols, type) {
  if (!rows.length) return '<div class="empty-state">Chưa có dữ liệu.</div>';
  const canEdit = ["subject", "teacher", "grade", "class"].includes(type);
  const tableHtml = `<table class="data-table"><thead><tr>${bulkEntityHeader(type)}${cols.map((c) => `<th>${c[0]}</th>`).join("")}<th></th></tr></thead><tbody>${rows.map((r) => `<tr>${bulkEntityCell(type, r.id)}${cols.map((c) => `<td>${esc(typeof c[1] === "function" ? c[1](r) : r[c[1]])}</td>`).join("")}<td><div class="row end">${canEdit ? `<button class="action-link" onclick="openEntityEdit('${type}',${r.id})">Sửa</button>` : ""}<button class="danger-link" onclick="delEntity('${type}',${r.id},this)">Xóa</button></div></td></tr>`).join("")}</tbody></table>`;
  return bulkEntityTableShell(type, tableHtml);
}
function entityBulkRoot(type) {
  return document.querySelector(`[data-bulk-table="${type}"]`);
}
function selectedEntityIds(type) {
  const root = entityBulkRoot(type);
  if (!root) return [];
  return [...root.querySelectorAll(".entity-row-select:checked")]
    .map((input) => Number(input.dataset.entityId || 0))
    .filter((id) => id > 0);
}
function syncEntityBulkControls(type) {
  const root = entityBulkRoot(type);
  if (!root) return;
  const boxes = [...root.querySelectorAll(".entity-row-select")];
  const selected = boxes.filter((input) => input.checked);
  const master = root.querySelector(".entity-select-all");
  const count = root.querySelector("[data-bulk-count]");
  const button = root.querySelector(".entity-bulk-delete");
  if (master) {
    master.checked = boxes.length > 0 && selected.length === boxes.length;
    master.indeterminate = selected.length > 0 && selected.length < boxes.length;
  }
  if (count) count.textContent = String(selected.length);
  if (button) {
    const label = selected.length ? `Xóa đã chọn (${selected.length})` : "Xóa đã chọn";
    button.disabled = selected.length === 0;
    button.dataset.actionIdleLabel = label;
    if (button.dataset.actionState !== "loading") button.textContent = label;
  }
}
function toggleAllEntityRows(type, checked) {
  const root = entityBulkRoot(type);
  if (!root) return;
  root
    .querySelectorAll(".entity-row-select")
    .forEach((input) => (input.checked = Boolean(checked)));
  syncEntityBulkControls(type);
}
async function deleteSelectedEntities(type, button) {
  const ids = selectedEntityIds(type);
  if (!ids.length) return;
  const confirmed = await confirmAction(
    `Xóa ${ids.length} mục đã chọn? Mục đang được sử dụng sẽ được giữ lại.`,
    { confirmText: `Xóa ${ids.length} mục` },
  );
  if (!confirmed) return;
  setInlineActionState(button, "loading", {
    idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
    loading: "Đang xóa...",
  });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/entities/bulk`, {
      method: "DELETE",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ type, ids }),
    });
    const result = await readApiResponse(r);
    if (!r.ok) {
      setInlineActionState(
        button,
        "error",
        { idle: button.dataset.actionIdleLabel || "Xóa đã chọn", error: "Không thể xóa" },
        2200,
      );
      showToast(
        apiErrorMessage(result, "Không thể xóa các mục đã chọn."),
        "error",
        4800,
      );
      return;
    }
    setInlineActionState(button, "success", {
      idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
      success: `Đã xóa ${Number(result.deleted || ids.length)} mục`,
    });
    showToast(
      result.message || `Đã xóa ${Number(result.deleted || ids.length)} mục.`,
      Array.isArray(result.skipped) && result.skipped.length ? "warning" : "success",
      4800,
    );
    await wait(500);
    await refreshAfterSuccessfulMutation();
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: button.dataset.actionIdleLabel || "Xóa đã chọn", error: "Chưa hoàn tất" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 4800);
  }
}
function describeBlockMode(mode, total) {
  if (mode === "required_double") {
    const pairs = Math.floor(total / 2),
      single = total % 2;
    return `Bắt buộc tiết đôi · ${pairs ? `${pairs} cặp × 2 tiết` : ""}${pairs && single ? " + " : ""}${single ? "1 tiết đơn" : ""}`;
  }
  if (mode === "preferred_double")
    return "Ưu tiên tiết đôi · có thể tách khi cần";
  return "Tự do · xếp riêng hoặc liền nhau";
}
function teacherLoadStats(teacher, projected = null) {
  const current = Number(teacher?.assigned_periods || 0),
    capacity =
      teacher?.week_capacity == null ? null : Number(teacher.week_capacity),
    maxDay = Number(teacher?.max_periods_day || 0);
  const next =
    projected == null || !Number.isFinite(Number(projected))
      ? current
      : Math.max(0, Number(projected));
  const remaining =
    capacity == null || !Number.isFinite(capacity) ? null : capacity - next;
  return {
    current,
    capacity,
    maxDay,
    projected: next,
    remaining,
    over: remaining != null && remaining < 0,
  };
}
function teacherLoadCardHtml(teacher, projected = null) {
  if (!teacher) return "";
  const load = teacherLoadStats(teacher, projected),
    capacityText = load.capacity == null ? "—" : load.capacity;
  return `<div class="assignment-load-card assignment-load-card-live"><div class="assignment-load-metric ${load.over ? "over" : ""}"><small>Tải giáo viên</small><b>${load.projected}/${capacityText} tiết/tuần</b></div><div class="assignment-load-metric"><small>Tối đa/ngày</small><b>${load.maxDay || "—"} tiết/ngày</b></div></div>`;
}
function teacherLoadCellHtml(teacher) {
  if (!teacher) return '<span class="muted">—</span>';
  const load = teacherLoadStats(teacher),
    capacityText = load.capacity == null ? "—" : load.capacity;
  return `<div class="assignment-load-cell ${load.over ? "over" : ""}"><b>${load.current}/${capacityText} tiết/tuần</b><small>Tối đa ${load.maxDay || "—"} tiết/ngày</small></div>`;
}
function updateAssignmentEditLoad(form) {
  if (!form) return;
  const assignmentId = Number(
    form.querySelector('[name="assignment_id"]')?.value || 0,
  ),
    item = data.assignments.find((row) => row.id === assignmentId),
    box = form.querySelector("[data-assignment-edit-load]");
  if (!item || !box) return;
  const teacher = data.teachers.find((row) => row.id === item.teacher_id),
    nextPeriods = Number(
      form.querySelector('[name="periods_per_week"]')?.value || 0,
    ),
    currentTeacherLoad = Number(teacher?.assigned_periods || 0),
    oldPeriods = Number(item.periods_per_week || 0),
    projected = Math.max(0, currentTeacherLoad - oldPeriods + nextPeriods);
  box.innerHTML = teacherLoadCardHtml(teacher, projected);
}
function updateAssignmentEditPreview(form) {
  updateBlockModePreview(form);
  updateAssignmentEditLoad(form);
}
function assignmentFilterState() {
  return {
    classId: Number($("#assignmentFilterClass")?.value || 0),
    subjectId: Number($("#assignmentFilterSubject")?.value || 0),
    teacherId: Number($("#assignmentFilterTeacher")?.value || 0),
    status: $("#assignmentFilterStatus")?.value || "all",
  };
}
function assignmentMissingRows() {
  const assignments = data.assignments || [],
    classes = data.classes || [],
    subjects = data.subjects || [],
    grades = data.grades || [],
    requirements = data.grade_requirements || [];
  const assignmentByPair = new Map(
    assignments.map((item) => [`${item.class_id}:${item.subject_id}`, item]),
  );
  const requirementsByGrade = new Map();
  requirements.forEach((item) => {
    const key = Number(item.grade_id);
    if (!requirementsByGrade.has(key)) requirementsByGrade.set(key, []);
    requirementsByGrade.get(key).push(item);
  });
  const result = [];
  for (const schoolClass of classes) {
    if (schoolClass.grade_id == null) continue;
    const gradeId = Number(schoolClass.grade_id),
      grade = grades.find((item) => item.id === gradeId);
    for (const requirement of requirementsByGrade.get(gradeId) || []) {
      const subject = subjects.find(
        (item) => item.id === requirement.subject_id,
      ),
        assignment = assignmentByPair.get(
          `${schoolClass.id}:${requirement.subject_id}`,
        );
      if (!assignment) {
        result.push({
          issue_type: "missing",
          class_id: schoolClass.id,
          class_name: schoolClass.name,
          subject_id: requirement.subject_id,
          subject_name: subject?.name || "?",
          grade_id: gradeId,
          grade_name: grade?.name || "?",
          required_periods: requirement.periods_per_week,
          required_mode: requirement.block_mode,
        });
        continue;
      }
      if (
        Number(assignment.periods_per_week) !==
        Number(requirement.periods_per_week) ||
        String(assignment.block_mode || "free") !==
        String(requirement.block_mode || "free")
      ) {
        result.push({
          issue_type: "mismatch",
          assignment_id: assignment.id,
          assigned_teacher_id: assignment.teacher_id,
          assigned_teacher_name: assignment.teacher_name || "",
          class_id: schoolClass.id,
          class_name: schoolClass.name,
          subject_id: requirement.subject_id,
          subject_name: subject?.name || "?",
          grade_id: gradeId,
          grade_name: grade?.name || "?",
          required_periods: requirement.periods_per_week,
          required_mode: requirement.block_mode,
          assigned_periods: assignment.periods_per_week,
          assigned_mode: assignment.block_mode || "free",
        });
      }
    }
  }
  return result.sort(
    (a, b) =>
      String(a.class_name).localeCompare(String(b.class_name), "vi") ||
      String(a.subject_name).localeCompare(String(b.subject_name), "vi"),
  );
}
function assignmentUnassignedClasses() {
  const assigned = new Set(
    (data.assignments || []).map((item) => item.class_id),
  );
  return (data.classes || []).filter((item) => !assigned.has(item.id));
}
function assignmentEligibleTeachers() {
  // Tài khoản đăng ký và hồ sơ giáo viên dùng cho xếp lịch là hai khái niệm
  // tách biệt. Chỉ giáo viên đã được quản trị viên cấu hình ít nhất một môn dạy
  // mới có thể xuất hiện trong form tạo phân công.
  return (data.teachers || []).filter(
    (teacher) => Array.isArray(teacher.subject_ids) && teacher.subject_ids.length > 0,
  );
}
function assignmentFilterTeachers() {
  // Bộ lọc chỉ cần các giáo viên thực sự đang có phân công trong project.
  const usedIds = new Set(
    (data.assignments || []).map((item) => Number(item.teacher_id)),
  );
  return (data.teachers || []).filter((teacher) => usedIds.has(Number(teacher.id)));
}
function renderAssignmentFilters() {
  const classEl = $("#assignmentFilterClass"),
    subjectEl = $("#assignmentFilterSubject"),
    teacherEl = $("#assignmentFilterTeacher"),
    statusEl = $("#assignmentFilterStatus");
  if (!classEl || !subjectEl || !teacherEl || !statusEl) return;
  const current = {
    classId: classEl.value,
    subjectId: subjectEl.value,
    teacherId: teacherEl.value,
    status: statusEl.value || "all",
  };
  classEl.innerHTML =
    '<option value="">Tất cả lớp</option>' + opts(data.classes);
  subjectEl.innerHTML =
    '<option value="">Tất cả môn</option>' + opts(data.subjects);
  teacherEl.innerHTML =
    '<option value="">Tất cả giáo viên</option>' + opts(assignmentFilterTeachers());
  if ([...classEl.options].some((o) => o.value === current.classId))
    classEl.value = current.classId;
  if ([...subjectEl.options].some((o) => o.value === current.subjectId))
    subjectEl.value = current.subjectId;
  if ([...teacherEl.options].some((o) => o.value === current.teacherId))
    teacherEl.value = current.teacherId;
  statusEl.value = current.status;
  const applyStatusUi = () => {
    const unassignedOnly = statusEl.value === "unassigned_class",
      checkingProgram = statusEl.value === "missing";
    subjectEl.disabled = unassignedOnly;
    teacherEl.disabled = unassignedOnly;
    subjectEl.title = unassignedOnly
      ? "Bộ lọc môn không áp dụng cho lớp chưa có phân công."
      : "";
    teacherEl.title = unassignedOnly
      ? "Bộ lọc giáo viên không áp dụng cho lớp chưa có phân công."
      : checkingProgram
        ? "Trong chế độ kiểm tra chương trình, bộ lọc giáo viên chỉ áp dụng cho các phân công hiện có; dòng chưa phân công chưa có giáo viên để lọc."
        : "";
  };
  applyStatusUi();
  statusEl.onchange = () => {
    if (statusEl.value === "unassigned_class") {
      subjectEl.value = "";
      teacherEl.value = "";
    }
    applyStatusUi();
    renderAssignmentTable();
  };
}
function resetAssignmentFilters() {
  [
    "assignmentFilterClass",
    "assignmentFilterSubject",
    "assignmentFilterTeacher",
  ].forEach((id) => {
    const el = $("#" + id);
    if (el) el.value = "";
  });
  if ($("#assignmentFilterStatus")) $("#assignmentFilterStatus").value = "all";
  renderAssignmentFilters();
  renderAssignmentTable();
}
function assignmentSummaryHtml() {
  const issues = assignmentMissingRows(),
    unassigned = assignmentUnassignedClasses(),
    requirements = data.grade_requirements || [],
    classes = data.classes || [],
    grades = data.grades || [];
  const missing = issues.filter((item) => item.issue_type === "missing"),
    mismatch = issues.filter((item) => item.issue_type === "mismatch"),
    affected = new Set(issues.map((item) => item.class_id));
  const configuredGrades = new Set(
    requirements.map((item) => Number(item.grade_id)),
  ),
    classesWithoutGrade = classes.filter((item) => item.grade_id == null),
    gradesWithoutProgram = grades.filter(
      (item) => !configuredGrades.has(item.id),
    );
  if (!requirements.length) {
    return '<div class="assignment-filter-summary has-gap"><b>Kiểm tra phân công:</b> Chưa có chương trình môn chuẩn cho khối. Vào <b>Khối / nhóm lớp → Sửa</b> để chọn môn và số tiết/tuần; sau đó hệ thống mới có thể phát hiện thiếu chính xác.</div>';
  }
  const parts = [];
  if (missing.length)
    parts.push(`<b>${missing.length}</b> cặp lớp–môn còn thiếu`);
  if (mismatch.length)
    parts.push(`<b>${mismatch.length}</b> phân công lệch số tiết/chế độ chuẩn`);
  if (unassigned.length)
    parts.push(`<b>${unassigned.length}</b> lớp chưa có phân công nào`);
  if (classesWithoutGrade.length)
    parts.push(`<b>${classesWithoutGrade.length}</b> lớp chưa gán khối`);
  if (gradesWithoutProgram.length)
    parts.push(
      `<b>${gradesWithoutProgram.length}</b> khối chưa cấu hình chương trình`,
    );
  if (!parts.length)
    return '<div class="assignment-filter-summary"><b>Kiểm tra phân công:</b> Phân công hiện tại khớp với chương trình môn đã cấu hình cho các khối.</div>';
  return `<div class="assignment-filter-summary has-gap"><b>Kiểm tra phân công:</b> ${parts.join(" · ")}.${affected.size ? ` Có <b>${affected.size} lớp</b> cần kiểm tra.` : ""}</div>`;
}
function assignmentTable() {
  const state = assignmentFilterState();
  if (state.status === "missing") {
    let rows = assignmentMissingRows();
    if (state.classId)
      rows = rows.filter((item) => item.class_id === state.classId);
    if (state.subjectId)
      rows = rows.filter((item) => item.subject_id === state.subjectId);
    if (state.teacherId) {
      rows = rows.filter(
        (item) =>
          item.issue_type === "mismatch" &&
          Number(item.assigned_teacher_id) === state.teacherId,
      );
    }
    if (!rows.length)
      return '<div class="assignment-filter-empty">Không có cặp lớp–môn nào lệch chương trình với bộ lọc hiện tại.</div>';
    return `<table class="data-table"><thead><tr><th>Lớp</th><th>Khối</th><th>Môn</th><th>Giáo viên hiện tại</th><th>Chương trình chuẩn</th><th>Trạng thái</th><th></th></tr></thead><tbody>${rows
      .map((item) => {
        const required = `${item.required_periods} tiết/tuần · ${describeBlockMode(item.required_mode, item.required_periods)}`;
        if (item.issue_type === "mismatch") {
          const current = `${item.assigned_periods} tiết/tuần · ${describeBlockMode(item.assigned_mode, item.assigned_periods)}`;
          return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(item.assigned_teacher_name || "—")}</td><td>${esc(required)}</td><td><span class="assignment-gap-badge">Đang có: ${esc(current)}</span></td><td><button class="action-link" onclick="openAssignmentEdit(${item.assignment_id})">Sửa phân công</button></td></tr>`;
        }
        return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>—</td><td>${esc(required)}</td><td><span class="assignment-gap-badge">Chưa phân công</span></td><td><button class="action-link" onclick="openEntity('assignment',{classId:${item.class_id},subjectId:${item.subject_id}})">+ Thêm phân công</button></td></tr>`;
      })
      .join("")}</tbody></table>`;
  }
  if (state.status === "unassigned_class") {
    let rows = assignmentUnassignedClasses();
    if (state.classId) rows = rows.filter((item) => item.id === state.classId);
    if (!rows.length)
      return '<div class="assignment-filter-empty">Không có lớp chưa phân công với bộ lọc hiện tại.</div>';
    return `<table class="data-table"><thead><tr><th>Lớp</th><th>Khối</th><th>Trạng thái</th><th></th></tr></thead><tbody>${rows
      .map((item) => {
        const grade = data.grades.find((g) => g.id === item.grade_id);
        return `<tr><td><b>${esc(item.name)}</b></td><td>${esc(grade?.name || "—")}</td><td><span class="assignment-gap-badge">Chưa có phân công</span></td><td><button class="action-link" onclick="openEntity('assignment',{classId:${item.id}})">+ Thêm phân công</button></td></tr>`;
      })
      .join("")}</tbody></table>`;
  }
  let rows = data.assignments || [];
  if (state.classId)
    rows = rows.filter((item) => item.class_id === state.classId);
  if (state.subjectId)
    rows = rows.filter((item) => item.subject_id === state.subjectId);
  if (state.teacherId)
    rows = rows.filter((item) => item.teacher_id === state.teacherId);
  if (!rows.length)
    return `<div class="assignment-filter-empty">${data.assignments?.length ? "Không có phân công phù hợp với bộ lọc hiện tại." : "Chưa có phân công. Hãy gắn lớp – môn – giáo viên và số tiết/tuần trước khi xếp lịch."}</div>`;
  const tableHtml = `<table class="data-table"><thead><tr>${bulkEntityHeader("assignment")}<th>Lớp</th><th>Môn</th><th>Giáo viên</th><th>Tiết/tuần</th><th>Tải giáo viên</th><th>Chế độ xếp</th><th></th></tr></thead><tbody>${rows
    .map((item) => {
      const teacher = data.teachers.find((row) => row.id === item.teacher_id);
      return `<tr>${bulkEntityCell("assignment", item.id)}<td>${esc(item.class_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(item.teacher_name)}</td><td><b>${item.periods_per_week}</b></td><td>${teacherLoadCellHtml(teacher)}</td><td>${esc(describeBlockMode(item.block_mode, item.periods_per_week))}</td><td><div class="row end"><button class="action-link" onclick="openAssignmentEdit(${item.id})">Sửa phân công</button><button class="danger-link" onclick="delEntity('assignment',${item.id},this)">Xóa</button></div></td></tr>`;
    })
    .join("")}</tbody></table>`;
  return bulkEntityTableShell("assignment", tableHtml);
}
function renderAssignmentTable() {
  const summary = $("#assignmentCompletenessSummary"),
    table = $("#assignmentTable");
  if (summary) summary.innerHTML = assignmentSummaryHtml();
  if (table) table.innerHTML = assignmentTable();
}
function renderAll() {
  if ($("#subjectTable")) {
    $("#subjectTable").innerHTML = table(
      data.subjects,
      [
        ["Tên", "name"],
        ["Tên rút gọn", "short_name"],
        ["Tiết liên tiếp tối đa", "max_consecutive"],
      ],
      "subject",
    );
    $("#departmentTable").innerHTML = table(
      data.departments,
      [["Tên tổ", "name"]],
      "department",
    );
    $("#teacherTable").innerHTML = table(
      data.teachers,
      [
        ["Họ tên", "name"],
        ["Tên ngắn", "short_name"],
        [
          "Môn dạy",
          (r) =>
            (r.subject_ids || [])
              .map((id) => data.subjects.find((x) => x.id === id)?.name)
              .filter(Boolean)
              .join(", ") || "—",
        ],
        [
          "Tổ",
          (r) =>
            data.departments.find((x) => x.id === r.department_id)?.name || "—",
        ],
        [
          "Tải tuần",
          (r) => `${r.assigned_periods || 0}/${r.week_capacity ?? "—"} tiết`,
        ],
        ["Tối đa tiết/ngày", "max_periods_day"],
      ],
      "teacher",
    );
    $("#gradeTable").innerHTML = table(
      data.grades,
      [
        ["Tên khối/nhóm", "name"],
        [
          "Chương trình",
          (r) => {
            const rows = (data.grade_requirements || []).filter(
              (item) => item.grade_id === r.id,
            );
            return rows.length
              ? `${rows.length} môn · ${rows.reduce((sum, item) => sum + Number(item.periods_per_week || 0), 0)} tiết/tuần`
              : "Chưa cấu hình";
          },
        ],
      ],
      "grade",
    );
    $("#classTable").innerHTML = table(
      data.classes,
      [
        ["Tên lớp", "name"],
        [
          "Khối",
          (r) => data.grades.find((x) => x.id === r.grade_id)?.name || "—",
        ],
      ],
      "class",
    );
    renderAssignmentFilters();
    renderAssignmentTable();
    if ($("#statLessons")) {
      $("#statTeachers").textContent = data.teachers.length;
      $("#statClasses").textContent = data.classes.length;
      $("#statAssignments").textContent = data.assignments.length;
      $("#statLessons").textContent = data.lessons.length;
    }
    renderScheduleSelectors();
    renderConstraintSelectors();
  }
}
function opts(rows, label = "name") {
  return rows
    .map((x) => `<option value="${x.id}">${esc(x[label])}</option>`)
    .join("");
}

function renderScheduleSelectors() {
  const type = $("#viewType"),
    entity = $("#viewEntity"),
    search = $("#viewSearch");
  if (!type || !entity) return;

  const updateEntity = (preserveValue = true) => {
    const previousValue = preserveValue ? entity.value : "";
    const filterType = type.value;
    let rows = [];
    if (filterType === "class") rows = data.classes || [];
    else if (filterType === "teacher") rows = data.teachers || [];
    else if (filterType === "subject") rows = data.subjects || [];

    const query = (search?.value || "").trim().toLocaleLowerCase("vi");
    if (query) {
      rows = rows.filter((item) =>
        [item.name, item.short_name]
          .filter(Boolean)
          .some((value) =>
            String(value).toLocaleLowerCase("vi").includes(query),
          ),
      );
    }

    const needsEntity = filterType !== "overview";
    entity.hidden = !needsEntity;
    entity.disabled = !needsEntity;
    const entityLabel = entity.closest("label");
    if (entityLabel) entityLabel.hidden = !needsEntity;

    entity.innerHTML = needsEntity ? opts(rows) : "";
    if (
      needsEntity &&
      previousValue &&
      [...entity.options].some((o) => o.value === previousValue)
    ) {
      entity.value = previousValue;
    }
  };

  const rerender = () => {
    renderSchedule(true);
    if ($("#unscheduledTray")) renderManualTray();
  };

  updateEntity(true);

  type.onchange = () => {
    updateEntity(false);
    rerender();
  };
  entity.onchange = rerender;

  if (search) {
    search.oninput = () => {
      updateEntity(true);
      rerender();
    };
  }

  rerender();
}
function blockModeEditor(mode = "free") {
  const selected = (value) => (value === mode ? "selected" : "");
  return `<label>Chế độ xếp tiết<select name="block_mode" onchange="updateBlockModePreview(this.form)"><option value="free" ${selected("free")}>Tự do</option><option value="preferred_double" ${selected("preferred_double")}>Ưu tiên tiết đôi</option><option value="required_double" ${selected("required_double")}>Bắt buộc tiết đôi</option></select><small class="block-mode-help">Tự do: các tiết độc lập. Ưu tiên: cố gắng ghép đôi nhưng được tách. Bắt buộc: hệ thống chia thành các cặp 2 tiết; nếu tổng số tiết lẻ thì còn 1 tiết đơn.</small></label><div class="block-mode-preview" data-block-preview></div>`;
}
function updateBlockModePreview(form) {
  if (!form) return;
  const total = Number(
    form.querySelector('[name="periods_per_week"]')?.value || 0,
  ),
    mode = form.querySelector('[name="block_mode"]')?.value || "free",
    preview = form.querySelector("[data-block-preview]");
  if (preview)
    preview.textContent =
      total > 0
        ? describeBlockMode(mode, total)
        : "Nhập số tiết/tuần để xem cách xếp.";
}
function teacherSubjectPicker(selectedIds = []) {
  const selected = new Set((selectedIds || []).map(Number));
  return `<div class="teacher-subject-picker"><div class="assignment-pick-head"><b>Môn giáo viên có thể dạy</b><div class="assignment-pick-actions"><button type="button" onclick="selectTeacherSubjects(this.form,true)">Chọn tất cả</button><button type="button" onclick="selectTeacherSubjects(this.form,false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${data.subjects.length ? data.subjects.map((item) => `<label class="assignment-pick-row"><input type="checkbox" name="subject_ids" value="${item.id}" ${selected.has(item.id) ? "checked" : ""}><span>${esc(item.name)}</span></label>`).join("") : '<div class="assignment-bulk-empty">Chưa có môn học. Hãy thêm môn trước.</div>'}</div></div><p class="teacher-subject-help">Màn phân công chỉ hiển thị các môn được chọn ở đây.</p>`;
}
function selectTeacherSubjects(form, checked) {
  if (!form) return;
  form
    .querySelectorAll('input[name="subject_ids"]')
    .forEach((input) => (input.checked = checked));
}
function gradeRequirementPicker(selectedRows = []) {
  const selected = new Map(
    (selectedRows || []).map((item) => [Number(item.subject_id), item]),
  );
  const modeOptions = (mode) =>
    `<option value="free" ${mode === "free" ? "selected" : ""}>Tự do</option><option value="preferred_double" ${mode === "preferred_double" ? "selected" : ""}>Ưu tiên tiết đôi</option><option value="required_double" ${mode === "required_double" ? "selected" : ""}>Bắt buộc tiết đôi</option>`;
  return `<div class="teacher-subject-picker"><div class="assignment-pick-head"><b>Chương trình môn chuẩn của khối</b><div class="assignment-pick-actions"><button type="button" onclick="selectGradeRequirements(this.form,true)">Chọn tất cả</button><button type="button" onclick="selectGradeRequirements(this.form,false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${data.subjects.length
    ? data.subjects
      .map((item) => {
        const row = selected.get(item.id),
          checked = !!row,
          periods = row?.periods_per_week || 1,
          mode = row?.block_mode || "free";
        return `<div class="assignment-subject-item"><label class="assignment-pick-row"><input type="checkbox" name="grade_subject_ids" value="${item.id}" ${checked ? "checked" : ""} onchange="toggleGradeRequirement(this)"><span>${esc(item.name)}</span></label><div class="assignment-subject-config" data-grade-subject-settings="${item.id}" ${checked ? "" : "hidden"}><label>Tiết/tuần<input type="number" name="grade_subject_periods_${item.id}" min="1" max="40" value="${periods}"></label><label>Chế độ xếp<select name="grade_subject_mode_${item.id}">${modeOptions(mode)}</select></label></div></div>`;
      })
      .join("")
    : '<div class="assignment-bulk-empty">Chưa có môn học. Hãy thêm môn trước.</div>'
    }</div></div><p class="teacher-subject-help">Bộ lọc thiếu phân công sẽ so trực tiếp từng lớp trong khối với danh sách này, không suy đoán từ các lớp khác.</p>`;
}
function toggleGradeRequirement(input) {
  const box = input.form?.querySelector(
    `[data-grade-subject-settings="${input.value}"]`,
  );
  if (box) box.hidden = !input.checked;
}
function selectGradeRequirements(form, checked) {
  if (!form) return;
  form.querySelectorAll('input[name="grade_subject_ids"]').forEach((input) => {
    input.checked = checked;
    toggleGradeRequirement(input);
  });
}
function openEntity(type, preset = null) {
  entityType = type;
  pendingAssignmentGap = type === "assignment" && preset ? preset : null;
  const titles = {
    subject: "Thêm môn học",
    department: "Thêm tổ chuyên môn",
    teacher: "Thêm giáo viên",
    grade: "Thêm khối / nhóm",
    class: "Thêm lớp",
    assignment: "Thêm phân công nhanh",
  };
  $("#modalTitle").textContent = titles[type];
  let h = '<label>Tên<input name="name" required></label>';
  if (type === "subject")
    h +=
      `<label>Tên rút gọn<input name="short_name" required></label><label>Số tiết liên tiếp tối đa<input type="number" name="max_consecutive" value="${Math.min(2, projectMaxConsecutive())}" min="1" max="${projectMaxConsecutive()}"></label><p class="muted">Giới hạn số tiết của môn này được phép xếp liền nhau trong cùng một buổi.</p>`;
  if (type === "teacher")
    h = `<label>Họ tên<input name="name" required></label><label>Tên ngắn<input name="short_name" required></label><label>Tổ chuyên môn<select name="department_id"><option value="">Không chọn</option>${opts(data.departments)}</select></label><label>Tối đa tiết/ngày<input type="number" name="max_periods_day" value="${Math.min(5, projectMaxPeriodsDay())}" min="1" max="${projectMaxPeriodsDay()}"></label>${teacherSubjectPicker()}`;
  if (type === "grade")
    h = `<label>Tên khối / nhóm<input name="name" required></label>${gradeRequirementPicker()}`;
  if (type === "class")
    h = `<label>Tên lớp<input name="name" required></label><label>Khối / nhóm<select name="grade_id"><option value="">Không chọn</option>${opts(data.grades)}</select></label>`;
  if (type === "assignment") {
    const eligibleTeachers = assignmentEligibleTeachers();
    h = `<div class="assignment-bulk-modal"><p class="assignment-bulk-intro">Chọn giáo viên trước, tick môn và lớp. Nếu các lớp đã có chương trình chuẩn theo khối, số tiết/tuần và chế độ xếp sẽ tự điền theo chương trình; hệ thống không lấy lại số tiết từ một lớp khác của giáo viên.</p><label>Giáo viên<select name="teacher_id" required onchange="renderBulkAssignmentChoices(this.value)" ${eligibleTeachers.length ? "" : "disabled"}><option value="">${eligibleTeachers.length ? "Chọn giáo viên" : "Chưa có giáo viên đã cấu hình môn dạy"}</option>${opts(eligibleTeachers)}</select></label>${eligibleTeachers.length ? "" : '<div class="assignment-bulk-empty assignment-bulk-empty-warning">Tài khoản giáo viên mới đăng ký không tự trở thành giáo viên trong phân công. Hãy tạo/cấu hình hồ sơ ở tab <b>Giáo viên</b> và chọn ít nhất một môn có thể dạy.</div>'}<div id="bulkAssignmentChoices"><div class="assignment-bulk-empty">${eligibleTeachers.length ? "Chọn giáo viên để hiện danh sách môn và lớp." : "Chưa thể tạo phân công."}</div></div></div>`;
  }
  $("#entityFields").innerHTML = h;
  if (type === "assignment") {
    entityModal
      .querySelector(".modal-form")
      ?.classList.add("assignment-bulk-form");
  } else {
    entityModal
      .querySelector(".modal-form")
      ?.classList.remove("assignment-bulk-form");
  }
  entityModal.showModal();
}
function editOpts(rows, selected, label = "name") {
  return rows
    .map(
      (x) =>
        `<option value="${x.id}" ${x.id === selected ? "selected" : ""}>${esc(x[label])}</option>`,
    )
    .join("");
}
function bulkRequirementForSelection(subjectId, classIds) {
  if (!classIds.length) return { status: "none" };
  const rows = [];
  for (const classId of classIds) {
    const schoolClass = data.classes.find((item) => item.id === classId);
    if (!schoolClass || schoolClass.grade_id == null)
      return { status: "missing" };
    const requirement = (data.grade_requirements || []).find(
      (item) =>
        item.grade_id === schoolClass.grade_id && item.subject_id === subjectId,
    );
    if (!requirement) return { status: "missing" };
    rows.push(requirement);
  }
  const first = rows[0],
    same = rows.every(
      (item) =>
        Number(item.periods_per_week) === Number(first.periods_per_week) &&
        String(item.block_mode || "free") ===
        String(first.block_mode || "free"),
    );
  return same
    ? {
      status: "exact",
      periods: Number(first.periods_per_week),
      mode: first.block_mode || "free",
    }
    : { status: "mixed" };
}
function syncBulkCurriculumDefaults(form, force = false) {
  if (!form) return;
  const classIds = [
    ...form.querySelectorAll('input[name="class_ids"]:checked'),
  ].map((input) => Number(input.value));
  form.querySelectorAll('input[name="subject_ids"]').forEach((subjectInput) => {
    const subjectId = Number(subjectInput.value),
      periodInput = form.querySelector(`[name="subject_periods_${subjectId}"]`),
      modeInput = form.querySelector(`[name="subject_mode_${subjectId}"]`),
      status = form.querySelector(`[data-subject-curriculum="${subjectId}"]`);
    if (!periodInput || !modeInput) return;
    const auto = force || periodInput.dataset.auto !== "0";
    const requirement = bulkRequirementForSelection(subjectId, classIds);
    if (requirement.status === "exact") {
      if (auto) {
        periodInput.value = requirement.periods;
        modeInput.value = requirement.mode;
        periodInput.dataset.auto = "1";
        modeInput.dataset.auto = "1";
      }
      if (status)
        status.textContent = `Theo chương trình lớp đã chọn: ${requirement.periods} tiết/tuần.`;
    } else if (requirement.status === "mixed") {
      if (auto) {
        periodInput.value = "";
        modeInput.value = "free";
      }
      if (status)
        status.textContent =
          "Các lớp đã chọn có chương trình khác nhau cho môn này. Hãy chia lần phân công theo từng khối/chương trình.";
    } else if (requirement.status === "missing") {
      if (auto) {
        periodInput.value = "";
        modeInput.value = "free";
      }
      if (status)
        status.textContent =
          "Có lớp chưa cấu hình chương trình cho môn này; hãy nhập thủ công hoặc cấu hình ở mục Khối / nhóm lớp.";
    } else {
      if (auto) {
        periodInput.value = "";
        modeInput.value = "free";
      }
      if (status)
        status.textContent = "Chọn lớp để tự điền theo chương trình khối.";
    }
    updateBulkSubjectPreview(subjectId, form);
  });
}
function markBulkSubjectManual(subjectId, form) {
  const periodInput = form?.querySelector(
    `[name="subject_periods_${subjectId}"]`,
  ),
    modeInput = form?.querySelector(`[name="subject_mode_${subjectId}"]`);
  if (periodInput) periodInput.dataset.auto = "0";
  if (modeInput) modeInput.dataset.auto = "0";
  updateBulkSubjectPreview(subjectId, form);
  updateBulkAssignmentPreview(form);
}
function renderBulkAssignmentChoices(value) {
  const teacherId = Number(value),
    box = $("#bulkAssignmentChoices");
  if (!box) return;
  if (!teacherId) {
    box.innerHTML =
      '<div class="assignment-bulk-empty">Chọn giáo viên để hiện danh sách môn và lớp.</div>';
    return;
  }
  const teacher = data.teachers.find((item) => item.id === teacherId),
    allowed = new Set((teacher?.subject_ids || []).map(Number)),
    subjects = data.subjects
      .filter((item) => allowed.has(item.id))
      .sort((a, b) => a.name.localeCompare(b.name, "vi")),
    classes = [...data.classes].sort((a, b) =>
      a.name.localeCompare(b.name, "vi"),
    );
  if (!subjects.length) {
    box.innerHTML =
      '<div class="assignment-bulk-empty">Giáo viên này chưa được cấu hình môn có thể dạy. Hãy vào mục Giáo viên → Sửa và tick môn trước.</div>';
    return;
  }
  const modeOptions = `<option value="free">Tự do</option><option value="preferred_double">Ưu tiên tiết đôi</option><option value="required_double">Bắt buộc tiết đôi</option>`;
  const subjectRows = subjects
    .map(
      (item) =>
        `<div class="assignment-subject-item"><label class="assignment-pick-row"><input type="checkbox" name="subject_ids" value="${item.id}" onchange="toggleBulkSubjectSettings(this);syncBulkCurriculumDefaults(this.form);updateBulkAssignmentPreview(this.form)"><span>${esc(item.name)}</span></label><div class="assignment-subject-config" data-subject-settings="${item.id}" hidden><label>Tiết/tuần<input type="number" name="subject_periods_${item.id}" min="1" max="40" value="" placeholder="Theo khối" data-auto="1" oninput="markBulkSubjectManual(${item.id},this.form)" onchange="markBulkSubjectManual(${item.id},this.form)"></label><label>Chế độ xếp<select name="subject_mode_${item.id}" data-auto="1" onchange="markBulkSubjectManual(${item.id},this.form)">${modeOptions}</select></label><div class="block-mode-preview" data-subject-preview="${item.id}"></div><small class="teacher-subject-help" data-subject-curriculum="${item.id}">Chọn lớp để tự điền theo chương trình khối.</small></div></div>`,
    )
    .join("");
  const classRows = classes.length
    ? classes
      .map((item) => {
        const grade = data.grades.find((g) => g.id === item.grade_id);
        return `<label class="assignment-pick-row"><input type="checkbox" name="class_ids" value="${item.id}" onchange="syncBulkCurriculumDefaults(this.form);updateBulkAssignmentPreview(this.form)"><span>${esc(item.name)}${grade ? ` <small>${esc(grade.name)}</small>` : ""}</span></label>`;
      })
      .join("")
    : '<div class="assignment-bulk-empty">Chưa có lớp học.</div>';
  box.innerHTML = `<div id="bulkTeacherLoad"></div><div class="assignment-bulk-grid"><div class="assignment-pick-panel"><div class="assignment-pick-head"><b>Môn học của giáo viên</b><div class="assignment-pick-actions"><button type="button" onclick="selectBulkAssignmentGroup('subject_ids',true)">Chọn tất cả</button><button type="button" onclick="selectBulkAssignmentGroup('subject_ids',false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${subjectRows}</div></div><div class="assignment-pick-panel"><div class="assignment-pick-head"><b>Lớp học</b><div class="assignment-pick-actions"><button type="button" onclick="selectBulkAssignmentGroup('class_ids',true)">Chọn tất cả</button><button type="button" onclick="selectBulkAssignmentGroup('class_ids',false)">Bỏ chọn</button></div></div><div class="assignment-pick-list">${classRows}</div></div></div><div id="bulkAssignmentPreview" class="assignment-bulk-preview"></div>`;
  const form = entityModal.querySelector("form");
  if (pendingAssignmentGap) {
    const subjectInput = form.querySelector(
      `input[name="subject_ids"][value="${pendingAssignmentGap.subjectId}"]`,
    ),
      classInput = form.querySelector(
        `input[name="class_ids"][value="${pendingAssignmentGap.classId}"]`,
      );
    if (subjectInput) {
      subjectInput.checked = true;
      toggleBulkSubjectSettings(subjectInput);
    }
    if (classInput) classInput.checked = true;
    if (!subjectInput) {
      box.insertAdjacentHTML(
        "afterbegin",
        '<div class="assignment-warning" style="padding:10px 12px">Giáo viên này chưa được cấu hình dạy môn đang thiếu. Hãy chọn giáo viên khác hoặc cập nhật môn dạy của giáo viên.</div>',
      );
    }
  }
  syncBulkCurriculumDefaults(form, true);
  updateBulkAssignmentPreview(form);
}
function toggleBulkSubjectSettings(input) {
  const box = input.form?.querySelector(
    `[data-subject-settings="${input.value}"]`,
  );
  if (box) box.hidden = !input.checked;
  if (input.checked) {
    syncBulkCurriculumDefaults(input.form);
    updateBulkSubjectPreview(Number(input.value), input.form);
  }
}
function updateBulkSubjectPreview(subjectId, form) {
  if (!form) return;
  const total = Number(
    form.querySelector(`[name="subject_periods_${subjectId}"]`)?.value || 0,
  ),
    mode =
      form.querySelector(`[name="subject_mode_${subjectId}"]`)?.value || "free",
    preview = form.querySelector(`[data-subject-preview="${subjectId}"]`);
  if (preview)
    preview.textContent =
      total > 0 ? describeBlockMode(mode, total) : "Chưa có số tiết/tuần.";
}
function selectBulkAssignmentGroup(name, checked) {
  const form = entityModal.querySelector("form");
  if (!form) return;
  form.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
    input.checked = checked;
    if (name === "subject_ids") toggleBulkSubjectSettings(input);
  });
  syncBulkCurriculumDefaults(form);
  updateBulkAssignmentPreview(form);
}
function updateBulkAssignmentPreview(form) {
  const preview = $("#bulkAssignmentPreview");
  if (!preview || !form) return;
  const teacherId = Number(
    form.querySelector('[name="teacher_id"]')?.value || 0,
  ),
    teacher = data.teachers.find((item) => item.id === teacherId),
    subjectIds = [
      ...form.querySelectorAll('input[name="subject_ids"]:checked'),
    ].map((input) => Number(input.value)),
    classIds = [
      ...form.querySelectorAll('input[name="class_ids"]:checked'),
    ].map((input) => Number(input.value)),
    total = subjectIds.length * classIds.length;
  const subjectSet = new Set(subjectIds),
    classSet = new Set(classIds),
    existing = data.assignments.filter(
      (item) => subjectSet.has(item.subject_id) && classSet.has(item.class_id),
    );
  let addedPeriods = 0;
  for (const subjectId of subjectIds) {
    const periods = Number(
      form.querySelector(`[name="subject_periods_${subjectId}"]`)?.value || 0,
    );
    for (const classId of classIds) {
      if (
        !existing.some(
          (item) => item.subject_id === subjectId && item.class_id === classId,
        )
      )
        addedPeriods += periods;
    }
  }
  const current = Number(teacher?.assigned_periods || 0),
    projected = current + addedPeriods,
    loadBox = $("#bulkTeacherLoad");
  if (loadBox) loadBox.innerHTML = teacherLoadCardHtml(teacher, projected);
  if (!total) {
    preview.innerHTML =
      "Hãy tick ít nhất 1 môn và 1 lớp. Tải giáo viên phía trên sẽ cập nhật ngay khi bạn chọn.";
    return;
  }
  const mixedSubjects = subjectIds.filter(
    (subjectId) =>
      bulkRequirementForSelection(subjectId, classIds).status === "mixed",
  );
  if (mixedSubjects.length) {
    preview.innerHTML = `<span class="assignment-warning">Có ${mixedSubjects.length} môn có số tiết/chế độ khác nhau giữa các lớp đã chọn. Hãy chia lần phân công theo từng khối/chương trình để tránh gán sai.</span>`;
    return;
  }
  const duplicates = existing.filter(
    (item) => item.teacher_id === teacherId,
  ).length,
    conflicts = existing.filter((item) => item.teacher_id !== teacherId).length,
    staleDuplicates = existing.filter((item) => {
      if (item.teacher_id !== teacherId) return false;
      const periods = Number(
        form.querySelector(`[name="subject_periods_${item.subject_id}"]`)?.value ||
        0,
      );
      const mode =
        form.querySelector(`[name="subject_mode_${item.subject_id}"]`)?.value ||
        "free";
      return (
        Number(item.periods_per_week) !== periods ||
        String(item.block_mode || "free") !== String(mode)
      );
    }).length,
    fresh = Math.max(0, total - duplicates - conflicts),
    capacity = teacher?.week_capacity;
  let status = "";
  if (conflicts)
    status = `<span class="assignment-warning">Có ${conflicts} cặp lớp–môn đã thuộc giáo viên khác; hệ thống sẽ không cho lưu cho đến khi xử lý các phân công đó.</span>`;
  else if (staleDuplicates)
    status = `<span class="assignment-warning">Có ${staleDuplicates} cặp đã tồn tại nhưng số tiết/chế độ khác cấu hình đang chọn. Hệ thống sẽ không bỏ qua âm thầm; hãy sửa phân công hiện có hoặc bỏ các cặp đó khỏi lần phân công này.</span>`;
  else if (capacity != null && projected > Number(capacity))
    status = `<span class="assignment-warning">Tải dự kiến ${projected}/${capacity} tiết/tuần vượt khả năng xếp của giáo viên.</span>`;
  else
    status =
      capacity == null
        ? ""
        : `<span class="assignment-ok">Tải giáo viên: ${projected}/${capacity} tiết/tuần.</span>`;
  preview.innerHTML = `Đã chọn <b>${subjectIds.length}</b> môn × <b>${classIds.length}</b> lớp = <b>${total}</b> cặp. ${duplicates ? `Có ${duplicates} cặp đã tồn tại; ` : ""}dự kiến tạo mới <b>${fresh}</b> phân công, thêm <b>${addedPeriods}</b> tiết/tuần.${status}`;
}
function openEntityEdit(type, id) {
  const rows =
    {
      subject: data.subjects,
      teacher: data.teachers,
      grade: data.grades,
      class: data.classes,
    }[type] || [];
  const item = rows.find((x) => x.id === Number(id));
  if (!item) return;
  entityType = `${type}_edit`;
  entityId = item.id;
  entityModal
    .querySelector(".modal-form")
    ?.classList.remove("assignment-bulk-form");
  const titles = {
    subject: "Sửa môn học",
    teacher: "Sửa giáo viên",
    grade: "Sửa khối / nhóm",
    class: "Sửa lớp học",
  };
  $("#modalTitle").textContent = titles[type];
  let h = "";
  if (type === "subject")
    h = `<label>Tên môn học<input name="name" value="${esc(item.name)}" required></label><label>Tên rút gọn<input name="short_name" value="${esc(item.short_name)}" required></label><label>Số tiết liên tiếp tối đa<input type="number" name="max_consecutive" value="${Math.min(Number(item.max_consecutive) || 1, projectMaxConsecutive())}" min="1" max="${projectMaxConsecutive()}" required></label><p class="muted">Giới hạn số tiết của môn này được phép xếp liền nhau trong cùng một buổi.</p>`;
  if (type === "teacher")
    h = `<label>Họ tên<input name="name" value="${esc(item.name)}" required></label><label>Tên ngắn<input name="short_name" value="${esc(item.short_name)}" required></label><label>Tổ chuyên môn<select name="department_id"><option value="">Không chọn</option>${editOpts(data.departments, item.department_id)}</select></label><label>Tối đa tiết/ngày<input type="number" name="max_periods_day" value="${Math.min(Number(item.max_periods_day) || 1, projectMaxPeriodsDay())}" min="1" max="${projectMaxPeriodsDay()}" required></label>${teacherSubjectPicker(item.subject_ids || [])}`;
  if (type === "grade")
    h = `<label>Tên khối / nhóm<input name="name" value="${esc(item.name)}" required></label>${gradeRequirementPicker((data.grade_requirements || []).filter((row) => row.grade_id === item.id))}`;
  if (type === "class")
    h = `<label>Tên lớp<input name="name" value="${esc(item.name)}" required></label><label>Khối / nhóm<select name="grade_id"><option value="">Không chọn</option>${editOpts(data.grades, item.grade_id)}</select></label>`;
  $("#entityFields").innerHTML = h;
  entityModal.showModal();
}
function openAssignmentEdit(id) {
  const item = data.assignments.find((x) => x.id === id);
  if (!item) return;
  entityType = "assignment_edit";
  entityModal
    .querySelector(".modal-form")
    ?.classList.remove("assignment-bulk-form");
  $("#modalTitle").textContent = "Sửa phân công";
  $("#entityFields").innerHTML =
    `<div class="assignment-summary"><b>${esc(item.class_name)} · ${esc(item.subject_name)}</b><span>${esc(item.teacher_name)}</span></div><input type="hidden" name="assignment_id" value="${item.id}"><label>Số tiết/tuần<input type="number" name="periods_per_week" min="1" max="40" value="${item.periods_per_week}" required oninput="updateAssignmentEditPreview(this.form)" onchange="updateAssignmentEditPreview(this.form)"></label><div data-assignment-edit-load></div>${blockModeEditor(item.block_mode)}`;
  updateAssignmentEditPreview(entityModal.querySelector("form"));
  entityModal.showModal();
}
async function submitEntity(e) {
  e.preventDefault();
  const form = e.target,
    formData = new FormData(form),
    o = Object.fromEntries(formData),
    submitButton = e.submitter || $("#entitySubmitButton");
  setEntityActionMessage("");
  setInlineActionState(submitButton, "loading", {
    idle: "Lưu",
    loading: "Đang lưu...",
  });
  for (const k of [
    "department_id",
    "grade_id",
    "class_id",
    "subject_id",
    "teacher_id",
    "assignment_id",
    "max_periods_day",
    "max_consecutive",
    "periods_per_week",
  ])
    if (o[k]) o[k] = Number(o[k]);
  if (entityType === "teacher" || entityType === "teacher_edit")
    o.subject_ids = formData.getAll("subject_ids").map(Number).filter(Boolean);
  if (entityType === "grade" || entityType === "grade_edit") {
    o.subject_requirements = formData
      .getAll("grade_subject_ids")
      .map(Number)
      .filter(Boolean)
      .map((subject_id) => ({
        subject_id,
        periods_per_week: Number(
          form.querySelector(`[name="grade_subject_periods_${subject_id}"]`)
            ?.value || 0,
        ),
        block_mode:
          form.querySelector(`[name="grade_subject_mode_${subject_id}"]`)
            ?.value || "free",
      }));
    if (
      o.subject_requirements.some(
        (item) =>
          !Number.isInteger(item.periods_per_week) || item.periods_per_week < 1,
      )
    ) {
      entityActionError(
        submitButton,
        "Số tiết/tuần trong chương trình khối phải từ 1 trở lên.",
      );
      return;
    }
  }
  try {
    if (entityType === "assignment") {
      const subject_ids = formData
        .getAll("subject_ids")
        .map(Number)
        .filter(Boolean),
        class_ids = formData.getAll("class_ids").map(Number).filter(Boolean);
      if (!o.teacher_id) {
        entityActionError(submitButton, "Hãy chọn giáo viên.");
        return;
      }
      if (!subject_ids.length) {
        entityActionError(submitButton, "Hãy chọn ít nhất một môn học.");
        return;
      }
      if (!class_ids.length) {
        entityActionError(submitButton, "Hãy chọn ít nhất một lớp.");
        return;
      }
      const mixedSubject = subject_ids.find(
        (subject_id) =>
          bulkRequirementForSelection(subject_id, class_ids).status === "mixed",
      );
      if (mixedSubject) {
        const subject = data.subjects.find((item) => item.id === mixedSubject);
        entityActionError(
          submitButton,
          `${subject?.name || "Môn đã chọn"} có chương trình khác nhau giữa các lớp. Hãy chia lần phân công theo từng khối.`,
        );
        return;
      }
      const subjects = subject_ids.map((subject_id) => ({
        subject_id,
        periods_per_week: Number(
          form.querySelector(`[name="subject_periods_${subject_id}"]`)?.value ||
          0,
        ),
        block_mode:
          form.querySelector(`[name="subject_mode_${subject_id}"]`)?.value ||
          "free",
      }));
      if (
        subjects.some(
          (item) =>
            !Number.isInteger(item.periods_per_week) ||
            item.periods_per_week < 1,
        )
      ) {
        entityActionError(
          submitButton,
          "Số tiết/tuần của mỗi môn phải từ 1 trở lên.",
        );
        return;
      }
      const r = await fetch(`/api/projects/${PROJECT_ID}/assignments/bulk`, {
        method: "POST",
        headers: operationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ teacher_id: o.teacher_id, class_ids, subjects }),
      });
      const result = await readApiResponse(r);
      if (!r.ok) {
        entityActionError(
          submitButton,
          apiErrorMessage(result, "Không thể thêm phân công."),
        );
        return;
      }
      setInlineActionState(submitButton, "success", {
        idle: "Lưu",
        success: "Đã lưu",
      });
      setEntityActionMessage(
        result.message || `Đã tạo ${result.created || 0} phân công.`,
        "success",
      );
      await wait(650);
      entityModal.close();
      await refreshAfterSuccessfulMutation();
      return;
    }
    if (entityType === "assignment_edit") {
      const r = await fetch(
        `/api/projects/${PROJECT_ID}/assignments/${o.assignment_id}`,
        {
          method: "PUT",
          headers: operationHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            periods_per_week: o.periods_per_week,
            block_mode: o.block_mode,
          }),
        },
      );
      const result = await readApiResponse(r);
      if (!r.ok) {
        entityActionError(
          submitButton,
          apiErrorMessage(result, "Không thể cập nhật phân công."),
        );
        return;
      }
      setInlineActionState(submitButton, "success", {
        idle: "Lưu",
        success: "Đã cập nhật",
      });
      setEntityActionMessage("Đã cập nhật phân công.", "success");
      await wait(650);
      entityModal.close();
      await refreshAfterSuccessfulMutation();
      return;
    }
    if (entityType.endsWith("_edit")) {
      const type = entityType.replace("_edit", "");
      const r = await fetch(
        `/api/projects/${PROJECT_ID}/entity/${type}/${entityId}`,
        {
          method: "PUT",
          headers: operationHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ type, data: o }),
        },
      );
      const result = await readApiResponse(r);
      if (!r.ok) {
        entityActionError(
          submitButton,
          apiErrorMessage(result, "Không thể cập nhật dữ liệu."),
        );
        return;
      }
      setInlineActionState(submitButton, "success", {
        idle: "Lưu",
        success: "Đã cập nhật",
      });
      const syncedAssignments = Number(result.synced_assignments || 0);
      setEntityActionMessage(
        syncedAssignments > 0
          ? `Đã cập nhật dữ liệu và đồng bộ ${syncedAssignments} phân công theo chương trình khối.`
          : "Đã cập nhật dữ liệu.",
        "success",
      );
      await wait(650);
      entityModal.close();
      await refreshAfterSuccessfulMutation();
      return;
    }
    const r = await fetch(`/api/projects/${PROJECT_ID}/entity`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ type: entityType, data: o }),
    });
    const result = await readApiResponse(r);
    if (!r.ok) {
      entityActionError(
        submitButton,
        apiErrorMessage(result, "Không thể lưu dữ liệu."),
      );
      return;
    }
    setInlineActionState(submitButton, "success", {
      idle: "Lưu",
      success: "Đã lưu",
    });
    setEntityActionMessage("Đã lưu dữ liệu.", "success");
    await wait(650);
    entityModal.close();
    await refreshAfterSuccessfulMutation();
  } catch (error) {
    entityActionError(
      submitButton,
      requestFailureMessage(error, "Mất kết nối tới máy chủ. Vui lòng thử lại."),
    );
  }
}
async function delEntity(type, id, button) {
  if (!(await confirmAction("Xóa mục này?", { confirmText: "Xóa" }))) return;
  setInlineActionState(button, "loading", {
    idle: "Xóa",
    loading: "Đang xóa...",
  });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/entity/${type}/${id}`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const result = await readApiResponse(r);
    if (r.ok) {
      setInlineActionState(button, "success", {
        idle: "Xóa",
        success: "Đã xóa",
      });
      await wait(450);
      await refreshAfterSuccessfulMutation();
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: "Xóa", error: "Không thể xóa" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể xóa dữ liệu. Vui lòng thử lại."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Xóa", error: "Chưa hoàn tất" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
function exportFilenameFromResponse(response) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch { }
  }
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1]?.trim() || "thoi-khoa-bieu.xlsx";
}
async function handleExportExcel(event, link) {
  if (!link) return;
  event?.preventDefault?.();
  if (link.dataset.exportBusy === "1") return;

  const originalHtml = link.innerHTML;
  link.dataset.exportBusy = "1";
  link.innerHTML = '<span class="btn-spinner"></span> Đang tạo tệp...';
  link.style.pointerEvents = "none";
  link.setAttribute("aria-busy", "true");

  try {
    const response = await fetch(link.href, {
      method: "GET",
      headers: operationHeaders(),
    });
    if (!response.ok) {
      const result = await readApiResponse(response);
      throw new Error(
        apiErrorMessage(result, `Không thể xuất Excel (HTTP ${response.status}).`),
      );
    }

    const blob = await response.blob();
    if (!blob.size) throw new Error("Máy chủ trả về tệp Excel rỗng.");

    const downloadUrl = URL.createObjectURL(blob);
    const downloadLink = document.createElement("a");
    downloadLink.href = downloadUrl;
    downloadLink.download = exportFilenameFromResponse(response);
    downloadLink.style.display = "none";
    document.body.appendChild(downloadLink);
    downloadLink.click();
    downloadLink.remove();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);

    showToast("Đã tạo file Excel và bắt đầu tải xuống.", "success", 3200);
  } catch (error) {
    showToast(
      error?.message || "Không thể xuất Excel. Vui lòng thử lại.",
      "error",
      5000,
    );
  } finally {
    link.innerHTML = originalHtml;
    link.style.pointerEvents = "";
    link.removeAttribute("aria-busy");
    delete link.dataset.exportBusy;
  }
}
window.handleExportExcel = handleExportExcel;

function computeScheduleConflicts() {
  const conflictsByLessonId = new Map();
  if (!data?.lessons || !data?.assignments || !data?.project)
    return { conflictsByLessonId };

  const addLessonConflict = (lessonId, reason) => {
    if (!conflictsByLessonId.has(lessonId)) conflictsByLessonId.set(lessonId, []);
    const reasons = conflictsByLessonId.get(lessonId);
    if (!reasons.includes(reason)) reasons.push(reason);
  };
  const markLessons = (lessons, reason) => {
    for (const lesson of lessons) addLessonConflict(lesson.id, reason);
  };

  const assignmentById = new Map(data.assignments.map((row) => [row.id, row]));
  const teacherById = new Map((data.teachers || []).map((row) => [row.id, row]));
  const classById = new Map((data.classes || []).map((row) => [row.id, row]));
  const subjectById = new Map((data.subjects || []).map((row) => [row.id, row]));
  const blockedSlots = new Set(data.project.blocked_slots || []);
  const pps = Number(data.project.periods || 0);
  const sessions = Number(data.project.sessions || 0);
  const days = Number(data.project.days || 0);
  const ppd = pps * sessions;
  const totalSlots = days * ppd;

  const teacherUnavailable = new Map(
    (data.teachers || []).map((row) => [row.id, new Set(row.unavailable || [])]),
  );
  const classUnavailable = new Map(
    (data.classes || []).map((row) => [row.id, new Set(row.unavailable || [])]),
  );
  const slotMap = new Map();
  const teacherDayMap = new Map();
  const classSubjectSessionMap = new Map();
  const assignmentLessons = new Map();

  for (const lesson of data.lessons) {
    const slot = Number(lesson.slot);
    const assignment = assignmentById.get(lesson.assignment_id);
    if (!assignment) {
      markLessons([lesson], "Tiết học tham chiếu phân công không còn tồn tại");
      continue;
    }

    if (!assignmentLessons.has(assignment.id)) assignmentLessons.set(assignment.id, []);
    assignmentLessons.get(assignment.id).push(lesson);

    if (!Number.isInteger(slot) || slot < 0 || slot >= totalSlots || ppd <= 0 || pps <= 0) {
      markLessons([lesson], "Ô thời khóa biểu không hợp lệ");
      continue;
    }

    if (!slotMap.has(slot)) slotMap.set(slot, []);
    slotMap.get(slot).push({ lesson, assignment });

    const teacher = teacherById.get(assignment.teacher_id);
    const schoolClass = classById.get(assignment.class_id);
    const subject = subjectById.get(assignment.subject_id);
    if (!teacher || !schoolClass || !subject) {
      markLessons([lesson], "Phân công không còn đầy đủ lớp, môn hoặc giáo viên");
      continue;
    }

    if (blockedSlots.has(slot))
      markLessons([lesson], "Tiết này đã bị khóa toàn trường");
    if (teacherUnavailable.get(teacher.id)?.has(slot))
      markLessons(
        [lesson],
        `Giáo viên ${teacher.name || assignment.teacher_name || ""} không thể dạy ở tiết này`,
      );
    if (classUnavailable.get(schoolClass.id)?.has(slot))
      markLessons(
        [lesson],
        `Lớp ${schoolClass.name || assignment.class_name || ""} không học ở tiết này`,
      );

    const day = Math.floor(slot / ppd);
    const insideDay = slot % ppd;
    const session = Math.floor(insideDay / pps);
    const teacherDayKey = `${assignment.teacher_id}:${day}`;
    if (!teacherDayMap.has(teacherDayKey)) teacherDayMap.set(teacherDayKey, []);
    teacherDayMap.get(teacherDayKey).push({ lesson, assignment, teacher });

    const runKey = `${assignment.class_id}:${assignment.subject_id}:${day}:${session}`;
    if (!classSubjectSessionMap.has(runKey)) classSubjectSessionMap.set(runKey, []);
    classSubjectSessionMap.get(runKey).push({ lesson, assignment, subject });
  }

  for (const rows of slotMap.values()) {
    const teacherMap = new Map();
    const classMap = new Map();
    for (const row of rows) {
      if (!teacherMap.has(row.assignment.teacher_id)) teacherMap.set(row.assignment.teacher_id, []);
      teacherMap.get(row.assignment.teacher_id).push(row);
      if (!classMap.has(row.assignment.class_id)) classMap.set(row.assignment.class_id, []);
      classMap.get(row.assignment.class_id).push(row);
    }
    for (const list of teacherMap.values()) {
      if (list.length <= 1) continue;
      const name = list[0].assignment.teacher_name || list[0].assignment.teacher_short || "Giáo viên";
      markLessons(
        list.map((row) => row.lesson),
        `Trùng lịch GV: ${name} đang dạy nhiều lớp trong cùng một tiết`,
      );
    }
    for (const list of classMap.values()) {
      if (list.length <= 1) continue;
      const name = list[0].assignment.class_name || "Lớp";
      markLessons(
        list.map((row) => row.lesson),
        `Trùng lịch lớp: ${name} có nhiều môn trong cùng một tiết`,
      );
    }
  }

  for (const rows of teacherDayMap.values()) {
    const limit = Number(rows[0]?.teacher?.max_periods_day || 0);
    if (limit > 0 && rows.length > limit) {
      const name = rows[0].teacher?.name || rows[0].assignment.teacher_name || "Giáo viên";
      markLessons(
        rows.map((row) => row.lesson),
        `${name} có ${rows.length} tiết trong ngày, vượt giới hạn ${limit} tiết/ngày`,
      );
    }
  }

  for (const rows of classSubjectSessionMap.values()) {
    const limit = Number(rows[0]?.subject?.max_consecutive || 0);
    if (limit <= 0) continue;
    const ordered = [...rows].sort((a, b) => a.lesson.slot - b.lesson.slot);
    let run = [];
    const inspectRun = () => {
      if (run.length > limit) {
        const label = rows[0].subject?.name || rows[0].assignment.subject_name || "Môn học";
        markLessons(
          run.map((row) => row.lesson),
          `${label} có ${run.length} tiết liên tiếp, vượt giới hạn ${limit}`,
        );
      }
      run = [];
    };
    for (const row of ordered) {
      if (run.length && row.lesson.slot !== run[run.length - 1].lesson.slot + 1) inspectRun();
      run.push(row);
    }
    inspectRun();
  }

  for (const assignment of data.assignments) {
    if (assignment.block_mode !== "required_double") continue;
    const lessons = [...(assignmentLessons.get(assignment.id) || [])].sort(
      (a, b) => a.slot - b.slot,
    );
    if (!lessons.length) continue;
    const expected = Number(assignment.periods_per_week || 0);
    if (lessons.length > expected) {
      markLessons(
        lessons,
        `Phân công bắt buộc tiết đôi đang có ${lessons.length}/${expected} tiết`,
      );
      continue;
    }

    const groups = new Map();
    for (const lesson of lessons) {
      const day = Math.floor(lesson.slot / ppd);
      const session = Math.floor((lesson.slot % ppd) / pps);
      const key = `${day}:${session}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(lesson);
    }
    const runs = [];
    for (const group of groups.values()) {
      group.sort((a, b) => a.slot - b.slot);
      let run = [];
      for (const lesson of group) {
        if (run.length && lesson.slot !== run[run.length - 1].slot + 1) {
          runs.push(run);
          run = [];
        }
        run.push(lesson);
      }
      if (run.length) runs.push(run);
    }
    if (lessons.length === expected) {
      const actualSizes = runs
        .flatMap((run) => [
          ...Array(Math.floor(run.length / 2)).fill(2),
          ...(run.length % 2 ? [1] : []),
        ])
        .sort((a, b) => a - b);
      const expectedSizes = [
        ...Array(Math.floor(expected / 2)).fill(2),
        ...(expected % 2 ? [1] : []),
      ].sort((a, b) => a - b);
      const valid =
        actualSizes.length === expectedSizes.length &&
        actualSizes.every((size, index) => size === expectedSizes[index]);
      if (!valid)
        markLessons(
          lessons,
          `Phân công ${assignment.class_name || ""} – ${assignment.subject_name || ""} chưa đúng mẫu bắt buộc tiết đôi`,
        );
    }
  }

  return { conflictsByLessonId };
}

async function generateSchedule(allowRebuild = false) {
  const modal = $("#aiProgressModal");
  const bar = $("#aiProgressBar");
  const subtitle = $("#aiProgressSubtitle");

  function setProgress(state, statusText) {
    if (bar) {
      const running = state === "running";
      bar.classList.toggle("is-indeterminate", running);
      if (running) {
        bar.style.width = "34%";
        bar.removeAttribute("aria-valuenow");
      } else {
        bar.style.width = state === "complete" ? "100%" : "0%";
        if (state === "complete") bar.setAttribute("aria-valuenow", "100");
        else bar.removeAttribute("aria-valuenow");
      }
    }
    if (subtitle && statusText) subtitle.textContent = statusText;
  }

  setScheduleActionState("loading");
  setScheduleFeedback("", "info", 0);

  if (modal && typeof modal.showModal === "function") {
    modal.showModal();
    setProgress(
      "running",
      "Đang kiểm tra ràng buộc và chạy solver. Thời gian xử lý phụ thuộc độ phức tạp của lịch...",
    );
  }

  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/generate`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ allow_rebuild: allowRebuild }),
    });
    const j = await readApiResponse(r);

    if (r.ok) {
      setProgress("complete", "Đã xếp xong. Đang đồng bộ thời khóa biểu...");
      setTimeout(async () => {
        if (modal) modal.close();
        const refreshed = await refreshAfterSuccessfulMutation(
          ["lessons"],
          "Máy chủ đã xếp lịch thành công nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ thời khóa biểu.",
        );
        setScheduleActionState("success", refreshed ? 1400 : 2600);
        setScheduleFeedback(
          refreshed
            ? j.message || "Đã xếp thời khóa biểu thành công."
            : "Đã xếp thời khóa biểu trên máy chủ. Hãy tải lại trang để xem dữ liệu mới.",
          refreshed ? "success" : "warning",
          refreshed ? 2600 : 6500,
        );
        if (refreshed) {
          launchConfetti();
        }
      }, 400);
    } else if (j.requires_confirmation && !allowRebuild) {
      if (modal) modal.close();
      setScheduleActionState("idle");
      if (
        await confirmAction(
          `${apiErrorMessage(j, "Lịch hiện tại cần được xếp lại.")}\n\nBạn có đồng ý xếp lại phần không cố định không?`,
          {
            title: "Xếp lại thời khóa biểu",
            confirmText: "Xếp lại",
          },
        )
      ) {
        return generateSchedule(true);
      }
    } else {
      if (modal) modal.close();
      setScheduleActionState("error", 1800);
      setScheduleFeedback(
        apiErrorMessage(j, "Xếp thời khóa biểu thất bại; lịch hiện tại được giữ nguyên."),
        "error",
        5200,
      );

    }
  } catch (error) {
    if (modal) modal.close();
    setScheduleActionState("error", 1800);
    const message = requestFailureMessage(
      error,
      "Mất kết nối tới máy chủ. Không thể xếp thời khóa biểu.",
    );
    setScheduleFeedback(message, "error", 5200);
  }
}
function goToAssignments() {
  document.querySelector('.nav[data-tab="assignments"]')?.click();
}
function renderManualTray() {
  const tray = $("#unscheduledTray"),
    scheduledBox = $("#scheduledAssignmentTray"),
    coverageBox = $("#assignmentCoverage"),
    vt = $("#viewType"),
    ve = $("#viewEntity");
  if (!tray) return;
  const coverage = data.coverage || {};
  const duplicates = coverage.duplicate_assignments || [];
  const overloaded = coverage.over_capacity_teachers || [];
  const overloadedClasses = coverage.over_capacity_classes || [];
  const groups = [
    ["Giáo viên chưa phân công", coverage.unassigned_teachers || []],
    ["Môn chưa phân công", coverage.unassigned_subjects || []],
    ["Lớp chưa phân công", coverage.unassigned_classes || []],
  ].filter(([, rows]) => rows.length);
  const duplicateHtml = duplicates.length
    ? `<div><b>Không thể xếp do phân công lớp–môn bị trùng</b><p>${duplicates.map((row) => `${esc(row.class_name)} – ${esc(row.subject_name)}: ID ${(row.assignment_ids || []).join(", ")}`).join("; ")}. Hãy xóa hoặc chuyển để mỗi lớp–môn chỉ còn một giáo viên.</p></div>`
    : "";
  const overloadHtml = overloaded.length
    ? `<div><b>Không thể xếp đầy đủ do giáo viên quá tải</b><p>${overloaded.map((row) => `${esc(row.teacher_name)}: ${row.assigned}/${row.capacity} tiết (dư ${row.excess})`).join("; ")}. Hãy giảm/chuyển phân công, tăng giới hạn tiết/ngày hoặc bỏ bớt tiết tránh.</p></div>`
    : "";
  const classOverloadHtml = overloadedClasses.length
    ? `<div><b>Không thể xếp đầy đủ do lớp vượt số ô học</b><p>${overloadedClasses.map((row) => `${esc(row.class_name)}: ${row.assigned}/${row.capacity} tiết (dư ${row.excess})`).join("; ")}. Hãy giảm phân công hoặc bỏ bớt khóa/tiết tránh của lớp.</p></div>`
    : "";
  const gapsHtml = groups.length
    ? `<div><b>Dữ liệu chưa có phân công</b><p>Giáo viên, môn hoặc lớp chỉ xuất hiện trên thời khóa biểu sau khi được tạo ở mục Phân công.</p>${groups.map(([label, rows]) => `<div><strong>${label}:</strong> ${rows.map((row) => esc(row.name)).join(", ")}</div>`).join("")}</div>`
    : "";
  const coverageHtml =
    duplicateHtml || overloadHtml || classOverloadHtml || gapsHtml
      ? `<div class="coverage-warning">${duplicateHtml}${overloadHtml}${classOverloadHtml}${gapsHtml}<button class="btn ghost" onclick="goToAssignments()">Đến mục Phân công</button></div>`
      : "";
  if (coverageBox && coverageBox.innerHTML !== coverageHtml) {
    coverageBox.innerHTML = coverageHtml;
  }
  const counts = {};
  data.lessons.forEach(
    (lesson) =>
      (counts[lesson.assignment_id] = (counts[lesson.assignment_id] || 0) + 1),
  );
  let rows = data.assignments.map((item) => ({
    ...item,
    scheduled: counts[item.id] || 0,
    remaining: Math.max(0, item.periods_per_week - (counts[item.id] || 0)),
  }));
  if (vt && ve && vt.value === "class")
    rows = rows.filter((item) => item.class_id === Number(ve.value));
  if (vt && ve && vt.value === "teacher")
    rows = rows.filter((item) => item.teacher_id === Number(ve.value));
  if (vt && ve && vt.value === "subject")
    rows = rows.filter((item) => item.subject_id === Number(ve.value));
  if (!rows.length) {
    if (scheduledBox && scheduledBox.innerHTML !== "") scheduledBox.innerHTML = "";
    const filtered =
      vt &&
      ve &&
      (vt.value === "class" || vt.value === "teacher" || vt.value === "subject");
    const filterLabel =
      vt?.value === "class"
        ? "lớp"
        : vt?.value === "teacher"
          ? "giáo viên"
          : "môn học";
    const emptyHtml = `<div class="empty-state">${filtered ? "Không có phân công cho " + filterLabel + " đang chọn." : "Chưa có phân công để xếp. Hãy tạo phân công lớp – môn – giáo viên – số tiết/tuần."}</div>`;
    if (tray.innerHTML !== emptyHtml) tray.innerHTML = emptyHtml;
    return;
  }
  const scheduled = rows.filter((item) => item.scheduled > 0),
    pending = rows.filter((item) => item.remaining > 0);
  const scheduledHtml = scheduled.length
    ? `<div class="scheduled-label">Đang có trên lịch · bấm thẻ rồi bấm vào khay để thu hồi các tiết chưa cố định của phân công. Các tiết đã cố định luôn được giữ nguyên.</div><div class="scheduled-cards">${scheduled.map((item) => `<div class="scheduled-assignment" data-tap-payload="scheduled-assignment:${item.id}"><div><b>${esc(item.subject_short)}</b><small>${esc(item.class_name)} · ${esc(item.teacher_short)}</small></div><span>${item.scheduled}/${item.periods_per_week} tiết</span></div>`).join("")}</div>`
    : "";
  if (scheduledBox && scheduledBox.innerHTML !== scheduledHtml) {
    scheduledBox.innerHTML = scheduledHtml;
  }
  const hint =
    '<div class="tray-action-hint">Bấm một tiết trên thời khóa biểu hoặc thẻ “đang có trên lịch”, sau đó bấm vào khay này để đưa về khay</div>';
  const trayHtml =
    hint +
    pending
      .map(
        (item) =>
          `<div class="tray-lesson" data-tap-payload="assignment:${item.id}"><div><b>${esc(item.subject_short)}</b><small>${esc(item.class_name)} · ${esc(item.teacher_short)}</small></div><span>Còn ${item.remaining}</span></div>`,
      )
      .join("");
  if (tray.innerHTML !== trayHtml) {
    tray.innerHTML = trayHtml;
  }
}

function clusteredLessonIds() {
  const marked = new Set();
  const modes = new Map(
    data.assignments.map((item) => [item.id, item.block_mode || "free"]),
  );
  const groups = new Map(),
    pps = data.project.periods,
    ppd = data.project.sessions * pps;
  for (const lesson of data.lessons) {
    const mode = modes.get(lesson.assignment_id);
    if (mode !== "preferred_double" && mode !== "required_double") continue;
    const day = Math.floor(lesson.slot / ppd),
      inside = lesson.slot % ppd,
      session = Math.floor(inside / pps),
      key = `${lesson.assignment_id}:${day}:${session}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(lesson);
  }
  for (const lessons of groups.values()) {
    lessons.sort((left, right) => left.slot - right.slot);
    let run = [];
    const markRun = () => {
      if (!run.length) return;
      const mode = modes.get(run[0].assignment_id);
      if (mode === "required_double") {
        for (let index = 0; index + 1 < run.length; index += 2) {
          marked.add(run[index].id);
          marked.add(run[index + 1].id);
        }
      } else if (run.length === 2) {
        run.forEach((lesson) => marked.add(lesson.id));
      }
      run = [];
    };
    for (const lesson of lessons) {
      if (run.length && lesson.slot !== run[run.length - 1].slot + 1) markRun();
      run.push(lesson);
    }
    markRun();
  }
  return marked;
}

function renderSchedule(preserveScroll = false) {
  const box = $("#scheduleGrid"),
    vt = $("#viewType"),
    ve = $("#viewEntity");
  if (!box || !vt || !ve) return;

  if (vt.value !== "overview" && !ve.value) {
    box.innerHTML =
      '<div class="empty-state">Không tìm thấy đối tượng phù hợp với bộ lọc hiện tại.</div>';
    return;
  }

  const days = data.project.days,
    pps = data.project.periods,
    sessions = data.project.sessions;
  const clustered = clusteredLessonIds();
  const conflicts = computeScheduleConflicts();
  const legend =
    '<div class="schedule-color-legend"><b>Chú thích màu</b><span><i class="schedule-color-swatch"></i>Tiết đơn</span><span><i class="schedule-color-swatch cluster"></i>Tiết đang được ghép đôi</span><span><i class="schedule-color-swatch" style="background:#fee2e2;border:1px dashed #ef4444"></i>Ô vi phạm ràng buộc</span></div>';

  // Lập chỉ mục một lần cho mỗi lần render để tránh quét toàn bộ assignments/lessons
  // ở từng ô thời khóa biểu.
  const assignmentById = new Map(
    data.assignments.map((assignment) => [assignment.id, assignment]),
  );
  const selectedEntityId = Number(ve.value);
  const matchesCurrentView = (assignment) => {
    if (!assignment) return false;
    if (vt.value === "overview") return true;
    if (vt.value === "class") return assignment.class_id === selectedEntityId;
    if (vt.value === "subject") return assignment.subject_id === selectedEntityId;
    return assignment.teacher_id === selectedEntityId;
  };
  const sortLessons = (left, right) => {
    const a = assignmentById.get(left.assignment_id);
    const b = assignmentById.get(right.assignment_id);
    return (a?.class_name || "").localeCompare(b?.class_name || "", "vi");
  };
  const lessonsBySlot = new Map();
  for (const lesson of data.lessons) {
    const assignment = assignmentById.get(lesson.assignment_id);
    if (!matchesCurrentView(assignment)) continue;
    if (!lessonsBySlot.has(lesson.slot)) lessonsBySlot.set(lesson.slot, []);
    lessonsBySlot.get(lesson.slot).push(lesson);
  }
  for (const lessons of lessonsBySlot.values()) lessons.sort(sortLessons);

  const renderLessonsForSlot = (slot) => {
    const lessons = lessonsBySlot.get(slot) || [];
    const visibleConflictReasons = [
      ...new Set(
        lessons.flatMap((lesson) =>
          conflicts.conflictsByLessonId.get(lesson.id) || [],
        ),
      ),
    ];
    const slotConflictText = visibleConflictReasons.join("; ");
    const lessonMarkup = lessons
      .map((lesson) =>
        lessonHtml(
          lesson,
          vt.value,
          clustered.has(lesson.id),
          conflicts.conflictsByLessonId.get(lesson.id) || [],
          assignmentById.get(lesson.assignment_id),
        ),
      )
      .join("");
    return {
      hasConflict: visibleConflictReasons.length > 0,
      slotConflictText,
      lessonMarkup,
    };
  };

  const currentTable = box.querySelector(".timetable");
  const totalSlots = days * sessions * pps;
  const isOverview = vt.value === "overview";
  const canUpdateInPlace =
    currentTable &&
    currentTable.classList.contains("overview-timetable") === isOverview &&
    currentTable.querySelectorAll(".cell.available[data-slot]").length ===
    totalSlots;

  if (canUpdateInPlace) {
    for (let slot = 0; slot < totalSlots; slot++) {
      const cell = currentTable.querySelector(
        `.cell.available[data-slot="${slot}"]`,
      );
      if (!cell) continue;
      const { hasConflict, slotConflictText, lessonMarkup } =
        renderLessonsForSlot(slot);

      cell.classList.toggle("has-conflict", hasConflict);
      cell.dataset.conflictTitle = slotConflictText;
      if (cell.title !== slotConflictText) cell.title = slotConflictText;
      if (cell.innerHTML !== lessonMarkup) cell.innerHTML = lessonMarkup;
    }
    return;
  }

  const scrollState = preserveScroll ? captureRefreshScrollState() : null;

  let html = `<div class="timetable ${vt.value === "overview" ? "overview-timetable" : ""}" style="grid-template-columns:90px repeat(${days},minmax(135px,1fr))"><div class="cell head">Tiết</div>`;
  for (let d = 0; d < days; d++)
    html += `<div class="cell head">${["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][d]}</div>`;
  for (let s = 0; s < sessions; s++) {
    for (let p = 0; p < pps; p++) {
      html += `<div class="cell period">${sessions > 1 ? (s === 0 ? "S" : "C") + " " : ""}${p + 1}</div>`;
      for (let d = 0; d < days; d++) {
        const slot = d * (sessions * pps) + s * pps + p;
        const { hasConflict, slotConflictText, lessonMarkup } =
          renderLessonsForSlot(slot);
        html += `<div class="cell available ${hasConflict ? "has-conflict" : ""}" data-slot="${slot}" data-conflict-title="${esc(slotConflictText)}" title="${esc(slotConflictText)}">${lessonMarkup}</div>`;
      }
    }
  }
  html += "</div>";
  box.innerHTML = legend + html;

  if (scrollState) {
    restoreRefreshScrollState(scrollState);
  }
}

function lessonHtml(
  l,
  view,
  inCluster = false,
  conflictReasons = [],
  assignment = null,
) {
  const a = assignment || data.assignments.find((x) => x.id === l.assignment_id);
  if (!a) return "";
  const detail = `${a.class_name} · ${a.teacher_short}`;
  const actions =
    window.READ_ONLY
      ? ""
      : l.locked
        ? `<button class="lesson-remove" title="Bỏ cố định tiết/cặp này" aria-label="Bỏ cố định tiết/cặp này" onclick="event.stopPropagation();unfixGroup(${a.id},${l.slot},this)">🔓</button>`
        : `<button class="lesson-pin" title="Cố định tiết/cặp này" aria-label="Cố định tiết/cặp này" onclick="event.stopPropagation();setFixed(${a.id},${l.slot},this)">📌</button><button class="lesson-remove" title="Gỡ tiết" aria-label="Gỡ tiết khỏi thời khóa biểu" onclick="event.stopPropagation();removeLesson(${l.id})">×</button>`;
  const tapPayload =
    !window.READ_ONLY && !l.locked
      ? ` data-tap-payload="${l.id}"`
      : "";
  const normalizedConflictReasons = Array.isArray(conflictReasons)
    ? conflictReasons.filter(Boolean)
    : conflictReasons
      ? [String(conflictReasons)]
      : [];
  const conflictText = [...new Set(normalizedConflictReasons)].join("; ");
  const conflictBadge = conflictText
    ? `<button type="button" class="conflict-badge" title="${esc(conflictText)}" aria-label="Xem ${normalizedConflictReasons.length} xung đột" data-conflict-message="${esc(conflictText)}">!</button>`
    : "";
  return `<div class="lesson ${view === "overview" ? "lesson-overview" : ""} ${inCluster ? "lesson-cluster" : ""} ${conflictText ? "has-conflict" : ""}"${tapPayload} title="${esc(conflictText)}"><b>${esc(a.subject_short)}</b><small>${esc(detail)}</small>${l.locked ? ' <span title="Tiết cố định">🔒</span>' : ""}${conflictBadge}${actions}</div>`;
}

function showToast(message, type = "info", duration = 3200) {
  if (!message) return;
  if (
    window.OperationStatus &&
    typeof window.OperationStatus.notify === "function"
  ) {
    window.OperationStatus.notify(message, type);
    return;
  }
  let container = document.getElementById("appToastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "appToastContainer";
    container.className = "app-toast-container";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  toast.className = `app-toast is-${type}`;
  const icon =
    type === "error" || type === "warning"
      ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
      : type === "success"
        ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>'
        : '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  toast.innerHTML = `<span class="app-toast-icon">${icon}</span><span class="app-toast-text">${esc(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("is-hiding");
    setTimeout(() => {
      if (toast.isConnected) toast.remove();
    }, 300);
  }, duration);
}

document.addEventListener("click", (event) => {
  const badge = event.target.closest(".conflict-badge[data-conflict-message]");
  if (!badge) return;
  event.preventDefault();
  event.stopPropagation();
  showToast(
    badge.dataset.conflictMessage || "Xung đột thời khóa biểu.",
    "warning",
  );
});

const pendingLessonPlacements = new Set();
function renderScheduleAfterLessonChange() {
  const scrollState = captureRefreshScrollState();
  renderSchedule(true);
  renderManualTray();
  if ($("#statLessons")) $("#statLessons").textContent = data.lessons.length;
  restoreRefreshScrollState(scrollState);
}
function showPlacementConflict(slot, message) {
  const text = message || "Không thể xếp tiết";
  const cell = document.querySelector(`.cell.available[data-slot="${slot}"]`);
  if (cell) {
    cell.title = text;
    cell.classList.add("conflict-shake");
    setTimeout(() => cell.classList.remove("conflict-shake"), 600);
  }
  showToast(text, "warning", 3600);
}
function localPlacementValidationError(assignment, slot, excludeLessonId = null, isNew = false) {
  const pps = Number(data?.project?.periods || 0);
  const sessions = Number(data?.project?.sessions || 0);
  const days = Number(data?.project?.days || 0);
  const periodsPerDay = pps * sessions;
  const totalSlots = days * periodsPerDay;

  if (
    !assignment ||
    !Number.isInteger(slot) ||
    slot < 0 ||
    periodsPerDay <= 0 ||
    slot >= totalSlots
  )
    return "Ô thời khóa biểu không hợp lệ.";

  const blocked = new Set((data.project.blocked_slots || []).map(Number));
  if (blocked.has(slot))
    return "Tiết này đã bị khóa toàn trường và không được xếp.";

  const teacher = (data.teachers || []).find(
    (item) => Number(item.id) === Number(assignment.teacher_id),
  );
  const schoolClass = (data.classes || []).find(
    (item) => Number(item.id) === Number(assignment.class_id),
  );
  const subject = (data.subjects || []).find(
    (item) => Number(item.id) === Number(assignment.subject_id),
  );
  if (!teacher || !schoolClass || !subject)
    return "Phân công không còn đầy đủ lớp, môn hoặc giáo viên.";

  if ((teacher.unavailable || []).some((value) => Number(value) === slot))
    return "Giáo viên không thể dạy ở tiết này theo ràng buộc chính thức.";
  if ((schoolClass.unavailable || []).some((value) => Number(value) === slot))
    return "Lớp không học ở tiết này.";

  const existing = (data.lessons || []).filter(
    (lesson) => Number(lesson.id) !== Number(excludeLessonId),
  );
  const assignmentById = new Map(
    (data.assignments || []).map((item) => [Number(item.id), item]),
  );

  for (const lesson of existing) {
    if (Number(lesson.slot) !== slot) continue;
    const other = assignmentById.get(Number(lesson.assignment_id));
    if (!other) continue;
    if (
      Number(other.class_id) === Number(assignment.class_id) ||
      Number(other.teacher_id) === Number(assignment.teacher_id)
    )
      return "Ô đích bị trùng lớp hoặc giáo viên.";
  }

  if (isNew) {
    const scheduled = existing.filter(
      (lesson) => Number(lesson.assignment_id) === Number(assignment.id),
    ).length;
    if (scheduled >= Number(assignment.periods_per_week || 0))
      return "Phân công này đã đủ số tiết/tuần.";
  }

  const targetDay = Math.floor(slot / periodsPerDay);
  const targetInsideDay = slot % periodsPerDay;
  const targetSession = Math.floor(targetInsideDay / pps);
  const targetPeriod = targetInsideDay % pps;
  let teacherPeriods = 0;
  const subjectPeriods = [];

  for (const lesson of existing) {
    const lessonSlot = Number(lesson.slot);
    if (!Number.isInteger(lessonSlot) || Math.floor(lessonSlot / periodsPerDay) !== targetDay)
      continue;
    const other = assignmentById.get(Number(lesson.assignment_id));
    if (!other) continue;

    if (Number(other.teacher_id) === Number(assignment.teacher_id))
      teacherPeriods += 1;

    const insideDay = lessonSlot % periodsPerDay;
    if (
      Math.floor(insideDay / pps) === targetSession &&
      Number(other.class_id) === Number(assignment.class_id) &&
      Number(other.subject_id) === Number(assignment.subject_id)
    )
      subjectPeriods.push(insideDay % pps);
  }

  const maxPeriodsDay = Number(teacher.max_periods_day || 0);
  if (maxPeriodsDay > 0 && teacherPeriods >= maxPeriodsDay)
    return "Giáo viên đã đạt số tiết tối đa trong ngày.";

  const maxConsecutive = Number(subject.max_consecutive || 0);
  if (maxConsecutive > 0) {
    const periods = [...new Set([...subjectPeriods, targetPeriod])].sort(
      (left, right) => left - right,
    );
    let longest = periods.length ? 1 : 0;
    let current = periods.length ? 1 : 0;
    for (let index = 1; index < periods.length; index += 1) {
      current = periods[index] === periods[index - 1] + 1 ? current + 1 : 1;
      longest = Math.max(longest, current);
    }
    if (longest > maxConsecutive)
      return "Vượt số tiết liên tiếp tối đa của môn học.";
  }

  return null;
}
async function placeLessonPayload(raw, slot) {
  if (window.READ_ONLY || !raw || pendingLessonPlacements.has(raw)) return false;
  const numericSlot = Number(slot);
  const isNew = raw.startsWith("assignment:");
  const rawId = isNew ? raw.slice("assignment:".length) : raw;
  if (!/^\d+$/.test(rawId)) return false;

  const id = Number(rawId);
  let assignment = null;
  let lesson = null;
  if (isNew) {
    assignment = data.assignments.find((item) => Number(item.id) === id);
    if (!assignment) return false;
  } else {
    lesson = data.lessons.find((item) => Number(item.id) === id);
    if (!lesson || lesson.locked) return false;
    if (Number(lesson.slot) === numericSlot) return false;
    assignment = data.assignments.find(
      (item) => Number(item.id) === Number(lesson.assignment_id),
    );
    if (!assignment) return false;
  }

  const localError = localPlacementValidationError(
    assignment,
    numericSlot,
    isNew ? null : lesson.id,
    isNew,
  );
  if (localError) {
    showPlacementConflict(numericSlot, localError);
    return false;
  }

  const endpoint = isNew
    ? `/api/projects/${PROJECT_ID}/lessons`
    : `/api/projects/${PROJECT_ID}/move`;
  const payload = isNew
    ? { assignment_id: id, slot: numericSlot }
    : { lesson_id: id, slot: numericSlot };

  pendingLessonPlacements.add(raw);
  try {
    const r = await fetch(endpoint, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    const j = await readApiResponse(r);
    if (!r.ok) {
      showPlacementConflict(numericSlot, apiErrorMessage(j, "Không thể xếp tiết"));
      return false;
    }

    // Chỉ cập nhật giao diện sau khi máy chủ đã chấp nhận. Nhờ vậy một ô bị
    // từ chối bởi các ràng buộc sâu (ví dụ required_double) không hiện tiết
    // tạm thời rồi "nhảy" trở lại vị trí cũ.
    if (isNew) {
      data.lessons.push({
        id: Number(j.id),
        assignment_id: id,
        slot: numericSlot,
        locked: false,
      });
    } else {
      const live = data.lessons.find((item) => Number(item.id) === id);
      if (live) live.slot = numericSlot;
    }
    renderScheduleAfterLessonChange();

    try {
      await refresh(true, ["lessons"]);
    } catch (refreshError) {
      const refreshMessage =
        refreshError?.message || requestFailureMessage(refreshError);
      showToast(
        `Đã lưu thay đổi nhưng chưa thể đồng bộ lại dữ liệu: ${refreshMessage}`,
        "warning",
        5000,
      );
    }
    return true;
  } catch (error) {
    showPlacementConflict(numericSlot, requestFailureMessage(error));
    return false;
  } finally {
    pendingLessonPlacements.delete(raw);
  }
}
async function removeLesson(id) {
  setTrayActionStatus("loading", "Đang đưa tiết về khay…");
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/lessons/${id}`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const j = await readApiResponse(r);
    if (r.ok) {
      await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Tiết đã được đưa về khay trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      setTrayActionStatus("success", j.message || "Đã đưa tiết về khay", 1800);
      return true;
    }
    setTrayActionStatus("error", apiErrorMessage(j, "Không thể gỡ tiết"), 3600);
    return false;
  } catch (error) {
    setTrayActionStatus(
      "error",
      requestFailureMessage(
        error,
        "Mất kết nối tới máy chủ. Không thể đưa tiết về khay.",
      ),
      3600,
    );
    return false;
  }
}
async function setFixed(assignmentId, slot, button) {
  const original = button?.textContent || "📌";
  if (button) {
    button.disabled = true;
    button.textContent = "…";
  }
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/fixed`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ assignment_id: assignmentId, slot }),
    });
    const j = await readApiResponse(r);
    if (r.ok) {
      const refreshed = await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Tiết đã được cố định trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      if (!refreshed && button?.isConnected) {
        button.textContent = "✓";
        button.title = "Đã cố định trên máy chủ. Hãy tải lại trang để đồng bộ.";
        button.disabled = true;
      }
    } else {
      restoreTransientActionButton(
        button,
        original,
        apiErrorMessage(j, "Không thể cố định tiết"),
      );
    }
  } catch (error) {
    restoreTransientActionButton(button, original, requestFailureMessage(error));
  }
}
async function unfixGroup(assignmentId, slot, button) {
  const original = button?.textContent || "🔓";
  if (button) {
    button.disabled = true;
    button.textContent = "…";
  }
  try {
    const r = await fetch(
      `/api/projects/${PROJECT_ID}/fixed/${assignmentId}/${slot}`,
      { method: "DELETE", headers: operationHeaders() },
    );
    const j = await readApiResponse(r);
    if (r.ok) {
      const refreshed = await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Đã bỏ cố định trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      if (!refreshed && button?.isConnected) {
        button.textContent = "✓";
        button.title = "Đã bỏ cố định trên máy chủ. Hãy tải lại trang để đồng bộ.";
        button.disabled = true;
      }
    } else {
      restoreTransientActionButton(
        button,
        original,
        apiErrorMessage(j, "Không thể bỏ cố định"),
      );
    }
  } catch (error) {
    restoreTransientActionButton(button, original, requestFailureMessage(error));
  }
}
async function returnAssignmentToTray(id) {
  setTrayActionStatus("loading", "Đang đưa các tiết chưa cố định về khay…");
  try {
    const r = await fetch(
      `/api/projects/${PROJECT_ID}/assignments/${id}/lessons`,
      { method: "DELETE", headers: operationHeaders() },
    );
    const j = await readApiResponse(r);
    if (!r.ok) {
      setTrayActionStatus(
        "error",
        apiErrorMessage(j, "Không thể đưa phân công về khay"),
        3600,
      );
      return false;
    }

    await refreshAfterSuccessfulMutation(
      ["lessons"],
      "Các tiết chưa cố định đã được đưa về khay trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
    );
    setTrayActionStatus(
      "success",
      j.message || `Đã đưa ${Number(j.removed) || 0} tiết chưa cố định về khay.`,
      2600,
    );
    return true;
  } catch (error) {
    setTrayActionStatus(
      "error",
      requestFailureMessage(
        error,
        "Mất kết nối tới máy chủ. Không thể đưa phân công về khay.",
      ),
      3600,
    );
    return false;
  }
}

async function returnAllToTray(button) {
  if (
    !(await confirmAction(
      "Đưa toàn bộ tiết chưa cố định về khay? Các tiết đã cố định sẽ được giữ nguyên. Phân công và số tiết/tuần không thay đổi.",
      { title: "Đưa lịch về khay", confirmText: "Đưa về khay" },
    ))
  )
    return;
  setInlineActionState(button, "loading", {
    idle: "Đưa tiết chưa cố định về khay",
    loading: "Đang đưa về khay...",
  });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/lessons`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const j = await readApiResponse(r);
    if (r.ok) {
      await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Các tiết đã được đưa về khay trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      setInlineActionState(
        button,
        "success",
        { idle: "Đưa tiết chưa cố định về khay", success: "Đã đưa về khay" },
        1800,
      );
      showToast(
        j.message || "Đã đưa các tiết chưa cố định về khay.",
        "success",
        2600,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: "Đưa tiết chưa cố định về khay", error: "Chưa đưa được" },
        2200,
      );
      showToast(
        apiErrorMessage(j, "Không thể đưa lịch về khay."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Đưa tiết chưa cố định về khay", error: "Chưa hoàn tất" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
async function returnPayloadToTray(raw) {
  if (window.READ_ONLY || !raw || raw.startsWith("assignment:")) return false;
  if (raw.startsWith("scheduled-assignment:")) {
    return returnAssignmentToTray(Number(raw.split(":")[1]));
  }
  if (/^\d+$/.test(raw)) return removeLesson(Number(raw));
  return false;
}
function constraintStateMarkup(blocked, label) {
  const icon = blocked
    ? '<svg class="constraint-state-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>'
    : '<svg class="constraint-state-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>';
  return `${icon}<span>${esc(label)}</span>`;
}
function animateConstraintState(host, blocked, label) {
  if (!host) return;
  let stage = host.querySelector(":scope > .constraint-state-stage");
  if (!stage) {
    stage = document.createElement("span");
    stage.className = "constraint-state-stage";
    host.textContent = "";
    host.appendChild(stage);
  }
  stage
    .querySelectorAll(".constraint-state-content.constraint-state-leaving")
    .forEach((node) => node.remove());
  const current = stage.querySelector(".constraint-state-content");
  const next = document.createElement("span");
  next.className = `constraint-state-content constraint-state-enter ${blocked ? "is-blocked" : "is-allowed"}`;
  next.innerHTML = constraintStateMarkup(blocked, label);
  if (current) {
    current.classList.add("constraint-state-leaving");
    const cleanup = () => current.remove();
    current.addEventListener("animationend", cleanup, { once: true });
    setTimeout(cleanup, 360);
  }
  stage.appendChild(next);
}
function setGlobalSlotLockState(button, locked, animate = true) {
  if (!button) return;
  button.classList.toggle("is-locked", locked);
  if (animate)
    animateConstraintState(button, locked, locked ? "Đã khóa" : "Cho phép");
  else
    button.innerHTML = `<span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, locked ? "Đã khóa" : "Cho phép")}</span></span>`;
}
function setSessionLockState(button, locked, animate = true) {
  if (!button) return;
  button.classList.toggle("is-locked", locked);
  const label = button.dataset.label;
  let host = button.querySelector(".session-lock-state");
  if (!host) {
    const old = button.querySelector("span");
    host = document.createElement("span");
    host.className = "session-lock-state";
    if (old) old.replaceWith(host);
    else button.appendChild(host);
  }
  if (animate) animateConstraintState(host, locked, label);
  else
    host.innerHTML = `<span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, label)}</span></span>`;
}
function numberSetsEqual(left, right) {
  if (left.size !== right.size) return false;
  for (const value of left) if (!right.has(value)) return false;
  return true;
}
function syncConstraintDraftDirty() {
  const type = $("#constraintType"),
    ent = $("#constraintEntity");
  if (!type || !ent?.value) {
    constraintDraftDirty = false;
    return constraintDraftDirty;
  }
  const obj = (type.value === "teacher" ? data.teachers : data.classes).find(
    (item) => item.id === Number(ent.value),
  ),
    saved = new Set((obj?.unavailable || []).map(Number)),
    current = new Set(
      [...document.querySelectorAll("[data-cslot].blocked")].map((cell) =>
        Number(cell.dataset.cslot),
      ),
    );
  constraintDraftDirty = !numberSetsEqual(saved, current);
  return constraintDraftDirty;
}
function syncGlobalLocksDraftDirty() {
  const saved = new Set((data.project.blocked_slots || []).map(Number)),
    current = new Set(
      [...document.querySelectorAll("[data-global-slot].is-locked")].map(
        (button) => Number(button.dataset.globalSlot),
      ),
    );
  globalLocksDraftDirty = !numberSetsEqual(saved, current);
  return globalLocksDraftDirty;
}
function toggleConstraintCell(cell) {
  const blocked = !cell.classList.contains("blocked");
  cell.classList.toggle("blocked", blocked);
  cell.setAttribute("aria-pressed", blocked ? "true" : "false");
  animateConstraintState(cell, blocked, blocked ? "Tiết tránh" : "Có thể xếp");
  syncConstraintDraftDirty();
}
function ensureGlobalSessionLockPanel() {
  const section = $("#constraints");
  if (!section) return null;
  let panel = $("#globalSessionLocks");
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "globalSessionLocks";
  panel.className = "global-session-locks";
  panel.innerHTML =
    '<h2>Khóa lịch toàn trường</h2><p>Chọn khóa nguyên buổi hoặc chỉ khóa từng tiết. Xếp tự động và thao tác bấm để xếp/chuyển đều tuân thủ các khóa này.</p><div id="sessionLockGrid" class="session-lock-grid"></div><div class="global-slot-lock-title"><h3>Khóa từng tiết</h3><p>Nhấn vào từng ô để khóa hoặc mở khóa riêng tiết đó.</p></div><div id="globalSlotLockGrid" class="global-slot-lock-grid"></div><div class="row end"><button class="btn" type="button" onclick="saveGlobalSessionLocks(this)">Lưu khóa lịch</button></div>';
  const toolbar = section.querySelector(".constraint-toolbar");
  section.insertBefore(panel, toolbar);
  return panel;
}
function toggleSessionLock(button) {
  const locked = !button.classList.contains("is-locked"),
    key = Number(button.dataset.sessionLock);
  setSessionLockState(button, locked);
  document
    .querySelectorAll(`[data-global-session="${key}"]`)
    .forEach((slot) => setGlobalSlotLockState(slot, locked));
  syncGlobalLocksDraftDirty();
}
function toggleGlobalSlotLock(button) {
  const selected = !button.classList.contains("is-locked");
  setGlobalSlotLockState(button, selected);
  const key = Number(button.dataset.globalSession),
    slots = [...document.querySelectorAll(`[data-global-session="${key}"]`)],
    sessionButton = document.querySelector(`[data-session-lock="${key}"]`),
    locked =
      slots.length > 0 &&
      slots.every((slot) => slot.classList.contains("is-locked"));
  if (sessionButton) setSessionLockState(sessionButton, locked);
  syncGlobalLocksDraftDirty();
}
function renderGlobalSessionLocks() {
  if (!ensureGlobalSessionLockPanel()) return;
  const grid = $("#sessionLockGrid"),
    slotGrid = $("#globalSlotLockGrid"),
    blocked = new Set(data.project.blocked_slots || []),
    days = data.project.days,
    sessions = data.project.sessions,
    pps = data.project.periods,
    ppd = sessions * pps,
    dayNames = [
      "Thứ 2",
      "Thứ 3",
      "Thứ 4",
      "Thứ 5",
      "Thứ 6",
      "Thứ 7",
      "Chủ nhật",
    ];
  let html = "";
  for (let day = 0; day < days; day++)
    for (let session = 0; session < sessions; session++) {
      const key = day * sessions + session,
        start = day * ppd + session * pps,
        locked = Array.from({ length: pps }, (_, index) => start + index).every(
          (slot) => blocked.has(slot),
        ),
        sessionName =
          sessions === 1
            ? "Cả buổi"
            : session === 0
              ? "Buổi sáng"
              : "Buổi chiều";
      html += `<button type="button" class="session-lock ${locked ? "is-locked" : ""}" data-session-lock="${key}" data-label="${sessionName}" onclick="toggleSessionLock(this)"><b>${dayNames[day]}</b><span class="session-lock-state"><span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, sessionName)}</span></span></span></button>`;
    }
  grid.innerHTML = html;
  slotGrid.style.gridTemplateColumns = `90px repeat(${days},minmax(90px,1fr))`;
  let slotHtml =
    '<div class="slot-head">Tiết</div>' +
    dayNames
      .slice(0, days)
      .map((day) => `<div class="slot-head">${day}</div>`)
      .join("");
  for (let session = 0; session < sessions; session++)
    for (let period = 0; period < pps; period++) {
      slotHtml += `<div class="slot-period">${sessions > 1 ? (session === 0 ? "S" : "C") + " " : ""}${period + 1}</div>`;
      for (let day = 0; day < days; day++) {
        const slot = day * ppd + session * pps + period,
          key = day * sessions + session,
          locked = blocked.has(slot);
        slotHtml += `<button type="button" class="global-slot-lock ${locked ? "is-locked" : ""}" data-global-slot="${slot}" data-global-session="${key}" onclick="toggleGlobalSlotLock(this)"><span class="constraint-state-stage"><span class="constraint-state-content ${locked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(locked, locked ? "Đã khóa" : "Cho phép")}</span></span></button>`;
      }
    }
  slotGrid.innerHTML = slotHtml;
}
async function saveGlobalSessionLocks(button) {
  if (constraintDraftDirty) {
    showInlineActionFeedback(
      button,
      "Bạn còn thay đổi tiết tránh chưa lưu. Hãy lưu hoặc bỏ thay đổi tiết tránh trước khi lưu khóa lịch.",
      "warning",
      5200,
    );
    return;
  }
  const sessions = [
    ...document.querySelectorAll("[data-session-lock].is-locked"),
  ].map((button) => Number(button.dataset.sessionLock)),
    slots = [...document.querySelectorAll("[data-global-slot].is-locked")].map(
      (button) => Number(button.dataset.globalSlot),
    );
  setInlineActionState(button, "loading", {
    idle: "Lưu khóa lịch",
    loading: "Đang lưu...",
  });
  try {
    const { response: r, result, cancelled } =
      await postJsonWithDisplacementConfirmation(
        `/api/projects/${PROJECT_ID}/session-locks`,
        { sessions, slots },
        { title: "Xác nhận khóa lịch", confirmText: "Lưu và đưa về khay" },
      );
    if (cancelled) {
      setInlineActionState(button, "idle", { idle: "Lưu khóa lịch" });
      showInlineActionFeedback(
        button,
        "Đã hủy. Lịch hiện tại chưa bị thay đổi.",
        "info",
        3200,
      );
      return;
    }
    if (r.ok) {
      globalLocksDraftDirty = false;
      try {
        await refresh(true);
      } catch {
        setInlineActionState(
          button,
          "success",
          { idle: "Lưu khóa lịch", success: "Đã lưu" },
          2200,
        );
        showInlineActionFeedback(
          button,
          "Khóa lịch đã được lưu trên máy chủ nhưng chưa tải lại được dữ liệu mới. Hãy tải lại trang nếu lịch chưa cập nhật đầy đủ.",
          "warning",
          6500,
        );
        return;
      }
      setInlineActionState(
        button,
        "success",
        { idle: "Lưu khóa lịch", success: "Đã lưu" },
        1700,
      );
      showInlineActionFeedback(
        button,
        result.removed
          ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.`
          : "Khóa lịch đã được lưu.",
        "success",
        2800,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: "Lưu khóa lịch", error: "Chưa lưu được" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể lưu khóa lịch."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Lưu khóa lịch", error: "Chưa lưu được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
function renderConstraintSelectors({ force = false } = {}) {
  if (!force && constraintDraftDirty) return;
  if (!globalLocksDraftDirty || !$("#globalSessionLocks"))
    renderGlobalSessionLocks();
  const type = $("#constraintType"),
    ent = $("#constraintEntity");
  if (!type || !ent) return;
  const rows = type.value === "teacher" ? data.teachers : data.classes;
  const old = ent.value;
  ent.innerHTML = opts(rows);
  if ([...ent.options].some((o) => o.value === old)) ent.value = old;
  type.dataset.previousValue = type.value;
  ent.dataset.previousValue = ent.value;
  type.onchange = async () => {
    const previous = type.dataset.previousValue || "teacher";
    if (constraintDraftDirty) {
      const confirmed = await confirmAction(
        "Bạn có thay đổi tiết tránh chưa lưu. Đổi loại đối tượng sẽ bỏ các thay đổi đó.",
        { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
      );
      if (!confirmed) {
        type.value = previous;
        return;
      }
      constraintDraftDirty = false;
    }
    type.dataset.previousValue = type.value;
    renderConstraintSelectors({ force: true });
  };
  ent.onchange = async () => {
    const previous = ent.dataset.previousValue || "";
    if (constraintDraftDirty) {
      const confirmed = await confirmAction(
        "Bạn có thay đổi tiết tránh chưa lưu. Đổi giáo viên/lớp sẽ bỏ các thay đổi đó.",
        { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
      );
      if (!confirmed) {
        ent.value = previous;
        return;
      }
      constraintDraftDirty = false;
    }
    ent.dataset.previousValue = ent.value;
    renderConstraintGrid();
  };
  renderConstraintGrid();
}
function renderConstraintGrid() {
  const box = $("#constraintGrid"),
    type = $("#constraintType"),
    ent = $("#constraintEntity");
  if (!box) return;
  if (!ent?.value) {
    box.innerHTML =
      '<div class="empty-state">Hãy thêm giáo viên hoặc lớp học trước khi thiết lập tiết tránh.</div>';
    return;
  }
  const obj = (type.value === "teacher" ? data.teachers : data.classes).find(
    (x) => x.id === Number(ent.value),
  );
  const blocked = new Set(obj?.unavailable || []),
    days = data.project.days,
    pps = data.project.periods,
    sessions = data.project.sessions;
  let h = `<div class="timetable constraint-timetable" style="grid-template-columns:90px repeat(${days},minmax(110px,1fr))"><div class="cell head">Tiết</div>`;
  for (let d = 0; d < days; d++)
    h += `<div class="cell head">${["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][d]}</div>`;
  for (let s = 0; s < sessions; s++)
    for (let p = 0; p < pps; p++) {
      h += `<div class="cell period">${sessions > 1 ? (s ? "C" : "S") + " " : ""}${p + 1}</div>`;
      for (let d = 0; d < days; d++) {
        const slot = d * (sessions * pps) + s * pps + p,
          isBlocked = blocked.has(slot);
        h += `<div role="button" tabindex="0" aria-pressed="${isBlocked ? "true" : "false"}" data-cslot="${slot}" onclick="toggleConstraintCell(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();toggleConstraintCell(this)}" class="cell available constraint-state-cell ${isBlocked ? "blocked" : ""}"><span class="constraint-state-stage"><span class="constraint-state-content ${isBlocked ? "is-blocked" : "is-allowed"}">${constraintStateMarkup(isBlocked, isBlocked ? "Tiết tránh" : "Có thể xếp")}</span></span></div>`;
      }
    }
  h += "</div>";
  box.innerHTML = h;
}
async function saveConstraints(button) {
  if (globalLocksDraftDirty) {
    showInlineActionFeedback(
      button,
      "Bạn còn thay đổi khóa lịch chưa lưu. Hãy lưu hoặc bỏ thay đổi khóa lịch trước khi lưu tiết tránh.",
      "warning",
      5200,
    );
    return;
  }
  const entity = $("#constraintEntity");
  if (!entity?.value) {
    setInlineActionState(
      button,
      "error",
      { idle: "Lưu ràng buộc", error: "Chọn đối tượng" },
      1800,
    );
    showInlineActionFeedback(
      button,
      "Hãy chọn giáo viên hoặc lớp học trước.",
      "error",
      4200,
    );
    return;
  }
  const slots = [...document.querySelectorAll("[data-cslot].blocked")].map(
    (x) => Number(x.dataset.cslot),
  );
  setInlineActionState(button, "loading", {
    idle: "Lưu ràng buộc",
    loading: "Đang lưu...",
  });
  try {
    const { response: r, result, cancelled } =
      await postJsonWithDisplacementConfirmation(
        `/api/projects/${PROJECT_ID}/constraints`,
        {
          entity_type: $("#constraintType").value,
          entity_id: Number(entity.value),
          slots,
        },
        { title: "Xác nhận tiết tránh", confirmText: "Lưu và đưa về khay" },
      );
    if (cancelled) {
      setInlineActionState(button, "idle", { idle: "Lưu ràng buộc" });
      showInlineActionFeedback(
        button,
        "Đã hủy. Lịch hiện tại chưa bị thay đổi.",
        "info",
        3200,
      );
      return;
    }
    if (r.ok) {
      constraintDraftDirty = false;
      try {
        await refresh(true);
      } catch {
        setInlineActionState(
          button,
          "success",
          { idle: "Lưu ràng buộc", success: "Đã lưu" },
          2200,
        );
        showInlineActionFeedback(
          button,
          "Tiết tránh đã được lưu trên máy chủ nhưng chưa tải lại được dữ liệu mới. Hãy tải lại trang nếu lịch chưa cập nhật đầy đủ.",
          "warning",
          6500,
        );
        return;
      }
      setInlineActionState(
        button,
        "success",
        { idle: "Lưu ràng buộc", success: "Đã lưu" },
        1700,
      );
      showInlineActionFeedback(
        button,
        result.removed
          ? `Đã đưa ${result.removed} tiết bị ảnh hưởng về khay.`
          : "Đã lưu tiết tránh.",
        "success",
        2800,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: "Lưu ràng buộc", error: "Chưa lưu được" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể lưu tiết tránh."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Lưu ràng buộc", error: "Chưa lưu được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
function preferenceSlotLabel(slot) {
  const ppd = data.project.sessions * data.project.periods,
    day = Math.floor(slot / ppd),
    inside = slot % ppd,
    session = Math.floor(inside / data.project.periods),
    period = inside % data.project.periods;
  return `${["T2", "T3", "T4", "T5", "T6", "T7", "CN"][day]} · ${data.project.sessions > 1 ? (session ? "Chiều" : "Sáng") + " · " : ""}Tiết ${period + 1}`;
}
async function loadPreferenceInbox() {
  const box = $("#preferenceInbox");
  if (!box) return;
  box.innerHTML =
    '<div class="empty-state">Đang tải nguyện vọng giáo viên…</div>';
  const deleteAllButton = $("#deleteAllPreferencesButton");
  if (deleteAllButton) deleteAllButton.disabled = true;
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  if (!projectId) {
    box.innerHTML = '<div class="empty-state">Chưa có nguyện vọng nào.</div>';
    return;
  }
  try {
    const r = await fetch(`/api/projects/${projectId}/preferences`);
    const result = await readApiResponse(r);
    if (r.status === 404 || result?.status === 404) {
      box.innerHTML = '<div class="empty-state">Chưa có nguyện vọng nào.</div>';
      if (deleteAllButton) deleteAllButton.disabled = true;
      return;
    }
    if (!r.ok) {
      box.innerHTML = `<div class="empty-state">${esc(
        apiErrorMessage(result, "Không thể tải nguyện vọng giáo viên."),
      )}</div>`;
      return;
    }
    const items = Array.isArray(result.items) ? result.items : [];
    if (!items.length) {
      box.innerHTML = '<div class="empty-state">Chưa có nguyện vọng nào.</div>';
      if (deleteAllButton) deleteAllButton.disabled = true;
      return;
    }
    const statuses = {
      pending: "Chờ duyệt",
      accepted: "Đã ghi nhận",
      rejected: "Đã từ chối",
      superseded: "Đã thay thế",
    };
    if (deleteAllButton) deleteAllButton.disabled = items.length === 0;
    box.innerHTML = `<div class="preference-list">${items.map((item) => {
      const reviewActions = item.status === "pending"
        ? `<button class="btn ghost" onclick="reviewPreference(${item.id},'reject',this)">Từ chối</button><button class="btn" onclick="reviewPreference(${item.id},'accept',this)">Ghi nhận</button>`
        : "";
      return `<article class="preference-card"><div class="preference-card-head"><div><h3>${esc(item.teacher_name)}</h3>${item.teacher_email ? `<small>${esc(item.teacher_email)}</small>` : ""}<small>${esc(item.created_at_display || String(item.created_at || "").replace("T", " "))}</small></div><span class="status status-${item.status}">${statuses[item.status] || esc(item.status)}</span></div><div class="preference-detail"><b>Tiết mong muốn</b><div class="slot-chips">${item.preferred_slots?.length ? item.preferred_slots.map((slot) => `<span class="slot-chip preferred">${preferenceSlotLabel(slot)}</span>`).join("") : '<span class="muted">Không đăng ký</span>'}</div></div><div class="preference-detail"><b>Tiết cần tránh</b><div class="slot-chips">${item.unavailable_slots?.length ? item.unavailable_slots.map((slot) => `<span class="slot-chip blocked">${preferenceSlotLabel(slot)}</span>`).join("") : '<span class="muted">Không đăng ký</span>'}</div></div>${item.note ? `<p class="preference-note">${esc(item.note)}</p>` : ""}<div class="row end preference-card-actions"><button class="btn ghost preference-delete-btn" onclick="deletePreference(${item.id},this)">Xóa</button>${reviewActions}</div></article>`;
    }).join("")}</div>`;
  } catch (error) {
    box.innerHTML = `<div class="empty-state">${esc(
      requestFailureMessage(
        error,
        "Mất kết nối tới máy chủ. Không thể tải nguyện vọng giáo viên.",
      ),
    )}</div>`;
  }
}

async function deletePreference(id, button) {
  const confirmed = await confirmAction(
    "Xóa nguyện vọng này? Thao tác này không thể hoàn tác.",
    { title: "Xóa nguyện vọng", confirmText: "Xóa" },
  );
  if (!confirmed) return;
  setInlineActionState(button, "loading", {
    idle: "Xóa",
    loading: "Đang xóa...",
  });
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  try {
    const r = await fetch(`/api/projects/${projectId}/preferences/${id}`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const result = await readApiResponse(r);
    if (!r.ok) {
      setInlineActionState(button, "error", { idle: "Xóa", error: "Không thể xóa" }, 2200);
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể xóa nguyện vọng."),
        "error",
        5000,
      );
      return;
    }
    setInlineActionState(button, "success", { idle: "Xóa", success: "Đã xóa" });
    await wait(350);
    await loadPreferenceInbox();
  } catch (error) {
    setInlineActionState(button, "error", { idle: "Xóa", error: "Chưa xóa được" }, 2200);
    showToast(requestFailureMessage(error), "error", 5000);
  }
}

async function deleteAllPreferences(button) {
  const confirmed = await confirmAction(
    "Xóa toàn bộ nguyện vọng giáo viên trong bộ thời khóa biểu này? Thao tác này không thể hoàn tác.",
    { title: "Xóa tất cả nguyện vọng", confirmText: "Xóa tất cả" },
  );
  if (!confirmed) return;
  setInlineActionState(button, "loading", {
    idle: "Xóa tất cả",
    loading: "Đang xóa...",
  });
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  try {
    const r = await fetch(`/api/projects/${projectId}/preferences`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const result = await readApiResponse(r);
    if (!r.ok) {
      setInlineActionState(
        button,
        "error",
        { idle: "Xóa tất cả", error: "Không thể xóa" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể xóa toàn bộ nguyện vọng."),
        "error",
        5000,
      );
      return;
    }
    const deleted = Number(result.deleted || 0);
    setInlineActionState(button, "success", {
      idle: "Xóa tất cả",
      success: deleted ? `Đã xóa ${deleted}` : "Không có dữ liệu",
    });
    await wait(450);
    await loadPreferenceInbox();
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Xóa tất cả", error: "Chưa xóa được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}

async function reviewPreference(id, action, button) {
  const idle = action === "accept" ? "Ghi nhận" : "Từ chối",
    loading = action === "accept" ? "Đang ghi nhận..." : "Đang từ chối...",
    success = action === "accept" ? "Đã ghi nhận" : "Đã từ chối";
  setInlineActionState(button, "loading", { idle, loading });
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  try {
    const r = await fetch(
      `/api/projects/${projectId}/preferences/${id}/review`,
      {
        method: "POST",
        headers: operationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ action }),
      },
    );
    const result = await readApiResponse(r);
    if (r.ok) {
      setInlineActionState(button, "success", { idle, success });
      await wait(600);
      const refreshed = await refreshAfterSuccessfulMutation(
        null,
        "Nguyện vọng đã được cập nhật trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      if (refreshed) {
        try {
          await loadPreferenceInbox();
        } catch (error) {
          showToast(requestFailureMessage(error), "warning", 5000);
        }
      }
    } else {
      setInlineActionState(
        button,
        "error",
        { idle, error: "Chưa cập nhật" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể cập nhật nguyện vọng."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(button, "error", { idle, error: "Chưa cập nhật" }, 2200);
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
async function copyTextWithFallback(text) {
  const value = String(text || "");
  if (!value) return false;
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // WebView và một số trình duyệt chặn Clipboard API; dùng fallback bên dưới.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try {
    copied = Boolean(document.execCommand?.("copy"));
  } catch {
    copied = false;
  } finally {
    textarea.remove();
  }
  return copied;
}
function openManualShareDialog(shareUrl) {
  const value = String(shareUrl || "");
  if (!value) {
    showToast("Chưa có liên kết chia sẻ để sao chép.", "error", 4200);
    return;
  }

  let dialog = document.getElementById("manualShareDialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "manualShareDialog";
    dialog.className = "manual-share-dialog";
    dialog.setAttribute("data-app-zoom", "");
    dialog.innerHTML = `
      <div class="modal-form manual-share-modal">
        <div class="manual-share-head">
          <div>
            <h2>Liên kết chia sẻ</h2>
            <p>Trình duyệt đang chặn sao chép tự động. Chọn liên kết bên dưới và sao chép thủ công.</p>
          </div>
          <button type="button" class="manual-share-close" aria-label="Đóng">×</button>
        </div>
        <div class="manual-share-copy-row">
          <input id="manualShareInput" type="text" readonly aria-label="Liên kết chia sẻ">
          <button id="manualShareCopyBtn" type="button" class="btn">Sao chép</button>
        </div>
        <div id="manualShareHint" class="manual-share-hint" aria-live="polite"></div>
      </div>
    `;
    document.body.appendChild(dialog);

    dialog.querySelector(".manual-share-close")?.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.querySelector("#manualShareCopyBtn")?.addEventListener("click", async () => {
      const input = dialog.querySelector("#manualShareInput");
      const hint = dialog.querySelector("#manualShareHint");
      if (!input) return;
      const copied = await copyTextWithFallback(input.value);
      if (copied) {
        if (hint) {
          hint.textContent = "Đã sao chép liên kết.";
          hint.className = "manual-share-hint is-success";
        }
        return;
      }
      input.focus();
      input.select();
      input.setSelectionRange(0, input.value.length);
      if (hint) {
        hint.textContent = "Liên kết đã được chọn. Nhấn Ctrl+C (hoặc Sao chép trên điện thoại).";
        hint.className = "manual-share-hint is-error";
      }
    });
  }

  const input = dialog.querySelector("#manualShareInput");
  const hint = dialog.querySelector("#manualShareHint");
  if (input) input.value = value;
  if (hint) {
    hint.textContent = "";
    hint.className = "manual-share-hint";
  }

  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  setTimeout(() => {
    input?.focus();
    input?.select();
    input?.setSelectionRange(0, input.value.length);
  }, 0);
}
async function copyShare(button) {
  const shareUrl = String(window.SHARE_URL || "");
  const copied = await copyTextWithFallback(shareUrl);
  if (copied) {
    setInlineActionState(
      button,
      "success",
      { idle: "Chia sẻ", success: "Đã sao chép" },
      1700,
    );
    showInlineActionFeedback(button, "Đã sao chép liên kết chia sẻ.", "success", 2400);
    return;
  }
  setInlineActionState(
    button,
    "error",
    { idle: "Chia sẻ", error: "Sao chép thủ công" },
    2200,
  );
  showInlineActionFeedback(
    button,
    "Trình duyệt không cho phép sao chép tự động. Liên kết chia sẻ đã được mở để bạn sao chép thủ công.",
    "error",
    5200,
  );
  openManualShareDialog(shareUrl);
}

function markGlobalBlockedSlots() {
  const blocked = new Set(data.project.blocked_slots || []),
    sessions = data.project.sessions,
    pps = data.project.periods,
    ppd = sessions * pps;

  document.querySelectorAll("[data-slot]").forEach((cell) => {
    cell.classList.remove("global-locked-slot");
    cell.removeAttribute("aria-disabled");
    delete cell.dataset.globalLocked;
    cell.querySelectorAll(".global-lock-label").forEach((label) => label.remove());
    cell.title = cell.dataset.conflictTitle || "";
  });

  for (const slot of blocked) {
    const day = Math.floor(slot / ppd),
      inside = slot % ppd,
      session = Math.floor(inside / pps),
      start = day * ppd + session * pps,
      wholeSession = Array.from(
        { length: pps },
        (_, index) => start + index,
      ).every((value) => blocked.has(value)),
      label = wholeSession ? "KHÓA BUỔI" : "KHÓA TIẾT",
      lockTitle = wholeSession ? "Buổi này đã bị khóa" : "Tiết này đã bị khóa";
    document.querySelectorAll(`[data-slot="${slot}"]`).forEach((cell) => {
      cell.classList.add("global-locked-slot");
      cell.dataset.globalLocked = "true";
      cell.setAttribute("aria-disabled", "true");
      const conflictTitle = cell.dataset.conflictTitle || "";
      cell.title = conflictTitle ? `${lockTitle} · ${conflictTitle}` : lockTitle;
      cell.insertAdjacentHTML(
        "afterbegin",
        `<span class="global-lock-label">${label}</span>`,
      );
    });
  }
}

const renderScheduleWithoutGlobalLocks = renderSchedule;
renderSchedule = function (...args) {
  renderScheduleWithoutGlobalLocks(...args);
  markGlobalBlockedSlots();
};
renderAll();
renderScheduleSelectors();
renderConstraintSelectors();
activateRequestedWorkspaceTab();

entityModal?.addEventListener("close", () => {
  setEntityActionMessage("");
  const button = $("#entitySubmitButton");
  if (button) setInlineActionState(button, "idle", { idle: "Lưu" });
});

document.addEventListener("pointerdown", (event) => {
  const target = event.target.closest(".btn,.nav");
  if (!target) return;
  const rect = target.getBoundingClientRect(),
    ripple = document.createElement("span");
  ripple.className = "button-ripple";
  ripple.style.left = `${event.clientX - rect.left}px`;
  ripple.style.top = `${event.clientY - rect.top}px`;
  target.appendChild(ripple);
  setTimeout(() => ripple.remove(), 700);
});
function tapAssignCapabilities(payload) {
  return {
    schedule: Boolean(payload) && !payload.startsWith("scheduled-assignment:"),
    tray: Boolean(payload) && !payload.startsWith("assignment:"),
  };
}

function clearTapAssign() {
  document
    .querySelectorAll(".selected-for-assign")
    .forEach((el) => el.classList.remove("selected-for-assign"));
  const workspace = document.querySelector(".workspace");
  workspace?.classList.remove(
    "is-assign-mode",
    "tap-target-schedule",
    "tap-target-tray",
  );
  const bar = document.getElementById("tapAssignBar");
  if (bar) bar.remove();
  activeTapAssign = null;
}

function getPayloadLabel(payload) {
  if (!payload || !data) return "Tiết học";
  try {
    if (payload.startsWith("assignment:")) {
      const aid = Number(payload.split(":")[1]);
      const a = data.assignments.find((x) => x.id === aid);
      return a
        ? `${a.subject_short || a.subject_name} (${a.class_name})`
        : "Tiết học";
    }
    if (payload.startsWith("scheduled-assignment:")) {
      const aid = Number(payload.split(":")[1]);
      const a = data.assignments.find((x) => x.id === aid);
      return a
        ? `${a.subject_short || a.subject_name} (${a.class_name})`
        : "Phân công";
    }
    const lid = Number(payload);
    if (Number.isInteger(lid)) {
      const l = data.lessons.find((x) => x.id === lid);
      if (l) {
        const a = data.assignments.find((x) => x.id === l.assignment_id);
        return a
          ? `${a.subject_short || a.subject_name} (${a.class_name})`
          : "Tiết học";
      }
    }
  } catch (e) { }
  return "Tiết học";
}

function tapAssignInstruction(payload) {
  const capabilities = tapAssignCapabilities(payload);
  if (capabilities.schedule && capabilities.tray)
    return "Bấm ô trên lịch để chuyển, hoặc bấm khay để thu hồi";
  if (capabilities.tray) return "Bấm vào khay để thu hồi";
  return "Bấm ô trên lịch để xếp";
}

function handleTapToSelect(source, payload) {
  if (window.READ_ONLY || !source || !payload) return;
  if (activeTapAssign?.payload === payload) {
    clearTapAssign();
    return;
  }

  clearTapAssign();
  activeTapAssign = { payload };
  source.classList.add("selected-for-assign");

  const capabilities = tapAssignCapabilities(payload);
  const workspace = document.querySelector(".workspace");
  workspace?.classList.add("is-assign-mode");
  workspace?.classList.toggle("tap-target-schedule", capabilities.schedule);
  workspace?.classList.toggle("tap-target-tray", capabilities.tray);

  const label = getPayloadLabel(payload);
  const bar = document.createElement("div");
  bar.id = "tapAssignBar";
  bar.className = "tap-assign-bar";
  bar.innerHTML = `
    <div class="tap-assign-bar-info">
      <span class="tap-assign-pulse-dot" aria-hidden="true"></span>
      <span>Đang chọn: <b>${esc(label)}</b> · ${esc(tapAssignInstruction(payload))}</span>
    </div>
    <button type="button" data-tap-assign-cancel>Hủy</button>
  `;
  document.body.appendChild(bar);
}

async function finishTapAssignToSchedule(slot) {
  if (!activeTapAssign || !Number.isInteger(slot)) return;
  const payload = activeTapAssign.payload;
  if (!tapAssignCapabilities(payload).schedule) {
    showToast("Phân công này chỉ có thể đưa về khay.", "warning", 2800);
    return;
  }
  const succeeded = await placeLessonPayload(payload, slot);
  if (succeeded && activeTapAssign?.payload === payload) clearTapAssign();
}

async function finishTapAssignToTray() {
  if (!activeTapAssign) return;
  const payload = activeTapAssign.payload;
  if (!tapAssignCapabilities(payload).tray) {
    showToast("Tiết chưa xếp cần được chọn một ô trên lịch.", "warning", 2800);
    return;
  }
  const succeeded = await returnPayloadToTray(payload);
  if (succeeded && activeTapAssign?.payload === payload) clearTapAssign();
}

document.addEventListener("click", (event) => {
  const cancel = event.target.closest("[data-tap-assign-cancel]");
  if (cancel) {
    event.preventDefault();
    clearTapAssign();
    return;
  }

  if (
    window.READ_ONLY ||
    event.target.closest("button,a,input,select,textarea,label")
  )
    return;

  const source = event.target.closest("[data-tap-payload]");
  const sourcePayload = source?.dataset.tapPayload || "";

  if (!activeTapAssign) {
    if (sourcePayload) {
      event.preventDefault();
      handleTapToSelect(source, sourcePayload);
    }
    return;
  }

  if (sourcePayload && sourcePayload === activeTapAssign.payload) {
    event.preventDefault();
    clearTapAssign();
    return;
  }

  // Cards in the assignment trays are always selectable sources. Prioritize
  // switching selection over treating the whole tray as a destination.
  if (
    sourcePayload &&
    (source.classList.contains("tray-lesson") ||
      source.classList.contains("scheduled-assignment"))
  ) {
    event.preventDefault();
    handleTapToSelect(source, sourcePayload);
    return;
  }

  const lockedCell = event.target.closest(
    ".cell.available[data-slot].global-locked-slot",
  );
  if (lockedCell) {
    event.preventDefault();
    showPlacementConflict(
      Number(lockedCell.dataset.slot),
      "Tiết này đã bị khóa toàn trường và không được xếp.",
    );
    return;
  }

  const cell = event.target.closest(
    ".cell.available[data-slot]:not(.global-locked-slot)",
  );
  if (cell) {
    event.preventDefault();
    finishTapAssignToSchedule(Number(cell.dataset.slot));
    return;
  }

  const tray = event.target.closest(".unscheduled-tray");
  if (tray) {
    event.preventDefault();
    finishTapAssignToTray();
    return;
  }

  if (sourcePayload) {
    event.preventDefault();
    handleTapToSelect(source, sourcePayload);
    return;
  }

  if (!event.target.closest("#tapAssignBar")) clearTapAssign();
});

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key === "Escape" && activeTapAssign) {
      event.preventDefault();
      clearTapAssign();
    }
  },
  { capture: true },
);

window.addEventListener("beforeprint", () => {
  const scheduleGrid = document.querySelector("#scheduleGrid");
  if (scheduleGrid && !scheduleGrid.querySelector(".timetable"))
    renderSchedule();
});

function syncWorkspaceViewportMetrics() {
  const appbar = document.querySelector(".appbar");
  const height = appbar ? Math.ceil(appbar.getBoundingClientRect().height) : 64;
  document.documentElement.style.setProperty(
    "--workspace-appbar-height",
    `${Math.max(0, height)}px`,
  );
}

syncWorkspaceViewportMetrics();
window.addEventListener("resize", syncWorkspaceViewportMetrics, { passive: true });
window.addEventListener("orientationchange", syncWorkspaceViewportMetrics, {
  passive: true,
});

const SIDEBAR_DESKTOP_MEDIA = "(min-width: 901px)";

function syncSidebarCollapseForViewport() {
  const ws = document.querySelector(".workspace");
  if (!ws) return;
  const desktop = window.matchMedia(SIDEBAR_DESKTOP_MEDIA).matches;
  const btn = document.getElementById("sidebarCollapseBtn");

  if (!desktop) {
    ws.classList.remove("sidebar-collapsed");
    if (btn) {
      btn.title = "Thu gọn danh mục";
      btn.setAttribute("aria-label", btn.title);
    }
    return;
  }

  let shouldCollapse = false;
  try {
    shouldCollapse = localStorage.getItem("smart_tkb_sidebar_collapsed") === "1";
  } catch (e) { }
  ws.classList.toggle("sidebar-collapsed", shouldCollapse);
  if (btn) {
    btn.title = shouldCollapse ? "Mở rộng danh mục" : "Thu gọn danh mục";
    btn.setAttribute("aria-label", btn.title);
  }
}

function toggleSidebarCollapse() {
  const ws = document.querySelector(".workspace");
  if (!ws) return;

  // Mobile navigation is horizontal and must never enter the collapsed
  // desktop state, even if that state was saved previously.
  if (!window.matchMedia(SIDEBAR_DESKTOP_MEDIA).matches) {
    ws.classList.remove("sidebar-collapsed");
    return;
  }

  const isCollapsed = ws.classList.toggle("sidebar-collapsed");
  try {
    localStorage.setItem("smart_tkb_sidebar_collapsed", isCollapsed ? "1" : "0");
  } catch (e) { }
  const btn = document.getElementById("sidebarCollapseBtn");
  if (btn) {
    btn.title = isCollapsed ? "Mở rộng danh mục" : "Thu gọn danh mục";
    btn.setAttribute("aria-label", btn.title);
  }
}

document.addEventListener("DOMContentLoaded", syncSidebarCollapseForViewport);
window.addEventListener("resize", syncSidebarCollapseForViewport);
