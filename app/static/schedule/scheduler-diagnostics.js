let schedulerDiagnosticReport = null;
let schedulerDiagnosticsInFlight = false;

function schedulerDiagnosticTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short", timeStyle: "medium", timeZone: "Asia/Ho_Chi_Minh",
  }).format(date);
}

function renderSchedulerDiagnostics(report) {
  const host = document.getElementById("schedulerDiagnosticsContent");
  if (!host) return;
  const pairs = (entries) => `<dl>${entries.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value ?? "—")}</dd>`).join("")}</dl>`;
  const yesNo = (value) => value == null ? "Chưa xác định" : value ? "Có" : "Không";
  const summary = report.summary || {};
  const latest = report.latest_run;
  const search = latest?.search || {};
  const outcome = latest?.outcome || {};
  const modes = { full: "Xếp từ lịch trống", missing: "Bổ sung phần thiếu", rebuild: "Xếp lại phần không cố định" };
  const statuses = { complete: "Đã xếp đủ", partial: "Còn thiếu tiết", rejected: "Kết quả bị từ chối", error: "Gặp sự cố" };
  const missing = report.unscheduled_assignments || [];
  host.innerHTML = `
    <div class="scheduler-diagnostic-grid">
      <article class="scheduler-diagnostic-card">
        <h2>Môi trường bộ xếp</h2>
        ${pairs([
          ["Phiên bản bộ xếp", report.scheduler_revision], ["Python", report.python_version],
          ["OR-Tools", report.ortools_version || "Chưa cài"],
          ["CP-SAT sẵn sàng", yesNo(report.cp_sat_available)], ["Lỗi tải CP-SAT", report.cp_sat_load_error || "Không có"],
          ["CPU hệ thống báo", report.cpu_count], ["Thời gian tìm mỗi lượt", `${report.search_budget_seconds} giây`],
        ])}
      </article>
      <article class="scheduler-diagnostic-card">
        <h2>Lịch hiện tại</h2>
        <p class="scheduler-diagnostic-summary">${esc(summary.message || "")}</p>
        ${pairs([
          ["Tiết đang xếp / yêu cầu", `${summary.scheduled_periods} / ${summary.required_periods}`],
          ["Tiết còn thiếu", summary.missing_periods], ["Phân công", summary.assignment_count],
          ["Tiết đã ghim", summary.locked_lessons], ["Khối có khóa lịch", summary.grades_with_locks],
          ["Giáo viên có tiết tránh", summary.teachers_with_avoid_slots], ["Lớp có tiết tránh riêng", summary.classes_with_avoid_slots],
        ])}
      </article>
    </div>
    <article class="scheduler-diagnostic-card">
      <h2>Lần chạy bộ xếp gần nhất</h2>
      ${latest ? `${pairs([
        ["Thời điểm ghi nhận", schedulerDiagnosticTime(latest.recorded_at)],
        ["Phiên bản lúc chạy", search.scheduler_revision], ["Chế độ", modes[search.mode] || search.mode],
        ["Bộ giải trả kết quả", search.solver], ["Thời gian chạy", search.elapsed_seconds == null ? "—" : `${search.elapsed_seconds} giây`],
        ["Số tiết trước lượt xếp", search.initial_lessons], ["Trạng thái", statuses[outcome.status] || outcome.status],
        ["Tiết lịch cũ dùng làm điểm xuất phát", search.reused_periods],
        ["Tiết trên lịch sau lượt xếp", outcome.scheduled], ["Tiết còn thiếu sau lượt xếp", outcome.unscheduled],
        ["Đã chứng minh số tiết xếp là nhiều nhất", yesNo(search.maximum_placed)],
        ["Đã chứng minh điểm tối ưu", yesNo(search.optimal)],
      ])}<p>${esc(outcome.message || "")}</p><p>Lịch hiện tại có thể đã được chỉnh sửa sau lần chạy này.</p>`
        : "<p>Chưa có báo cáo được lưu. Lần chạy bộ xếp tiếp theo sẽ được ghi nhận.</p>"}
    </article>
    <article class="scheduler-diagnostic-card">
      <h2>Phân công còn thiếu tiết</h2>
      ${missing.length ? missing.map((item) => `
        <div class="scheduler-diagnostic-issue">
          <h3>${esc(item.class_name)} · ${esc(item.subject_name)} · ${esc(item.teacher_name)}</h3>
          <p>Đã xếp ${esc(item.scheduled_periods)}/${esc(item.required_periods)} tiết; còn thiếu ${esc(item.missing_periods)} tiết.</p>
          <p>${esc(item.message)}</p>
          ${(item.candidate_slots || []).length ? `<ul class="scheduler-diagnostic-slots">${item.candidate_slots.map((candidate) => `<li><b>${esc(candidate.label)}${candidate.group_size > 1 ? ` · block ${esc(candidate.group_size)} tiết` : ""}</b>: ${esc(candidate.valid ? "Có thể xếp." : (candidate.reasons || []).join(" "))}</li>`).join("")}</ul>` : ""}
          ${item.omitted_candidate_count ? `<p>Còn ${esc(item.omitted_candidate_count)} vị trí khác; báo cáo hiển thị tối đa 8 vị trí cho mỗi phân công.</p>` : ""}
        </div>`).join("") : "<p>Không có tiết phân công còn thiếu.</p>"}
    </article>`;
}

async function loadSchedulerDiagnostics() {
  const section = document.getElementById("schedulerDiagnostics");
  if (!section || schedulerDiagnosticsInFlight) return;
  const status = document.getElementById("schedulerDiagnosticsStatus");
  const refreshButton = document.getElementById("schedulerDiagnosticsRefresh");
  const downloadButton = document.getElementById("schedulerDiagnosticsDownload");
  schedulerDiagnosticsInFlight = true;
  schedulerDiagnosticReport = null;
  section.setAttribute("aria-busy", "true");
  refreshButton.disabled = true;
  downloadButton.disabled = true;
  status.classList.remove("is-error");
  status.textContent = "Đang kiểm tra môi trường và lịch hiện tại...";
  document.getElementById("schedulerDiagnosticsContent").innerHTML = "";
  try {
    const response = await fetch(`/api/projects/${PROJECT_ID}/scheduler-diagnostics`, { cache: "no-store" });
    const report = await readApiResponse(response);
    if (!response.ok) throw new Error(apiErrorMessage(report, "Không thể tải báo cáo chẩn đoán."));
    if (!report?.summary || !Array.isArray(report.unscheduled_assignments)) throw new Error("Báo cáo chẩn đoán chưa đầy đủ. Hãy thử kiểm tra lại.");
    renderSchedulerDiagnostics(report);
    schedulerDiagnosticReport = report;
    downloadButton.disabled = false;
    status.textContent = `Đã kiểm tra lúc ${schedulerDiagnosticTime(report.checked_at)} (giờ Việt Nam).`;
  } catch (error) {
    status.classList.add("is-error");
    status.textContent = requestFailureMessage(error, "Không tải được báo cáo. Hãy kiểm tra lại.");
  } finally {
    schedulerDiagnosticsInFlight = false;
    refreshButton.disabled = false;
    section.removeAttribute("aria-busy");
  }
}

function downloadSchedulerDiagnostics() {
  if (!schedulerDiagnosticReport) return;
  const blob = new Blob([JSON.stringify(schedulerDiagnosticReport, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `chan-doan-bo-xep-${PROJECT_ID}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
