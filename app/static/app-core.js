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
let latestAppliedFullRefreshSequence = 0;
const latestAppliedPartRefreshSequence = new Map();

async function refresh(skipOperationStatus = false, parts = null) {
  const scrollState = captureRefreshScrollState(),
    init = skipOperationStatus ? { headers: operationHeaders() } : undefined,
    requestedParts = Array.isArray(parts)
      ? [...new Set(parts.filter(Boolean))]
      : [],
    effectiveParts = requestedParts.includes("lessons")
      ? [...new Set([...requestedParts, "schedule_validation"])].sort()
      : [...requestedParts].sort(),
    query = effectiveParts.length
      ? `?parts=${encodeURIComponent(effectiveParts.join(","))}`
      : "",
    sequence = ++refreshRequestSequence,
    isFullRefresh = effectiveParts.length === 0;

  // A newer request does not make an older successful response stale by itself.
  // It only supersedes older data after the newer response was applied. This
  // prevents a later request that fails from causing a valid earlier response
  // to be discarded and leaving the UI on stale data.
  const responseAlreadySuperseded = () => {
    if (isFullRefresh) return latestAppliedFullRefreshSequence > sequence;
    if (latestAppliedFullRefreshSequence > sequence) return true;
    return effectiveParts.every(
      (part) => (latestAppliedPartRefreshSequence.get(part) || 0) > sequence,
    );
  };

  let r;
  try {
    r = await fetch(`/api/projects/${PROJECT_ID}/data${query}`, init);
  } catch (error) {
    if (responseAlreadySuperseded()) return data;
    throw error;
  }
  const result = await readApiResponse(r);
  if (!r.ok) {
    if (responseAlreadySuperseded()) return data;
    const error = new Error(
      apiErrorMessage(result, "Không thể tải lại dữ liệu từ máy chủ."),
    );
    error.isRefreshError = true;
    throw error;
  }
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    if (responseAlreadySuperseded()) return data;
    const error = new Error("Dữ liệu trả về từ máy chủ không hợp lệ.");
    error.isRefreshError = true;
    throw error;
  }

  const appliedParts = [];
  const merged = { ...data };
  if (isFullRefresh) {
    Object.entries(result).forEach(([key, value]) => {
      const latestApplied = latestAppliedPartRefreshSequence.get(key) || 0;
      if (latestApplied > sequence) return;
      merged[key] = value;
      latestAppliedPartRefreshSequence.set(key, sequence);
      appliedParts.push(key);
    });
    latestAppliedFullRefreshSequence = Math.max(
      latestAppliedFullRefreshSequence,
      sequence,
    );
  } else {
    effectiveParts.forEach((part) => {
      if (!Object.prototype.hasOwnProperty.call(result, part)) return;
      const latestApplied = latestAppliedPartRefreshSequence.get(part) || 0;
      if (latestApplied > sequence) return;
      merged[part] = result[part];
      latestAppliedPartRefreshSequence.set(part, sequence);
      appliedParts.push(part);
    });
  }

  if (!appliedParts.length) return data;
  data = merged;

  if (typeof clearTapAssign === "function") clearTapAssign();
  const lessonOnlyRefresh =
    appliedParts.includes("lessons") &&
    appliedParts.every((part) => ["lessons", "schedule_validation"].includes(part));
  if (lessonOnlyRefresh) {
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
    button.innerHTML = original;
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
    if (constraintSaveInFlight || globalSaveInFlight) {
      showToast("Đang lưu ràng buộc. Vui lòng chờ hoàn tất.", "info", 2400);
      syncMobileNavSelect(current);
      return false;
    }
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
    tabOld.style.transition = "";

    tabNew.style.transform = "";
    tabNew.style.opacity = "";
    tabNew.style.filter = "";
    tabNew.style.transition = "";

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
  const canEdit = ["department", "subject", "teacher", "grade", "class"].includes(type);
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

  if (type !== "assignment") {
    const confirmed = await confirmAction(
      `Xóa ${ids.length} mục đã chọn? Mục đang được sử dụng sẽ được giữ lại.`,
      { confirmText: `Xóa ${ids.length} mục` },
    );
    if (!confirmed) return;
  }

  setInlineActionState(button, "loading", {
    idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
    loading: type === "assignment" ? "Đang kiểm tra..." : "Đang xóa...",
  });

  try {
    let confirmation = null;
    for (let attemptIndex = 0; attemptIndex < 3; attemptIndex++) {
      const body = { type, ids, ...(confirmation || {}) };
      const r = await fetch(`/api/projects/${PROJECT_ID}/entities/bulk`, {
        method: "DELETE",
        headers: operationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      });
      const result = await readApiResponse(r);

      if (type === "assignment" && !r.ok && result?.requires_confirmation) {
        const confirmed = await confirmAction(
          result.message || `Xóa ${ids.length} phân công đã chọn?`,
          {
            title: "Xác nhận xóa phân công",
            confirmText: `Xóa ${Number(result.assignment_count || ids.length)} phân công`,
          },
        );
        if (!confirmed) {
          setInlineActionState(button, "idle", {
            idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
          });
          return;
        }
        confirmation = {
          confirm_assignment_cascade: true,
          confirmed_lesson_ids: Array.isArray(result.lesson_ids) ? result.lesson_ids : [],
          confirmed_fixed_lesson_ids: Array.isArray(result.fixed_lesson_ids)
            ? result.fixed_lesson_ids
            : [],
        };
        setInlineActionState(button, "loading", {
          idle: button.dataset.actionIdleLabel || "Xóa đã chọn",
          loading: "Đang xóa...",
        });
        continue;
      }

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
      return;
    }
    throw new Error("Dữ liệu lịch thay đổi trong lúc xác nhận. Hãy thử xóa lại.");
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
  const assignmentsByClass = new Map();
  assignments.forEach((item) => {
    const key = Number(item.class_id);
    if (!assignmentsByClass.has(key)) assignmentsByClass.set(key, []);
    assignmentsByClass.get(key).push(item);
  });
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
      grade = grades.find((item) => item.id === gradeId),
      gradeRequirements = requirementsByGrade.get(gradeId) || [];
    // Không có chương trình chuẩn cho khối => không thể kết luận môn nào là dư.
    if (!gradeRequirements.length) continue;
    const requiredSubjectIds = new Set(
      gradeRequirements.map((item) => Number(item.subject_id)),
    );
    for (const requirement of gradeRequirements) {
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
    for (const assignment of assignmentsByClass.get(schoolClass.id) || []) {
      if (requiredSubjectIds.has(Number(assignment.subject_id))) continue;
      const subject = subjects.find((item) => item.id === assignment.subject_id);
      result.push({
        issue_type: "extra",
        assignment_id: assignment.id,
        assigned_teacher_id: assignment.teacher_id,
        assigned_teacher_name: assignment.teacher_name || "",
        class_id: schoolClass.id,
        class_name: schoolClass.name,
        subject_id: assignment.subject_id,
        subject_name: subject?.name || assignment.subject_name || "?",
        grade_id: gradeId,
        grade_name: grade?.name || "?",
        assigned_periods: assignment.periods_per_week,
        assigned_mode: assignment.block_mode || "free",
      });
    }
  }
  return result.sort(
    (a, b) =>
      String(a.class_name).localeCompare(String(b.class_name), "vi") ||
      String(a.subject_name).localeCompare(String(b.subject_name), "vi") ||
      String(a.issue_type).localeCompare(String(b.issue_type)),
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
    extra = issues.filter((item) => item.issue_type === "extra"),
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
  if (extra.length)
    parts.push(`<b>${extra.length}</b> phân công môn không thuộc chương trình khối`);
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
          (item.issue_type === "mismatch" || item.issue_type === "extra") &&
          Number(item.assigned_teacher_id) === state.teacherId,
      );
    }
    if (!rows.length)
      return '<div class="assignment-filter-empty">Không có cặp lớp–môn nào lệch chương trình với bộ lọc hiện tại.</div>';
    return `<table class="data-table"><thead><tr><th>Lớp</th><th>Khối</th><th>Môn</th><th>Giáo viên hiện tại</th><th>Chương trình chuẩn</th><th>Trạng thái</th><th></th></tr></thead><tbody>${rows
      .map((item) => {
        if (item.issue_type === "extra") {
          const current = `${item.assigned_periods} tiết/tuần · ${describeBlockMode(item.assigned_mode, item.assigned_periods)}`;
          return `<tr><td><b>${esc(item.class_name)}</b></td><td>${esc(item.grade_name)}</td><td>${esc(item.subject_name)}</td><td>${esc(item.assigned_teacher_name || "—")}</td><td>Không thuộc chương trình khối</td><td><span class="assignment-gap-badge">Môn dư: ${esc(current)}</span></td><td><button class="danger-link" onclick="delEntity('assignment',${item.assignment_id},this)">Xóa phân công</button></td></tr>`;
        }
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
