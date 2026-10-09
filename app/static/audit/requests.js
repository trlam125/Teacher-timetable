"use strict";
async function runScheduleAudit() {
  const input = $("#scheduleAuditFile"),
    button = $("#scheduleAuditButton"),
    file = scheduleAuditSelectedFile || input?.files?.[0];
  const validationError = scheduleAuditFileValidationError(file);
  if (validationError) {
    renderScheduleAuditError(validationError);
    return;
  }
  scheduleAuditAiRunId += 1;
  resetScheduleAuditAiResult();
  const runId = ++scheduleAuditRunId,
    drop = $("#scheduleAuditDropzone");
  if (button) {
    button.disabled = true;
    button.textContent = "Đang phân tích…";
  }
  if (drop) drop.classList.add("is-analyzing");
  const box = $("#scheduleAuditResult");
  if (box) box.innerHTML = renderScheduleAuditWifiLoader();
  try {
    const form = new FormData();
    form.append("file", file, file.name);
    const response = await fetch("/api/schedule-audit", {
      method: "POST",
      headers: operationHeaders(),
      body: form,
    });
    const result = await readAuditResponse(response);
    if (runId !== scheduleAuditRunId) return;
    if (!response.ok || !result.ok) {
      scheduleAuditLastReport = null;
      renderScheduleAuditError(
        result.message ||
        result.detail ||
        `Máy chủ trả về lỗi ${response.status}.`,
      );
      return;
    }
    scheduleAuditManualEdits = 0;
    scheduleAuditLastReport = result;
    renderScheduleAudit(result, null);
  } catch (error) {
    if (runId === scheduleAuditRunId) {
      scheduleAuditLastReport = null;
      renderScheduleAuditError(
        error?.message || "Không thể kết nối tới máy chủ để kiểm tra file.",
      );
    }
  } finally {
    if (runId === scheduleAuditRunId) {
      if (button) {
        button.disabled = false;
        button.textContent = "Kiểm tra lại";
      }
      if (drop) drop.classList.remove("is-analyzing");
    }
  }
}
async function runScheduleAuditAI() {
  const input = $("#scheduleAuditFile"),
    button = $("#scheduleAuditAiButton"),
    file = scheduleAuditSelectedFile || input?.files?.[0];
  const validationError = scheduleAuditFileValidationError(file);
  if (validationError) {
    renderScheduleAuditAiError(validationError);
    return;
  }
  if (!scheduleAuditAiIsEnabled()) {
    renderScheduleAuditAiError(
      "Máy chủ chưa cấu hình GEMINI_API_KEY cho chức năng AI.",
    );
    return;
  }
  const runId = ++scheduleAuditAiRunId;
  if (button) {
    button.disabled = true;
    button.classList.add("is-loading");
    button.textContent = "✦ AI đang phân tích…";
  }
  renderScheduleAuditAiLoading();
  try {
    const form = new FormData();
    if (scheduleAuditLastReport && scheduleAuditManualEdits > 0) {
      form.append("report_json", JSON.stringify(scheduleAuditLastReport));
      form.append("file", file, file.name);
    } else form.append("file", file, file.name);
    const response = await fetch("/api/schedule-audit/ai", {
      method: "POST",
      headers: operationHeaders(),
      body: form,
    });
    const result = await readAuditResponse(response);
    if (runId !== scheduleAuditAiRunId) return;
    if (!response.ok || !result.ok) {
      renderScheduleAuditAiError(
        result.message || result.detail || `AI trả về lỗi ${response.status}.`,
      );
      return;
    }
    if (result.report) scheduleAuditLastReport = result.report;
    scheduleAuditAiAnalysis = result.ai || {
      overview: "",
      issues: [],
      summary: {},
    };
    if (scheduleAuditLastReport)
      renderScheduleAudit(scheduleAuditLastReport, scheduleAuditAiAnalysis);
    renderScheduleAuditAiResult(
      scheduleAuditLastReport,
      scheduleAuditAiAnalysis,
    );
  } catch (error) {
    if (runId === scheduleAuditAiRunId)
      renderScheduleAuditAiError(
        error?.message ||
        "Không thể kết nối tới AI để phân tích thời khóa biểu.",
      );
  } finally {
    if (runId === scheduleAuditAiRunId && button) {
      button.disabled = false;
      button.classList.remove("is-loading");
      button.textContent = "✦ Phân tích lại bằng AI";
    }
  }
}

