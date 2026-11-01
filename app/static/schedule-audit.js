"use strict";
const $ = (selector) => document.querySelector(selector);
async function readAuditResponse(response) {
  const raw = await response.text();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch (error) {
    if (!response.ok)
      return { detail: auditFriendlyError(response.status) };
    const invalid = new Error("Không đọc được kết quả kiểm tra. Hãy tải lại trang và thử lại.");
    invalid.cause = error;
    throw invalid;
  }
}
function auditFriendlyError(status) {
  if (status === 413) return "Tệp quá lớn. Hãy chọn tệp nhỏ hơn 15 MB.";
  if (status === 400 || status === 422) return "Không đọc được nội dung tệp. Hãy kiểm tra định dạng và thử lại.";
  if (status === 401) return "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.";
  if (status === 409) return "Dữ liệu đã thay đổi. Hãy kiểm tra rồi thử lại.";
  if (status >= 500) return "Hệ thống đang gặp sự cố khi kiểm tra. Hãy kiểm tra dữ liệu đã lưu và thử lại sau.";
  return "Không thể kiểm tra lúc này. Hãy thử lại.";
}
function auditErrorMessage(result, status, fallback) {
  const raw = result?.message || result?.detail || fallback || "";
  const text = typeof raw === "string" ? raw : "";
  const internal = /(?:Traceback|SQLAlchemy|psycopg|\bHTTP\s*\d{3}|\bJSON\b|\bUvicorn\b|GEMINI_API_KEY|<html)/i;
  const visible = !text || internal.test(text) ? auditFriendlyError(status) : text;
  return visible.replace(/\s*Mã hỗ trợ:\s*[A-Fa-f0-9]{6,32}\.?/g, "").trim();
}
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
      ch
      ],
  );
const operationHeaders = (extra) => ({
  "X-Skip-Operation-Status": "1",
  ...(extra || {}),
});

let scheduleAuditSelectedFile = null;
let scheduleAuditRunId = 0;
let scheduleAuditAiRunId = 0;
let scheduleAuditLastReport = null;
let scheduleAuditAiAnalysis = null;
let scheduleAuditActiveView = "timetable";
let scheduleAuditManualEdits = 0;
let scheduleAuditBulkTeacherRename = false;
let scheduleAuditBottomScroller = null;
let scheduleAuditBottomScrollerInner = null;
let scheduleAuditBottomScrollerSource = null;
let scheduleAuditBottomScrollSyncing = false;
let scheduleAuditTableExpanded = false;
const SCHEDULE_AUDIT_MAX_BYTES = 15 * 1024 * 1024;
const SCHEDULE_AUDIT_ALLOWED_EXTENSIONS = [
  "xlsx",
  "xlsm",
  "xls",
  "docx",
  "csv",
  "tsv",
];

