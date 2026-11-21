"use strict";
function scheduleAuditFileValidationError(file) {
  if (!file) return "Hãy chọn tệp thời khóa biểu trước khi kiểm tra.";
  if (file.size > SCHEDULE_AUDIT_MAX_BYTES)
    return "Tệp quá lớn (tối đa 15 MB). Hãy chọn tệp nhỏ hơn.";
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!SCHEDULE_AUDIT_ALLOWED_EXTENSIONS.includes(ext))
    return "Hãy chọn tệp Excel (.xlsx, .xlsm, .xls), Word (.docx), CSV hoặc TSV.";
  return "";
}
function setScheduleAuditFile(file) {
  scheduleAuditSelectedFile = file || null;
  const name = $("#scheduleAuditFileName"),
    drop = $("#scheduleAuditDropzone"),
    actions = $("#scheduleAuditFileActions"),
    button = $("#scheduleAuditButton"),
    aiButton = $("#scheduleAuditAiButton");
  if (name)
    name.textContent = file
      ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(file.size >= 1024 * 1024 ? 2 : 3)} MB`
      : "Chưa chọn tệp";
  if (drop) {
    drop.classList.toggle("has-file", !!file);
    drop.setAttribute(
      "aria-label",
      file
        ? `${file.name}. Bấm để chọn tệp khác.`
        : "Bấm để chọn tệp thời khóa biểu hoặc kéo thả vào đây.",
    );
  }
  if (actions) actions.hidden = !file;
  if (button && !button.disabled)
    button.textContent = file ? "Kiểm tra lại" : "Kiểm tra";
  if (aiButton && !aiButton.classList.contains("is-loading")) {
    aiButton.disabled = !scheduleAuditAiIsEnabled();
    aiButton.textContent = "✦ Phân tích bằng AI";
  }
}
function resetScheduleAuditAiResult() {
  // A response computed before a file/name edit must never restore old data.
  scheduleAuditAiRunId += 1;
  scheduleAuditAiAnalysis = null;
  const button = $("#scheduleAuditAiButton");
  if (button) {
    button.classList.remove("is-loading");
    button.disabled = !scheduleAuditAiIsEnabled();
    button.textContent = "✦ Phân tích bằng AI";
  }
  const aiBox = $("#scheduleAuditAiResult");
  if (aiBox) {
    aiBox.hidden = true;
    aiBox.innerHTML = "";
  }
}
function clearScheduleAuditFile(resetResult = true) {
  scheduleAuditRunId += 1;
  weeklyCatalogPromptCancel?.();
  scheduleAuditLastReport = null;
  resetScheduleAuditWorkloadLimits();
  scheduleAuditManualEdits = 0;
  scheduleAuditTableExpanded = false;
  resetScheduleAuditAiResult();
  const input = $("#scheduleAuditFile"),
    box = $("#scheduleAuditResult"),
    button = $("#scheduleAuditButton"),
    aiButton = $("#scheduleAuditAiButton"),
    drop = $("#scheduleAuditDropzone");
  if (input) input.value = "";
  setScheduleAuditFile(null);
  if (button) {
    button.disabled = false;
    button.textContent = "Kiểm tra";
  }
  if (aiButton) {
    aiButton.classList.remove("is-loading");
    aiButton.disabled = !scheduleAuditAiIsEnabled();
    aiButton.textContent = "✦ Phân tích bằng AI";
  }
  if (drop) drop.classList.remove("is-analyzing", "is-dragging");
  if (resetResult && box)
    box.innerHTML =
      '<div class="empty-state">Kết quả kiểm tra sẽ hiển thị tại đây.</div>';
  hideScheduleAuditBottomScroller();
}
function selectScheduleAuditFile(file, { autoRun = true } = {}) {
  if (scheduleAuditLimitsDirty && !window.confirm("Nhập tệp mới sẽ bỏ các thay đổi định mức chưa lưu. Tiếp tục?")) {
    const input = document.getElementById("scheduleAuditFile");
    if (input) input.value = "";
    return false;
  }
  const error = scheduleAuditFileValidationError(file);
  if (error) {
    clearScheduleAuditFile(false);
    renderScheduleAuditError(error);
    return false;
  }
  clearScheduleAuditFile();
  scheduleAuditActiveView = "timetable";
  setScheduleAuditFile(file);
  const formatGuide = $("#scheduleAuditFormatGuide");
  if (formatGuide) formatGuide.open = false;
  if (autoRun) runScheduleAudit();
  return true;
}
