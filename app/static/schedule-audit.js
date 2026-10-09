"use strict";
const $ = (selector) => document.querySelector(selector);
async function readAuditResponse(response) {
  const raw = await response.text();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch (error) {
    const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
    if (!response.ok)
      return { detail: `Máy chủ trả về lỗi ${statusLabel} nhưng phản hồi không phải JSON hợp lệ.` };
    const invalid = new Error(`Phản hồi từ máy chủ không hợp lệ (${statusLabel}).`);
    invalid.cause = error;
    throw invalid;
  }
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

