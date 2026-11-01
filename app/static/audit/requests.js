"use strict";
async function runScheduleAudit() {
  weeklyCatalogPromptCancel?.();
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
      renderScheduleAuditError(auditErrorMessage(result, response.status));
      return;
    }
    scheduleAuditManualEdits = 0;
    resetScheduleAuditWorkloadLimits();
    scheduleAuditLastReport = result;
    renderScheduleAudit(result, null);
    try {
      await restoreSavedWeeklyLimits(result, runId);
      if (runId === scheduleAuditRunId && result === scheduleAuditLastReport)
        renderScheduleAudit(result, null);
    } catch (loadError) {
      if (runId === scheduleAuditRunId && result === scheduleAuditLastReport) {
        initScheduleAuditWorkloadLimits(result);
        scheduleAuditWorkloadError = loadError.message || "Không thể tải định mức đã lưu.";
        scheduleAuditLimitsNotice = "Không thể xác minh dữ liệu đã lưu. Chưa thay thế hoặc xóa ngưỡng nào.";
        renderScheduleAudit(result, null);
      }
    }
  } catch (error) {
    if (runId === scheduleAuditRunId) {
      scheduleAuditLastReport = null;
      renderScheduleAuditError(
        "Không thể kết nối để kiểm tra thời khóa biểu. Hãy kiểm tra mạng và thử lại.",
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
      "Chức năng phân tích bằng AI hiện chưa sẵn sàng. Vui lòng liên hệ người quản lý.",
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
        auditErrorMessage(result, response.status, "Chưa thể phân tích bằng AI. Hãy thử lại sau."),
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
        "Không thể kết nối tới chức năng phân tích AI. Hãy thử lại sau.",
      );
  } finally {
    if (runId === scheduleAuditAiRunId && button) {
      button.disabled = false;
      button.classList.remove("is-loading");
      button.textContent = "✦ Phân tích lại bằng AI";
    }
  }
}

