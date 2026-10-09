"use strict";
function scheduleAuditFileValidationError(file) {
  if (!file) return "Hãy chọn file thời khóa biểu trước khi kiểm tra.";
  if (file.size > SCHEDULE_AUDIT_MAX_BYTES)
    return "File vượt quá giới hạn 15 MB.";
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!SCHEDULE_AUDIT_ALLOWED_EXTENSIONS.includes(ext))
    return "Định dạng chưa hỗ trợ. Dùng .xlsx, .xlsm, .xls, .docx, .csv hoặc .tsv.";
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
      : "Chưa chọn file";
  if (drop) {
    drop.classList.toggle("has-file", !!file);
    drop.setAttribute(
      "aria-label",
      file
        ? `${file.name} đã sẵn sàng. Bấm để chọn file khác.`
        : "Kéo thả file thời khóa biểu vào đây hoặc bấm để chọn file.",
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
  scheduleAuditAiAnalysis = null;
  const aiBox = $("#scheduleAuditAiResult");
  if (aiBox) {
    aiBox.hidden = true;
    aiBox.innerHTML = "";
  }
}
function clearScheduleAuditFile(resetResult = true) {
  scheduleAuditRunId += 1;
  scheduleAuditAiRunId += 1;
  scheduleAuditLastReport = null;
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
      '<div class="empty-state">Chọn một file thời khóa biểu để hiển thị và kiểm tra.</div>';
  hideScheduleAuditBottomScroller();
}
function selectScheduleAuditFile(file, { autoRun = true } = {}) {
  const error = scheduleAuditFileValidationError(file);
  if (error) {
    clearScheduleAuditFile(false);
    renderScheduleAuditError(error);
    return false;
  }
  scheduleAuditAiRunId += 1;
  scheduleAuditLastReport = null;
  scheduleAuditManualEdits = 0;
  scheduleAuditActiveView = "timetable";
  scheduleAuditTableExpanded = false;
  resetScheduleAuditAiResult();
  setScheduleAuditFile(file);
  if (autoRun) runScheduleAudit();
  return true;
}
