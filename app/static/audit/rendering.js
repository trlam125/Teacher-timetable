"use strict";
function renderScheduleAuditTable(report, ai = null) {
  const viewer = report.viewer || {},
    classes = viewer.classes || [],
    cells = viewer.cells || [];
  if (!classes.length || !cells.length)
    return '<div class="empty-state">Không có đủ dữ liệu để dựng bảng thời khóa biểu.</div>';
  const byCoordinate = new Map(),
    aiMap = scheduleAuditAiMap(ai);
  cells.forEach((item) => {
    const key = `${Number(item.slot)}:${Number(item.class_id)}`;
    if (!byCoordinate.has(key)) byCoordinate.set(key, []);
    byCoordinate.get(key).push(item);
  });
  const totalSlots = Math.max(
    0,
    Number(viewer.days || 0) *
    Number(viewer.sessions || 0) *
    Number(viewer.periods || 0),
  );
  const slots = totalSlots
    ? Array.from({ length: totalSlots }, (_, index) => index)
    : [...new Set(cells.map((item) => Number(item.slot)))].sort(
      (a, b) => a - b,
    );
  let previousDay = -1,
    previousSession = -1;
  let rows = "";
  for (const slot of slots) {
    const part = scheduleAuditSlotParts(slot, viewer),
      newDay = part.day !== previousDay,
      newSession = newDay || part.session !== previousSession;
    rows += `<tr class="${newDay ? "schedule-view-new-day " : ""}${newSession ? "schedule-view-new-session" : ""}">`;
    rows += `<th class="schedule-view-meta day">${newDay ? esc(scheduleAuditDayName(part.day)) : ""}</th>`;
    rows += `<th class="schedule-view-meta session">${newSession ? esc(scheduleAuditSessionName(part.session, viewer.sessions)) : ""}</th>`;
    rows += `<th class="schedule-view-meta period">${part.period}</th>`;
    for (const cls of classes) {
      const key = `${slot}:${Number(cls.id)}`;
      rows += scheduleAuditCellHtml(
        byCoordinate.get(key) || [],
        aiMap.get(key) || [],
      );
    }
    rows += "</tr>";
    previousDay = part.day;
    previousSession = part.session;
  }
  const bulkTeacherChecked = scheduleAuditBulkTeacherRename ? " checked" : "";
  const densityClass = classes.length >= 14
    ? " schedule-view-table--dense"
    : classes.length >= 9
      ? " schedule-view-table--compact"
      : "";
  const expandedClass = scheduleAuditTableExpanded
    ? " schedule-view-table--expanded"
    : "";
  const expandedWrapClass = scheduleAuditTableExpanded
    ? " schedule-view-table-wrap--expanded"
    : "";
  const sizeButton = scheduleAuditTableExpanded
    ? '<button type="button" class="schedule-view-size-toggle active" data-schedule-size-toggle aria-pressed="true" title="Thu thời khóa biểu vừa màn hình" onclick="toggleScheduleAuditTableSize()"><span aria-hidden="true">↙</span><span>Vừa màn hình</span></button>'
    : '<button type="button" class="schedule-view-size-toggle" data-schedule-size-toggle aria-pressed="false" title="Phóng to thời khóa biểu và bật thanh kéo ngang" onclick="toggleScheduleAuditTableSize()"><span aria-hidden="true">⛶</span><span>Phóng to</span></button>';
  return `<div class="schedule-view-edit-hint"><span class="schedule-view-edit-icon">✎</span><div class="schedule-view-edit-copy"><b>Có thể sửa trực tiếp</b><small>Bấm vào <strong>tên môn</strong> hoặc <strong>tên giáo viên</strong> trong từng ô. Nhấn Enter hoặc bấm ra ngoài để lưu, Esc để hủy. Tên môn trùng vẫn đổi đồng bộ; tên giáo viên chỉ đổi hàng loạt khi bật công tắc.</small></div><div class="schedule-view-toolbar">${sizeButton}<label class="schedule-view-bulk-toggle" title="Bật để đổi tất cả giáo viên có cùng tên"><input type="checkbox"${bulkTeacherChecked} onchange="setScheduleAuditBulkTeacherRename(this.checked)"><span class="schedule-view-switch" aria-hidden="true"><i></i></span><span class="schedule-view-bulk-toggle-text">Đổi hàng loạt tên GV trùng</span></label></div></div><div class="schedule-view-table-wrap${expandedWrapClass}"><table class="schedule-view-table${densityClass}${expandedClass}"><thead><tr><th class="schedule-view-meta day">Thứ</th><th class="schedule-view-meta session">Buổi</th><th class="schedule-view-meta period">Tiết</th>${classes.map((cls) => `<th class="schedule-view-class">${esc(cls.name)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function scheduleAuditAlphabetCompare(a, b) {
  return String(a || "").localeCompare(String(b || ""), "vi", {
    sensitivity: "base",
    numeric: true,
  });
}
function scheduleAuditBreakdownHtml(items, emptyLabel = "Không có dữ liệu") {
  if (!items?.length)
    return `<span class="schedule-stat-empty">${esc(emptyLabel)}</span>`;
  const sortedItems = [...items].sort((a, b) =>
    scheduleAuditAlphabetCompare(a?.name, b?.name),
  );
  return `<div class="schedule-stat-breakdown">${sortedItems.map((item) => `<span>${esc(item.name)} <b>${Number(item.lessons || 0)}</b></span>`).join("")}</div>`;
}
function scheduleAuditStatsOverview(statistics) {
  const overview = statistics?.overview || {};
  const leader = (item, fallback = "—") =>
    item?.name
      ? `<b>${esc(item.name)}</b><span>${Number(item.lessons || 0)} tiết</span>`
      : `<b>${fallback}</b><span>Chưa có dữ liệu</span>`;
  return `
    <div class="schedule-stat-cards">
      <article><span>Tổng số tiết</span><b>${Number(overview.total_lessons || 0)}</b></article>
      <article><span>Giáo viên</span><b>${Number(overview.total_teachers || 0)}</b></article>
      <article><span>Môn học</span><b>${Number(overview.total_subjects || 0)}</b></article>
      <article><span>Lớp học</span><b>${Number(overview.total_classes || 0)}</b></article>
    </div>
    <div class="schedule-stat-highlights">
      <article><small>Giáo viên dạy nhiều nhất</small>${leader(overview.busiest_teacher)}</article>
      <article><small>Môn có nhiều tiết nhất</small>${leader(overview.largest_subject)}</article>
      <article><small>Lớp có nhiều tiết nhất</small>${leader(overview.busiest_class)}</article>
      <article><small>Trung bình / giáo viên</small><b>${Number(overview.avg_lessons_per_teacher || 0).toLocaleString("vi-VN", { maximumFractionDigits: 2 })} tiết</b><span>TB / lớp: ${Number(overview.avg_lessons_per_class || 0).toLocaleString("vi-VN", { maximumFractionDigits: 2 })} tiết</span></article>
    </div>`;
}
function scheduleAuditStatsTable(rows, type) {
  const config = {
    teachers: {
      title: "Giáo viên",
      first: "Môn giảng dạy",
      second: "Lớp phụ trách",
      firstKey: "subjects",
      secondKey: "classes",
      search: "Tìm giáo viên…",
    },
    subjects: {
      title: "Môn học",
      first: "Giáo viên",
      second: "Lớp học",
      firstKey: "teachers",
      secondKey: "classes",
      search: "Tìm môn học…",
    },
    classes: {
      title: "Lớp học",
      first: "Môn học",
      second: "Giáo viên",
      firstKey: "subjects",
      secondKey: "teachers",
      search: "Tìm lớp học…",
    },
  }[type];
  if (!config) return "";
  const sortedRows = [...(rows || [])].sort((a, b) =>
    scheduleAuditAlphabetCompare(a?.name, b?.name),
  );
  const body = sortedRows
    .map(
      (item) =>
        `<tr data-stat-text="${esc(String(item.name || "").toLocaleLowerCase("vi-VN"))}"><td><b>${esc(item.name || "—")}</b></td><td class="schedule-stat-total">${Number(item.total_lessons || 0)}</td><td>${scheduleAuditBreakdownHtml(item[config.firstKey])}</td><td>${scheduleAuditBreakdownHtml(item[config.secondKey])}</td></tr>`,
    )
    .join("");
  return `<div class="schedule-stat-toolbar"><div><b>Thống kê theo ${esc(config.title.toLocaleLowerCase("vi-VN"))}</b><small>${Number((rows || []).length)} mục</small></div><input type="search" placeholder="${esc(config.search)}" oninput="filterScheduleAuditStats('${type}',this.value)" aria-label="${esc(config.search)}"></div>
    <div class="schedule-stat-table-wrap"><table class="schedule-stat-table"><thead><tr><th>${esc(config.title)}</th><th>Tổng tiết</th><th>${esc(config.first)}</th><th>${esc(config.second)}</th></tr></thead><tbody>${body || `<tr><td colspan="4" class="schedule-stat-none">Chưa có dữ liệu thống kê.</td></tr>`}</tbody></table></div>`;
}
function renderScheduleAuditStatistics(report) {
  const statistics = report?.statistics || {
    overview: {},
    teachers: [],
    subjects: [],
    classes: [],
  };
  return `
    <section id="scheduleAuditView-overview" class="schedule-audit-view-panel" data-audit-panel="overview" hidden>${scheduleAuditStatsOverview(statistics)}</section>
    <section id="scheduleAuditView-teachers" class="schedule-audit-view-panel" data-audit-panel="teachers" hidden>${scheduleAuditStatsTable(statistics.teachers, "teachers")}</section>
    <section id="scheduleAuditView-subjects" class="schedule-audit-view-panel" data-audit-panel="subjects" hidden>${scheduleAuditStatsTable(statistics.subjects, "subjects")}</section>
    <section id="scheduleAuditView-classes" class="schedule-audit-view-panel" data-audit-panel="classes" hidden>${scheduleAuditStatsTable(statistics.classes, "classes")}</section>`;
}
function switchScheduleAuditView(view) {
  const allowed = new Set([
    "timetable",
    "overview",
    "teachers",
    "subjects",
    "classes",
  ]);
  scheduleAuditActiveView = allowed.has(view) ? view : "timetable";
  document.querySelectorAll("[data-audit-view]").forEach((button) => {
    const active = button.dataset.auditView === scheduleAuditActiveView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-audit-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.auditPanel !== scheduleAuditActiveView;
  });
  requestAnimationFrame(syncScheduleAuditBottomScroller);
}
function filterScheduleAuditStats(type, query) {
  const normalized = String(query || "")
    .trim()
    .toLocaleLowerCase("vi-VN");
  document
    .querySelectorAll(`#scheduleAuditView-${type} tbody tr[data-stat-text]`)
    .forEach((row) => {
      row.hidden =
        !!normalized &&
        !String(row.dataset.statText || "").includes(normalized);
    });
}
function renderScheduleAuditDataIssues(issues) {
  if (!issues?.length) return "";
  return `<div class="schedule-audit-inline-issues"><div class="schedule-audit-group-head"><h3>Cảnh báo/lỗi dữ liệu cần xem lại</h3><span>${issues.length}</span></div><div class="schedule-audit-issue-list">${issues
    .map((issue) => {
      const severity = issue.severity === "error" ? "error" : "warning";
      const severityLabel = severity === "error" ? "Lỗi" : "Cảnh báo";
      const location = [issue.slot_label, issue.entity]
        .filter(Boolean)
        .join(" · ");
      return `<article class="schedule-audit-issue ${severity}"><div class="schedule-audit-issue-mark">${severity === "error" ? "!" : "⚠"}</div><div><div class="schedule-audit-issue-title"><b>${esc(issue.title || "Cần xem lại")}</b><span>${severityLabel}</span></div>${issue.detail ? `<p>${esc(issue.detail)}</p>` : ""}${location ? `<small><b>Vị trí:</b> ${esc(location)}</small>` : ""}${issue.source ? `<small><b>Nguồn:</b> ${esc(issue.source)}</small>` : ""}</div></article>`;
    })
    .join("")}</div></div>`;
}

function renderScheduleAudit(report, ai = scheduleAuditAiAnalysis) {
  const box = $("#scheduleAuditResult");
  if (!box) return;
  const summary = report.summary || {},
    viewer = report.viewer || {},
    issues = report.issues || [];
  const collisionIssues = issues.filter((item) =>
    ["teacher_collision", "class_collision", "room_collision"].includes(
      item.code,
    ),
  );
  const nonCellIssues = issues.filter(
    (item) =>
      !["teacher_collision", "class_collision", "room_collision"].includes(
        item.code,
      ),
  );
  const conflicts = Number(summary.collisions || collisionIssues.length),
    affected = Number(viewer.conflict_cells || 0);
  const hasConflict = conflicts > 0,
    hasOtherIssues = nonCellIssues.length > 0,
    aiMarked = Number(ai?.summary?.marked_cells || 0);
  const statusTitle = hasConflict
    ? `Phát hiện ${conflicts} xung đột trong thời khóa biểu`
    : hasOtherIssues
      ? `Không có ô bị trùng, nhưng còn ${nonCellIssues.length} cảnh báo/lỗi dữ liệu`
      : "Không phát hiện ô bị trùng";
  box.innerHTML = `
    <div class="schedule-audit-view-head ${hasConflict || hasOtherIssues ? "has-error" : "clean"}">
      <div class="schedule-audit-view-summary">
        <span class="schedule-audit-status-icon">${hasConflict || hasOtherIssues ? "!" : "✓"}</span>
        <div><h2>${statusTitle}</h2><p>${esc(report.filename || "File")} · Đã đọc ${Number(summary.recognized_lessons || 0)} tiết · ${Number(summary.classes || 0)} lớp · ${Number(summary.teachers || 0)} giáo viên.</p></div>
      </div>
      <div class="schedule-audit-view-legend"><span class="legend-conflict"></span><b>Đỏ = lỗi rule</b>${hasConflict ? `<small>${affected} ô</small>` : ""}${ai ? `<span class="legend-ai-warning"></span><b>Cam/vàng = AI</b><small>${aiMarked} ô</small>` : ""}</div>
    </div>
    ${renderScheduleAuditDataIssues(nonCellIssues)}
    <div class="schedule-audit-tabs" role="tablist" aria-label="Chế độ xem thời khóa biểu">
      <button type="button" data-audit-view="timetable" onclick="switchScheduleAuditView('timetable')">Thời khóa biểu</button>
      <button type="button" data-audit-view="overview" onclick="switchScheduleAuditView('overview')">Tổng quan</button>
      <button type="button" data-audit-view="teachers" onclick="switchScheduleAuditView('teachers')">Giáo viên</button>
      <button type="button" data-audit-view="subjects" onclick="switchScheduleAuditView('subjects')">Môn học</button>
      <button type="button" data-audit-view="classes" onclick="switchScheduleAuditView('classes')">Lớp học</button>
    </div>
    <section id="scheduleAuditView-timetable" class="schedule-audit-view-panel" data-audit-panel="timetable">${renderScheduleAuditTable(report, ai)}</section>
    ${renderScheduleAuditStatistics(report)}`;
  switchScheduleAuditView(scheduleAuditActiveView);
}
function renderScheduleAuditError(message) {
  const box = $("#scheduleAuditResult");
  if (!box) return;
  hideScheduleAuditBottomScroller();
  box.innerHTML = `<div class="schedule-audit-report-head has-error"><div><span class="schedule-audit-status-icon">!</span></div><div><h2>Không thể kiểm tra file</h2><p>${esc(message || "Đã xảy ra lỗi khi đọc thời khóa biểu.")}</p></div></div>`;
}
function scheduleAuditCellLocation(cellKey, report) {
  const [slotRaw, classRaw] = String(cellKey || "").split(":"),
    slot = Number(slotRaw),
    classId = Number(classRaw),
    viewer = report?.viewer || {};
  if (!Number.isFinite(slot) || !Number.isFinite(classId)) return "";
  const cls = (viewer.classes || []).find(
    (item) => Number(item.id) === classId,
  ),
    part = scheduleAuditSlotParts(slot, viewer),
    session = scheduleAuditSessionName(part.session, viewer.sessions);
  return [
    scheduleAuditDayName(part.day),
    session,
    `Tiết ${part.period}`,
    cls?.name || `Lớp ${classId}`,
  ]
    .filter(Boolean)
    .join(" · ");
}
function renderScheduleAuditAiLoading() {
  const box = $("#scheduleAuditAiResult");
  if (!box) return;
  box.hidden = false;
  box.innerHTML =
    '<div class="schedule-audit-ai-loading"><span></span><div><b>AI đang phân tích thời khóa biểu…</b><small>Rule thường vẫn giữ nguyên; AI chỉ bổ sung nhận xét.</small></div></div>';
}
function renderScheduleAuditAiError(message) {
  const box = $("#scheduleAuditAiResult");
  if (!box) return;
  box.hidden = false;
  box.innerHTML = `<div class="schedule-audit-ai-head error"><div><span class="schedule-audit-ai-icon">!</span></div><div><h2>AI chưa thể phân tích</h2><p>${esc(message || "Không thể kết nối tới AI.")}</p><small>Phần kiểm tra rule thường phía dưới vẫn sử dụng bình thường.</small></div></div>`;
}
function renderScheduleAuditAiResult(report, ai) {
  const box = $("#scheduleAuditAiResult");
  if (!box) return;
  const issues = ai?.issues || [],
    summary = ai?.summary || {},
    hasWarnings = Number(summary.warnings || 0) > 0;
  box.hidden = false;
  box.innerHTML = `
    <div class="schedule-audit-ai-head ${issues.length ? "has-findings" : "clean"}">
      <div><span class="schedule-audit-ai-icon">✦</span></div>
      <div class="schedule-audit-ai-copy"><div class="schedule-audit-ai-title-row"><h2>Phân tích bằng AI</h2></div><p>${esc(ai?.overview || "Đã phân tích thời khóa biểu.")}</p><small>AI là lớp kiểm tra bổ sung theo heuristic; lỗi rule cứng vẫn được ưu tiên.</small></div>
      <div class="schedule-audit-ai-counts"><b>${Number(summary.total || issues.length)}</b><span>điểm cần xem</span>${hasWarnings ? `<small>${Number(summary.warnings || 0)} cảnh báo</small>` : ""}</div>
    </div>
    ${issues.length
      ? `<div class="schedule-audit-ai-issues">${issues
        .map((issue) => {
          const locations = (issue.cell_keys || [])
            .map((key) => scheduleAuditCellLocation(key, report))
            .filter(Boolean);
          return `<article class="schedule-audit-ai-issue ${issue.severity === "warning" ? "warning" : "suggestion"}"><div class="schedule-audit-ai-issue-mark">${issue.severity === "warning" ? "!" : "✦"}</div><div><div class="schedule-audit-ai-issue-title"><b>${esc(issue.title || "Cần xem lại")}</b><span>${esc(scheduleAuditAiCategoryLabel(issue.category))}</span></div>${issue.message ? `<p>${esc(issue.message)}</p>` : ""}${issue.suggestion ? `<small><b>Gợi ý:</b> ${esc(issue.suggestion)}</small>` : ""}${locations.length ? `<div class="schedule-audit-ai-locations">${locations.map((location) => `<span>${esc(location)}</span>`).join("")}</div>` : '<div class="schedule-audit-ai-global">Nhận xét toàn cục</div>'}</div></article>`;
        })
        .join("")}</div>`
      : '<div class="schedule-audit-ai-empty">✓ AI không phát hiện bất thường đáng chú ý ngoài các kiểm tra rule hiện có.</div>'
    }`;
}
function renderScheduleAuditWifiLoader() {
  return `
    <div class="schedule-audit-loading">
      <div id="wifi-loader" class="wifi-loader">
        <svg class="circle-outer" viewBox="0 0 86 86">
          <circle class="back" cx="43" cy="43" r="40"></circle>
          <circle class="front" cx="43" cy="43" r="40"></circle>
          <circle class="new" cx="43" cy="43" r="40"></circle>
        </svg>
        <svg class="circle-middle" viewBox="0 0 60 60">
          <circle class="back" cx="30" cy="30" r="27"></circle>
          <circle class="front" cx="30" cy="30" r="27"></circle>
        </svg>
        <svg class="circle-inner" viewBox="0 0 34 34">
          <circle class="back" cx="17" cy="17" r="14"></circle>
          <circle class="front" cx="17" cy="17" r="14"></circle>
        </svg>
      </div>
    </div>
  `;
}
