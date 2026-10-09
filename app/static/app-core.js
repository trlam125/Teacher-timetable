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
  const send = async (
    confirmDisplacement = false,
    confirmedAffectedLessonIds = null,
  ) => {
    const response = await fetch(url, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        ...payload,
        confirm_displacement: confirmDisplacement,
        confirmed_affected_lesson_ids: confirmedAffectedLessonIds,
      }),
    });
    return { response, result: await readApiResponse(response) };
  };

  let confirmDisplacement = false;
  let confirmedAffectedLessonIds = null;
  for (let attemptIndex = 0; attemptIndex < 3; attemptIndex++) {
    const attempt = await send(
      confirmDisplacement,
      confirmedAffectedLessonIds,
    );
    if (!attempt.response.ok && attempt.result?.requires_confirmation) {
      const affected = Number(attempt.result.affected_lessons) || 0;
      const affectedLessonIds = Array.isArray(attempt.result.affected_lesson_ids)
        ? attempt.result.affected_lesson_ids
          .map(Number)
          .filter((id) => Number.isInteger(id) && id > 0)
        : [];
      if (affected > 0 && affectedLessonIds.length !== affected) {
        throw new Error(
          "Máy chủ không trả về đầy đủ danh sách tiết cần xác nhận. Hãy tải lại trang và thử lại.",
        );
      }
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
      confirmedAffectedLessonIds = affectedLessonIds;
      continue;
    }
    return { ...attempt, cancelled: false };
  }
  throw new Error("Lịch thay đổi liên tục trong lúc xác nhận. Hãy thử lưu lại.");
}

