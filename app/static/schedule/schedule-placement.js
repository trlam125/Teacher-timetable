/* Manual lesson placement and schedule editing actions. */
const pendingLessonPlacements = new Set();
function renderScheduleAfterLessonChange() {
  const scrollState = captureRefreshScrollState();
  renderSchedule(true);
  renderManualTray();
  if ($("#statLessons")) $("#statLessons").textContent = data.lessons.length;
  restoreRefreshScrollState(scrollState);
}
function showPlacementConflict(slot, message) {
  const text = message || "Không thể xếp tiết";
  const cell = document.querySelector(`.cell.available[data-slot="${slot}"]`);
  if (cell) {
    cell.title = text;
    cell.classList.add("conflict-shake");
    setTimeout(() => cell.classList.remove("conflict-shake"), 600);
  }
  showToast(text, "warning", 3600);
}
// Placement validity is authoritative on the server. The browser only renders
// /placement-options and surfaces the mutation endpoint's validation message.

function scheduleAvoidReason(slot) {
  let assignment = null;
  const payload = typeof activeTapAssign !== "undefined" ? activeTapAssign?.payload : null;
  if (payload?.startsWith("assignment:")) {
    assignment = data.assignments.find((row) => row.id === Number(payload.slice(11)));
  } else if (/^\d+$/.test(payload || "")) {
    const lesson = data.lessons.find((row) => row.id === Number(payload));
    assignment = data.assignments.find((row) => row.id === lesson?.assignment_id);
  }
  const view = $("#viewType")?.value;
  const entityId = Number($("#viewEntity")?.value);
  const teacherId = assignment?.teacher_id ?? (view === "teacher" ? entityId : null);
  const classId = assignment?.class_id ?? (view === "class" ? entityId : null);
  const teacher = (data.teachers || []).find((row) => row.id === teacherId);
  const schoolClass = (data.classes || []).find((row) => row.id === classId);
  const reasons = [];
  if ((teacher?.unavailable || []).some((value) => Number(value) === slot))
    reasons.push(`Giáo viên ${teacher.name} đã đặt tránh tiết này.`);
  if ((schoolClass?.unavailable || []).some((value) => Number(value) === slot))
    reasons.push(`Lớp ${schoolClass.name} đã đặt tránh tiết này.`);
  return reasons.join(" ");
}

function markScheduleAvoidSlots() {
  document.querySelectorAll("#scheduleGrid .cell.available[data-slot]").forEach((cell) => {
    const reason = scheduleAvoidReason(Number(cell.dataset.slot));
    cell.classList.toggle("entity-unavailable-slot", Boolean(reason));
    if (reason) {
      cell.dataset.avoidReason = reason;
      cell.setAttribute("tabindex", "0");
      cell.setAttribute("role", "button");
      cell.setAttribute("aria-label", "Tiết tránh. Bấm để xem lý do.");
    } else if (cell.dataset.avoidReason) {
      delete cell.dataset.avoidReason;
      cell.removeAttribute("tabindex");
      cell.removeAttribute("role");
      cell.removeAttribute("aria-label");
    }
  });
}

let placementOptionsRequestSerial = 0;

function clearPlacementTargetState() {
  placementOptionsRequestSerial += 1;
  const workspace = document.querySelector(".workspace");
  workspace?.classList.remove(
    "placement-options-loading",
    "placement-options-ready",
  );
  document
    .querySelectorAll(
      "#scheduleGrid .cell.available.placement-valid-slot, #scheduleGrid .cell.available.placement-invalid-slot",
    )
    .forEach((cell) => {
      cell.classList.remove("placement-valid-slot", "placement-invalid-slot");
      delete cell.dataset.placementInvalidReason;
    });
}

function applyPlacementTargetOptions(validSlots, message = "") {
  const valid = validSlots instanceof Set ? validSlots : new Set(validSlots || []);
  const workspace = document.querySelector(".workspace");
  workspace?.classList.remove("placement-options-loading");
  workspace?.classList.add("placement-options-ready");
  document
    .querySelectorAll("#scheduleGrid .cell.available[data-slot]")
    .forEach((cell) => {
      const slot = Number(cell.dataset.slot);
      const allowed = valid.has(slot);
      cell.classList.toggle("placement-valid-slot", allowed);
      cell.classList.toggle("placement-invalid-slot", !allowed);
      if (!allowed) {
        cell.dataset.placementInvalidReason =
          message || "Ô này không hợp lệ với các ràng buộc hiện tại.";
      } else {
        delete cell.dataset.placementInvalidReason;
      }
    });
}

async function loadPlacementOptionsForTap(payload, moveScope = null) {
  if (window.READ_ONLY || !payload || payload.startsWith("scheduled-assignment:"))
    return null;
  if (!activeTapAssign || activeTapAssign.payload !== payload) return null;

  const isNew = payload.startsWith("assignment:");
  const rawId = isNew ? payload.slice("assignment:".length) : payload;
  if (!/^\d+$/.test(rawId)) return null;

  const requestId = ++placementOptionsRequestSerial;
  activeTapAssign.placementLoading = true;
  activeTapAssign.validSlots = null;
  activeTapAssign.placementMessage = "";
  const workspace = document.querySelector(".workspace");
  workspace?.classList.remove("placement-options-ready");
  workspace?.classList.add("placement-options-loading");
  document
    .querySelectorAll("#scheduleGrid .cell.available[data-slot]")
    .forEach((cell) =>
      cell.classList.remove("placement-valid-slot", "placement-invalid-slot"),
    );

  const body = isNew
    ? { assignment_id: Number(rawId) }
    : { lesson_id: Number(rawId), move_scope: moveScope || "group" };

  try {
    const response = await fetch(`/api/projects/${PROJECT_ID}/placement-options`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    const result = await readApiResponse(response);
    if (
      requestId !== placementOptionsRequestSerial ||
      !activeTapAssign ||
      activeTapAssign.payload !== payload
    )
      return null;

    activeTapAssign.placementLoading = false;
    if (!response.ok) {
      const message = apiErrorMessage(
        result,
        "Không thể kiểm tra các ô có thể xếp.",
      );
      activeTapAssign.validSlots = new Set();
      activeTapAssign.placementMessage = message;
      applyPlacementTargetOptions(activeTapAssign.validSlots, message);
      showToast(message, "error", 4200);
      return null;
    }

    const validSlots = new Set(
      (result.valid_slots || []).map(Number).filter(Number.isInteger),
    );
    activeTapAssign.validSlots = validSlots;
    activeTapAssign.placementMessage = String(result.message || "");
    activeTapAssign.groupSize = Number(result.group_size || 1);
    activeTapAssign.moveScope = isNew
      ? activeTapAssign.moveScope
      : result.move_scope || moveScope || "group";
    applyPlacementTargetOptions(validSlots, activeTapAssign.placementMessage);
    if (typeof renderTapAssignBar === "function") renderTapAssignBar();
    if (!validSlots.size && activeTapAssign.placementMessage) {
      showToast(activeTapAssign.placementMessage, "warning", 3600);
    }
    return result;
  } catch (error) {
    if (
      requestId !== placementOptionsRequestSerial ||
      !activeTapAssign ||
      activeTapAssign.payload !== payload
    )
      return null;
    activeTapAssign.placementLoading = false;
    const message = requestFailureMessage(
      error,
      "Mất kết nối tới máy chủ. Chưa thể kiểm tra ô xếp hợp lệ.",
    );
    activeTapAssign.validSlots = new Set();
    activeTapAssign.placementMessage = message;
    applyPlacementTargetOptions(activeTapAssign.validSlots, message);
    showToast(message, "error", 4200);
    return null;
  }
}

async function placeLessonPayload(raw, slot) {
  if (window.READ_ONLY || !raw || pendingLessonPlacements.size) return false;
  const numericSlot = Number(slot);
  const isNew = raw.startsWith("assignment:");
  const rawId = isNew ? raw.slice("assignment:".length) : raw;
  if (!/^\d+$/.test(rawId)) return false;

  const id = Number(rawId);
  let assignment = null;
  let lesson = null;
  if (isNew) {
    assignment = data.assignments.find((item) => Number(item.id) === id);
    if (!assignment) return false;
  } else {
    lesson = data.lessons.find((item) => Number(item.id) === id);
    if (!lesson || lesson.locked) return false;
    assignment = data.assignments.find(
      (item) => Number(item.id) === Number(lesson.assignment_id),
    );
    if (!assignment) return false;
  }

  const selectedState =
    activeTapAssign && activeTapAssign.payload === raw ? activeTapAssign : null;
  if (selectedState?.placementLoading) {
    showToast("Đang kiểm tra các ô có thể xếp…", "info", 1800);
    return false;
  }
  if (selectedState?.validSlots instanceof Set && !selectedState.validSlots.has(numericSlot)) {
    const message =
      document.querySelector(
        `#scheduleGrid .cell.available[data-slot="${numericSlot}"]`,
      )?.dataset.placementInvalidReason ||
      selectedState.placementMessage ||
      "Ô này không hợp lệ với các ràng buộc hiện tại.";
    showPlacementConflict(numericSlot, message);
    return false;
  }

  const moveScope =
    !isNew && assignment.block_mode === "required_double" ? "group" : "single";

  if (!isNew) {
    const currentStart =
      moveScope === "group"
        ? Math.min(
          ...requiredDoubleBlockLessons(id).map((item) => Number(item.slot)),
        )
        : Number(lesson.slot);
    if (Number.isFinite(currentStart) && currentStart === numericSlot) return false;
  }

  const endpoint = isNew
    ? `/api/projects/${PROJECT_ID}/lessons`
    : `/api/projects/${PROJECT_ID}/move`;
  const payload = isNew
    ? { assignment_id: id, slot: numericSlot }
    : { lesson_id: id, slot: numericSlot, move_scope: moveScope };

  pendingLessonPlacements.add(raw);
  try {
    const r = await fetch(endpoint, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    const j = await readApiResponse(r);
    if (!r.ok) {
      showPlacementConflict(numericSlot, apiErrorMessage(j, "Không thể xếp tiết"));
      return false;
    }

    // Chỉ cập nhật giao diện sau khi máy chủ đã chấp nhận. Danh sách ô hợp lệ
    // và trạng thái required_double đều do máy chủ tính, nên giao diện không
    // duy trì một bộ luật xếp lịch thứ hai.
    if (j.schedule_validation) {
      data.schedule_validation = j.schedule_validation;
    }
    if (isNew) {
      if (Array.isArray(j.added_lessons) && j.added_lessons.length) {
        data.lessons.push(...j.added_lessons);
      } else {
        data.lessons.push({
          id: Number(j.id),
          assignment_id: id,
          slot: numericSlot,
          block_id: j.block_id || null,
          locked: false,
        });
      }
    } else {
      const removed = new Set((j.removed_ids || []).map(Number));
      data.lessons = data.lessons.filter((item) => !removed.has(Number(item.id)));
      data.lessons.push(...(j.moved_lessons || []));
    }
    renderScheduleAfterLessonChange();

    try {
      await refresh(true, ["lessons"]);
    } catch (refreshError) {
      const refreshMessage =
        refreshError?.message || requestFailureMessage(refreshError);
      showToast(
        `Đã lưu thay đổi nhưng chưa thể đồng bộ lại dữ liệu: ${refreshMessage}`,
        "warning",
        5000,
      );
    }
    return true;
  } catch (error) {
    showPlacementConflict(numericSlot, requestFailureMessage(error));
    return false;
  } finally {
    pendingLessonPlacements.delete(raw);
  }
}
async function removeLesson(id) {
  setTrayActionStatus("loading", "Đang đưa tiết về khay…");
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/lessons/${id}`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const j = await readApiResponse(r);
    if (r.ok) {
      await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Tiết đã được đưa về khay trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      setTrayActionStatus("success", j.message || "Đã đưa tiết về khay", 1800);
      return true;
    }
    setTrayActionStatus("error", apiErrorMessage(j, "Không thể gỡ tiết"), 3600);
    return false;
  } catch (error) {
    setTrayActionStatus(
      "error",
      requestFailureMessage(
        error,
        "Mất kết nối tới máy chủ. Không thể đưa tiết về khay.",
      ),
      3600,
    );
    return false;
  }
}
async function setFixed(assignmentId, slot, button) {
  const original = button?.innerHTML || lessonActionIcon("pin");
  if (button) {
    button.disabled = true;
    button.textContent = "…";
  }
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/fixed`, {
      method: "POST",
      headers: operationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ assignment_id: assignmentId, slot }),
    });
    const j = await readApiResponse(r);
    if (r.ok) {
      const refreshed = await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Tiết đã được cố định trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      if (!refreshed && button?.isConnected) {
        button.textContent = "✓";
        button.title = "Đã cố định trên máy chủ. Hãy tải lại trang để đồng bộ.";
        button.disabled = true;
      }
    } else {
      restoreTransientActionButton(
        button,
        original,
        apiErrorMessage(j, "Không thể cố định tiết"),
      );
    }
  } catch (error) {
    restoreTransientActionButton(button, original, requestFailureMessage(error));
  }
}
async function unfixGroup(assignmentId, slot, button) {
  const original = button?.innerHTML || lessonActionIcon("unlock");
  if (button) {
    button.disabled = true;
    button.textContent = "…";
  }
  try {
    const r = await fetch(
      `/api/projects/${PROJECT_ID}/fixed/${assignmentId}/${slot}`,
      { method: "DELETE", headers: operationHeaders() },
    );
    const j = await readApiResponse(r);
    if (r.ok) {
      const refreshed = await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Đã bỏ cố định trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      if (!refreshed && button?.isConnected) {
        button.textContent = "✓";
        button.title = "Đã bỏ cố định trên máy chủ. Hãy tải lại trang để đồng bộ.";
        button.disabled = true;
      }
    } else {
      restoreTransientActionButton(
        button,
        original,
        apiErrorMessage(j, "Không thể bỏ cố định"),
      );
    }
  } catch (error) {
    restoreTransientActionButton(button, original, requestFailureMessage(error));
  }
}
async function returnAssignmentToTray(id) {
  setTrayActionStatus("loading", "Đang đưa các tiết chưa cố định về khay…");
  try {
    const r = await fetch(
      `/api/projects/${PROJECT_ID}/assignments/${id}/lessons`,
      { method: "DELETE", headers: operationHeaders() },
    );
    const j = await readApiResponse(r);
    if (!r.ok) {
      setTrayActionStatus(
        "error",
        apiErrorMessage(j, "Không thể đưa phân công về khay"),
        3600,
      );
      return false;
    }

    await refreshAfterSuccessfulMutation(
      ["lessons"],
      "Các tiết chưa cố định đã được đưa về khay trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
    );
    setTrayActionStatus(
      "success",
      j.message || `Đã đưa ${Number(j.removed) || 0} tiết chưa cố định về khay.`,
      2600,
    );
    return true;
  } catch (error) {
    setTrayActionStatus(
      "error",
      requestFailureMessage(
        error,
        "Mất kết nối tới máy chủ. Không thể đưa phân công về khay.",
      ),
      3600,
    );
    return false;
  }
}

async function returnAllToTray(button) {
  if (
    !(await confirmAction(
      "Đưa toàn bộ tiết chưa cố định về khay? Các tiết đã cố định sẽ được giữ nguyên. Phân công và số tiết/tuần không thay đổi.",
      { title: "Đưa lịch về khay", confirmText: "Đưa về khay" },
    ))
  )
    return;
  setInlineActionState(button, "loading", {
    idle: "Đưa tiết chưa cố định về khay",
    loading: "Đang đưa về khay...",
  });
  try {
    const r = await fetch(`/api/projects/${PROJECT_ID}/lessons`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const j = await readApiResponse(r);
    if (r.ok) {
      await refreshAfterSuccessfulMutation(
        ["lessons"],
        "Các tiết đã được đưa về khay trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      setInlineActionState(
        button,
        "success",
        { idle: "Đưa tiết chưa cố định về khay", success: "Đã đưa về khay" },
        1800,
      );
      showToast(
        j.message || "Đã đưa các tiết chưa cố định về khay.",
        "success",
        2600,
      );
    } else {
      setInlineActionState(
        button,
        "error",
        { idle: "Đưa tiết chưa cố định về khay", error: "Chưa đưa được" },
        2200,
      );
      showToast(
        apiErrorMessage(j, "Không thể đưa lịch về khay."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Đưa tiết chưa cố định về khay", error: "Chưa hoàn tất" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
async function returnPayloadToTray(raw) {
  if (window.READ_ONLY || !raw || raw.startsWith("assignment:")) return false;
  if (raw.startsWith("scheduled-assignment:")) {
    return returnAssignmentToTray(Number(raw.split(":")[1]));
  }
  if (/^\d+$/.test(raw)) return removeLesson(Number(raw));
  return false;
}
