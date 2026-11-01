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
    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        detail: friendlyRequestError(response.status),
      };
    }
    const invalid = new Error(
      "Không đọc được kết quả vừa nhận. Hãy tải lại trang và thử lại.",
    );
    invalid.isInvalidServerResponse = true;
    invalid.cause = error;
    throw invalid;
  }
}
// Hiển thị nguyên nhân có thể xác định; mã tra cứu chỉ giữ trong nhật ký máy chủ.
function friendlyRequestError(status) {
  if (status === 401) return "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.";
  if (status === 403) return "Bạn không có quyền thực hiện thao tác này.";
  if (status === 404) return "Không tìm thấy thông tin cần xử lý. Hãy tải lại trang.";
  if (status === 409) return "Thông tin đã thay đổi hoặc bị trùng. Hãy kiểm tra rồi thử lại.";
  if (status === 413) return "Tệp quá lớn. Hãy chọn tệp nhỏ hơn và thử lại.";
  if (status === 422 || status === 400) return "Thông tin chưa hợp lệ. Hãy kiểm tra các ô đã nhập.";
  if (status === 429) return "Bạn thao tác quá nhanh. Hãy thử lại sau ít phút.";
  if (status === 503) return "Hệ thống đang tạm gián đoạn. Hãy thử lại sau ít phút.";
  return status >= 500
    ? "Hệ thống gặp sự cố nên chưa thể hoàn tất. Hãy tải lại trang để kiểm tra dữ liệu rồi thử lại."
    : "Không thực hiện được thao tác. Hãy kiểm tra thông tin rồi thử lại.";
}
function friendlyServerDetail(value, status = 500, reference = "") {
  const message = String(value || "").trim();
  // Không đưa lỗi lập trình hoặc thông tin máy chủ lên giao diện người dùng.
  const internalPattern = /(?:Traceback|SQLAlchemy|psycopg|ProgrammingError|IntegrityError|OperationalError|GEMINI_API_KEY|\bHTTP\s*\d{3}\b|\bJSON\b|\bUvicorn\b|<html|database_schema|database_integrity|database_unavailable)/i;
  const visible = !message || internalPattern.test(message)
    ? friendlyRequestError(status)
    : message;
  return visible.replace(/\s*Mã hỗ trợ:\s*[A-Fa-f0-9]{6,32}\.?/g, "").trim();
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
      const readableMessage = /field required/i.test(message)
        ? "Không được để trống."
        : /valid (?:integer|number)/i.test(message)
          ? "Hãy nhập một số hợp lệ."
          : /string_too_long|string should have at most/i.test(message)
            ? "Nội dung quá dài. Hãy nhập ngắn hơn."
            : message;
      const location = Array.isArray(detail.loc)
        ? detail.loc.filter((part) => !["body", "query", "path"].includes(String(part)))
        : [];
      const lastField = location.length ? String(location[location.length - 1]) : "";
      const readableFields = {
        name: "Tên", subject: "Môn", subject_id: "Môn", grade: "Khối",
        class_id: "Lớp", class_name: "Lớp", teacher_id: "Giáo viên",
        teacher: "Giáo viên", periods: "Số tiết", periods_per_week: "Tiết/tuần",
        email: "Email", password: "Mật khẩu",
      };
      const field = readableFields[lastField] || lastField.replace(/_/g, " ");
      return field ? `${field}: ${readableMessage}` : readableMessage;
    }
    return "";
  }
  return String(detail).trim();
}
function apiErrorMessage(payload, fallback) {
  if (payload && typeof payload === "object") {
    const message = formatApiDetail(payload.message);
    const detail = formatApiDetail(payload.detail);
    const error = formatApiDetail(payload.error);
    if (message || detail || error)
      return friendlyServerDetail(message || detail || error, payload.status || 500, payload.error_id || "");
  } else {
    const message = formatApiDetail(payload);
    if (message) return friendlyServerDetail(message);
  }
  return fallback;
}
function requestFailureMessage(error, fallback = "Kết nối bị gián đoạn. Hãy kiểm tra mạng rồi thử lại.") {
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
          "Chưa kiểm tra được toàn bộ tiết học chịu ảnh hưởng. Hãy tải lại trang trước khi tiếp tục.",
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

