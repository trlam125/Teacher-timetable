"use strict";
function scheduleAuditAiIsEnabled() {
  return $("#scheduleAuditAiButton")?.dataset?.enabled === "1";
}

function handleScheduleAuditSourceScroll() {
  if (
    scheduleAuditBottomScrollSyncing ||
    !scheduleAuditBottomScroller ||
    !scheduleAuditBottomScrollerSource
  )
    return;
  scheduleAuditBottomScrollSyncing = true;
  scheduleAuditBottomScroller.scrollLeft =
    scheduleAuditBottomScrollerSource.scrollLeft;
  scheduleAuditBottomScrollSyncing = false;
}

function ensureScheduleAuditBottomScroller() {
  if (scheduleAuditBottomScroller) return scheduleAuditBottomScroller;
  const scroller = document.createElement("div");
  scroller.className = "schedule-view-bottom-scrollbar";
  scroller.hidden = true;
  scroller.setAttribute("aria-label", "Thanh cuộn ngang thời khóa biểu");
  const inner = document.createElement("div");
  inner.className = "schedule-view-bottom-scrollbar-inner";
  scroller.appendChild(inner);
  scroller.addEventListener("scroll", () => {
    if (
      scheduleAuditBottomScrollSyncing ||
      !scheduleAuditBottomScrollerSource
    )
      return;
    scheduleAuditBottomScrollSyncing = true;
    scheduleAuditBottomScrollerSource.scrollLeft = scroller.scrollLeft;
    scheduleAuditBottomScrollSyncing = false;
  });
  document.body.appendChild(scroller);
  scheduleAuditBottomScroller = scroller;
  scheduleAuditBottomScrollerInner = inner;
  return scroller;
}

function hideScheduleAuditBottomScroller() {
  if (scheduleAuditBottomScroller) scheduleAuditBottomScroller.hidden = true;
  if (scheduleAuditBottomScrollerSource) {
    scheduleAuditBottomScrollerSource.removeEventListener(
      "scroll",
      handleScheduleAuditSourceScroll,
    );
  }
  scheduleAuditBottomScrollerSource = null;
}

function syncScheduleAuditBottomScroller() {
  const panel = $("#scheduleAuditView-timetable"),
    wrap = panel?.querySelector(".schedule-view-table-wrap");
  if (
    !scheduleAuditTableExpanded ||
    scheduleAuditActiveView !== "timetable" ||
    !panel ||
    panel.hidden ||
    !wrap ||
    wrap.scrollWidth <= wrap.clientWidth + 1
  ) {
    hideScheduleAuditBottomScroller();
    return;
  }

  const scroller = ensureScheduleAuditBottomScroller();
  if (scheduleAuditBottomScrollerSource !== wrap) {
    if (scheduleAuditBottomScrollerSource)
      scheduleAuditBottomScrollerSource.removeEventListener(
        "scroll",
        handleScheduleAuditSourceScroll,
      );
    scheduleAuditBottomScrollerSource = wrap;
    wrap.addEventListener("scroll", handleScheduleAuditSourceScroll, {
      passive: true,
    });
  }

  const rect = wrap.getBoundingClientRect(),
    left = Math.max(0, rect.left),
    right = Math.min(window.innerWidth, rect.right),
    width = Math.max(0, right - left);
  if (width < 80) {
    hideScheduleAuditBottomScroller();
    return;
  }

  scroller.style.left = `${left}px`;
  scroller.style.width = `${width}px`;
  scheduleAuditBottomScrollerInner.style.width = `${wrap.scrollWidth}px`;
  scroller.hidden = false;
  scroller.scrollLeft = wrap.scrollLeft;
}

function setScheduleAuditTableExpanded(expanded) {
  scheduleAuditTableExpanded = !!expanded;
  const panel = $("#scheduleAuditView-timetable"),
    wrap = panel?.querySelector(".schedule-view-table-wrap"),
    table = panel?.querySelector(".schedule-view-table"),
    button = panel?.querySelector("[data-schedule-size-toggle]");

  wrap?.classList.toggle(
    "schedule-view-table-wrap--expanded",
    scheduleAuditTableExpanded,
  );
  table?.classList.toggle(
    "schedule-view-table--expanded",
    scheduleAuditTableExpanded,
  );

  if (button) {
    button.classList.toggle("active", scheduleAuditTableExpanded);
    button.setAttribute(
      "aria-pressed",
      scheduleAuditTableExpanded ? "true" : "false",
    );
    button.setAttribute(
      "title",
      scheduleAuditTableExpanded
        ? "Thu thời khóa biểu vừa màn hình"
        : "Phóng to thời khóa biểu và bật thanh kéo ngang",
    );
    button.innerHTML = scheduleAuditTableExpanded
      ? '<span aria-hidden="true">↙</span><span>Vừa màn hình</span>'
      : '<span aria-hidden="true">⛶</span><span>Phóng to</span>';
  }

  if (!scheduleAuditTableExpanded && wrap) wrap.scrollLeft = 0;
  requestAnimationFrame(syncScheduleAuditBottomScroller);
}

function toggleScheduleAuditTableSize() {
  setScheduleAuditTableExpanded(!scheduleAuditTableExpanded);
}

