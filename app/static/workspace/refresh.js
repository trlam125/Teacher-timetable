function captureRefreshScrollState() {
  const root =
    document.scrollingElement || document.documentElement || document.body,
    table = document.querySelector("#scheduleGrid .timetable"),
    content = document.querySelector(".workspace .content");
  const tableRect = table ? table.getBoundingClientRect() : null;
  return {
    pageTop: window.pageYOffset ?? window.scrollY ?? root?.scrollTop ?? 0,
    pageLeft: window.pageXOffset ?? window.scrollX ?? root?.scrollLeft ?? 0,
    tableTop: table ? table.scrollTop : null,
    tableLeft: table ? table.scrollLeft : null,
    tableRectTop: tableRect ? tableRect.top : null,
    contentTop: content ? content.scrollTop : null,
    contentLeft: content ? content.scrollLeft : null,
  };
}
function restoreRefreshScrollState(state) {
  if (!state) return;
  const apply = () => {
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
  const scrollState = captureRefreshScrollState(),
    init = skipOperationStatus ? { headers: operationHeaders() } : undefined,
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
    const detail = error?.message || requestFailureMessage(error);
    showToast(
      message ||
      `Thay đổi đã được lưu trên máy chủ nhưng giao diện chưa thể đồng bộ dữ liệu mới: ${detail}`,
      "warning",
      6000,
    );
    return false;
  }
}
