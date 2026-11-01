// Scrollable containers can be replaced by renderAll() (assignment matrices,
// curriculum grid, timetable and entity tables). Remember their relative DOM
// paths inside the active tab so their scroll positions survive replacement.
function captureWorkspaceNestedScroll(tab) {
  if (!tab) return [];
  const result = [];
  for (const element of tab.querySelectorAll("*")) {
    const top = element.scrollTop;
    const left = element.scrollLeft;
    if (top <= 0 && left <= 0) continue;
    const path = [];
    let current = element;
    while (current && current !== tab) {
      const parent = current.parentElement;
      if (!parent) break;
      path.unshift(Array.prototype.indexOf.call(parent.children, current));
      current = parent;
    }
    if (current !== tab) continue;
    result.push({ path, tag: element.tagName, top, left });
  }
  return result;
}
function restoreWorkspaceNestedScroll(tab, saved) {
  if (!tab || !Array.isArray(saved)) return;
  for (const entry of saved) {
    let element = tab;
    for (const index of entry.path) {
      element = element?.children[index];
      if (!element) break;
    }
    // Avoid restoring a scroll position onto a different element after a
    // structural change, e.g. an empty state replacing an entire table.
    if (!element || element.tagName !== entry.tag) continue;
    element.scrollTop = entry.top;
    element.scrollLeft = entry.left;
  }
}
function captureRefreshScrollState() {
  const root =
    document.scrollingElement || document.documentElement || document.body,
    table = document.querySelector("#scheduleGrid .timetable"),
    content = document.querySelector(".workspace .content"),
    activeTab = document.querySelector(".workspace-tabs-stage .tab.active");
  const tableRect = table ? table.getBoundingClientRect() : null;
  return {
    pageTop: window.pageYOffset ?? window.scrollY ?? root?.scrollTop ?? 0,
    pageLeft: window.pageXOffset ?? window.scrollX ?? root?.scrollLeft ?? 0,
    tableTop: table ? table.scrollTop : null,
    tableLeft: table ? table.scrollLeft : null,
    tableRectTop: tableRect ? tableRect.top : null,
    contentTop: content ? content.scrollTop : null,
    contentLeft: content ? content.scrollLeft : null,
    // The active tab itself (not .content) owns the page's vertical scroll.
    activeTabId: activeTab?.id ?? null,
    activeTabTop: activeTab?.scrollTop ?? null,
    activeTabLeft: activeTab?.scrollLeft ?? null,
    nestedScroll: captureWorkspaceNestedScroll(activeTab),
  };
}
function restoreRefreshScrollState(state) {
  if (!state) return;
  const apply = () => {
    // An asynchronous refresh may finish after the user changes tab.
    // Never move the user back to a former page in that case.
    const activeTab = document.querySelector(".workspace-tabs-stage .tab.active");
    if (state.activeTabId && activeTab?.id !== state.activeTabId) return;
    const table = document.querySelector("#scheduleGrid .timetable"),
      content = document.querySelector(".workspace .content"),
      root =
        document.scrollingElement || document.documentElement || document.body;

    if (table) {
      const top = state.tableTop ?? table.scrollTop;
      const left = state.tableLeft ?? table.scrollLeft;
      try {
        table.scrollTo({ top, left, behavior: "instant" });
      } catch {
        table.scrollTop = top;
        table.scrollLeft = left;
      }
    }

    if (content && (state.contentTop != null || state.contentLeft != null)) {
      const top = state.contentTop ?? content.scrollTop;
      const left = state.contentLeft ?? content.scrollLeft;
      try {
        content.scrollTo({ top, left, behavior: "instant" });
      } catch {
        content.scrollTop = top;
        content.scrollLeft = left;
      }
    }

    // Restoring .content alone is not sufficient: the active tab has its own
    // overflow-y:auto, and its position must survive a full renderAll().
    if (activeTab && state.activeTabId === activeTab.id) {
      restoreWorkspaceNestedScroll(activeTab, state.nestedScroll);
      activeTab.scrollTop = state.activeTabTop ?? activeTab.scrollTop;
      activeTab.scrollLeft = state.activeTabLeft ?? activeTab.scrollLeft;
    }

    let targetPageTop = state.pageTop ?? 0;
    let targetPageLeft = state.pageLeft ?? 0;

    if (state.tableRectTop != null && table) {
      const currentRect = table.getBoundingClientRect();
      const deltaY = currentRect.top - state.tableRectTop;
      if (Math.abs(deltaY) > 1) {
        targetPageTop += deltaY;
      }
    }

    try {
      window.scrollTo({
        top: targetPageTop,
        left: targetPageLeft,
        behavior: "instant",
      });
    } catch {
      window.scrollTo(targetPageLeft, targetPageTop);
    }
    if (root) {
      root.scrollTop = targetPageTop;
      root.scrollLeft = targetPageLeft;
    }
  };

  apply();
  requestAnimationFrame(apply);
}
let refreshRequestSequence = 0;
let latestAppliedFullRefreshSequence = 0;
const latestAppliedPartRefreshSequence = new Map();

async function refresh(skipOperationStatus = false, parts = null) {
  const init = skipOperationStatus ? { headers: operationHeaders() } : undefined,
    requestedParts = Array.isArray(parts)
      ? [...new Set(parts.filter(Boolean))]
      : [],
    effectiveParts = requestedParts.includes("lessons")
      ? [...new Set([...requestedParts, "schedule_validation"])].sort()
      : [...requestedParts].sort(),
    query = effectiveParts.length
      ? `?parts=${encodeURIComponent(effectiveParts.join(","))}`
      : "",
    sequence = ++refreshRequestSequence,
    isFullRefresh = effectiveParts.length === 0;

  // A newer request does not make an older successful response stale by itself.
  // It only supersedes older data after the newer response was applied. This
  // prevents a later request that fails from causing a valid earlier response
  // to be discarded and leaving the UI on stale data.
  const responseAlreadySuperseded = () => {
    if (isFullRefresh) return latestAppliedFullRefreshSequence > sequence;
    if (latestAppliedFullRefreshSequence > sequence) return true;
    return effectiveParts.every(
      (part) => (latestAppliedPartRefreshSequence.get(part) || 0) > sequence,
    );
  };

  let r;
  try {
    r = await fetch(`/api/projects/${PROJECT_ID}/data${query}`, init);
  } catch (error) {
    if (responseAlreadySuperseded()) return data;
    throw error;
  }
  const result = await readApiResponse(r);
  if (!r.ok) {
    if (responseAlreadySuperseded()) return data;
    const error = new Error(
      apiErrorMessage(result, "Không thể tải lại dữ liệu từ máy chủ."),
    );
    error.isRefreshError = true;
    throw error;
  }
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    if (responseAlreadySuperseded()) return data;
    const error = new Error("Dữ liệu trả về từ máy chủ không hợp lệ.");
    error.isRefreshError = true;
    throw error;
  }

  const appliedParts = [];
  const merged = { ...data };
  if (isFullRefresh) {
    Object.entries(result).forEach(([key, value]) => {
      const latestApplied = latestAppliedPartRefreshSequence.get(key) || 0;
      if (latestApplied > sequence) return;
      merged[key] = value;
      latestAppliedPartRefreshSequence.set(key, sequence);
      appliedParts.push(key);
    });
    latestAppliedFullRefreshSequence = Math.max(
      latestAppliedFullRefreshSequence,
      sequence,
    );
  } else {
    effectiveParts.forEach((part) => {
      if (!Object.prototype.hasOwnProperty.call(result, part)) return;
      const latestApplied = latestAppliedPartRefreshSequence.get(part) || 0;
      if (latestApplied > sequence) return;
      merged[part] = result[part];
      latestAppliedPartRefreshSequence.set(part, sequence);
      appliedParts.push(part);
    });
  }

  if (!appliedParts.length) return data;
  data = merged;
  // Capture immediately before render, not before the network request: the
  // user may have scrolled while waiting for the response.
  const scrollState = captureRefreshScrollState();

  // Khi đang xếp thủ công, giữ thanh trạng thái "Đang xếp" trong lúc
  // dữ liệu mới được render. Luồng xếp sẽ tự đóng thanh sau khi UI đã vẽ xong.
  const preserveTapAssignDuringPlacement = Boolean(
    typeof activeTapAssign !== "undefined" &&
    activeTapAssign?.placementSubmitting,
  );
  if (typeof clearTapAssign === "function" && !preserveTapAssignDuringPlacement)
    clearTapAssign();
  const lessonOnlyRefresh =
    appliedParts.includes("lessons") &&
    appliedParts.every((part) => ["lessons", "schedule_validation"].includes(part));
  if (lessonOnlyRefresh) {
    renderScheduleAfterLessonChange();
  } else {
    renderAll();
  }
  restoreRefreshScrollState(scrollState);
  requestAnimationFrame(() => restoreRefreshScrollState(scrollState));
  return data;
}
async function refreshAfterSuccessfulMutation(parts = null, message = null) {
  try {
    await refresh(true, parts);
    return true;
  } catch (error) {
    showToast(
      message ||
      `Thay đổi đã được lưu nhưng trang chưa cập nhật được. Hãy tải lại trang để xem kết quả.`,
      "warning",
      6000,
    );
    return false;
  }
}
