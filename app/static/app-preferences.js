function preferenceSlotLabel(slot) {
  const ppd = data.project.sessions * data.project.periods,
    day = Math.floor(slot / ppd),
    inside = slot % ppd,
    session = Math.floor(inside / data.project.periods),
    period = inside % data.project.periods;
  return `${["T2", "T3", "T4", "T5", "T6", "T7", "CN"][day]} · ${data.project.sessions > 1 ? (session ? "Chiều" : "Sáng") + " · " : ""}Tiết ${period + 1}`;
}
async function loadPreferenceInbox() {
  const box = $("#preferenceInbox");
  if (!box) return;
  box.innerHTML =
    '<div class="empty-state">Đang tải nguyện vọng giáo viên…</div>';
  const deleteAllButton = $("#deleteAllPreferencesButton");
  if (deleteAllButton) deleteAllButton.disabled = true;
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  if (!projectId) {
    box.innerHTML = '<div class="empty-state">Chưa có nguyện vọng nào.</div>';
    return;
  }
  try {
    const r = await fetch(`/api/projects/${projectId}/preferences`);
    const result = await readApiResponse(r);
    if (r.status === 404 || result?.status === 404) {
      box.innerHTML = '<div class="empty-state">Chưa có nguyện vọng nào.</div>';
      if (deleteAllButton) deleteAllButton.disabled = true;
      return;
    }
    if (!r.ok) {
      box.innerHTML = `<div class="empty-state">${esc(
        apiErrorMessage(result, "Không thể tải nguyện vọng giáo viên."),
      )}</div>`;
      return;
    }
    const items = Array.isArray(result.items) ? result.items : [];
    if (!items.length) {
      box.innerHTML = '<div class="empty-state">Chưa có nguyện vọng nào.</div>';
      if (deleteAllButton) deleteAllButton.disabled = true;
      return;
    }
    const statuses = {
      pending: "Chờ duyệt",
      accepted: "Đã ghi nhận",
      rejected: "Đã từ chối",
      superseded: "Đã thay thế",
    };
    if (deleteAllButton) deleteAllButton.disabled = items.length === 0;
    box.innerHTML = `<div class="preference-list">${items.map((item) => {
      const reviewActions = item.status === "pending"
        ? `<button class="btn ghost" onclick="reviewPreference(${item.id},'reject',this)">Từ chối</button><button class="btn" onclick="reviewPreference(${item.id},'accept',this)">Ghi nhận</button>`
        : "";
      return `<article class="preference-card"><div class="preference-card-head"><div><h3>${esc(item.teacher_name)}</h3>${item.teacher_email ? `<small>${esc(item.teacher_email)}</small>` : ""}<small>${esc(item.created_at_display || String(item.created_at || "").replace("T", " "))}</small></div><span class="status status-${item.status}">${statuses[item.status] || esc(item.status)}</span></div><div class="preference-detail"><b>Tiết mong muốn</b><div class="slot-chips">${item.preferred_slots?.length ? item.preferred_slots.map((slot) => `<span class="slot-chip preferred">${preferenceSlotLabel(slot)}</span>`).join("") : '<span class="muted">Không đăng ký</span>'}</div></div><div class="preference-detail"><b>Tiết cần tránh</b><div class="slot-chips">${item.unavailable_slots?.length ? item.unavailable_slots.map((slot) => `<span class="slot-chip blocked">${preferenceSlotLabel(slot)}</span>`).join("") : '<span class="muted">Không đăng ký</span>'}</div></div>${item.note ? `<p class="preference-note">${esc(item.note)}</p>` : ""}<div class="row end preference-card-actions"><button class="btn ghost preference-delete-btn" onclick="deletePreference(${item.id},this)">Xóa</button>${reviewActions}</div></article>`;
    }).join("")}</div>`;
  } catch (error) {
    box.innerHTML = `<div class="empty-state">${esc(
      requestFailureMessage(
        error,
        "Mất kết nối tới máy chủ. Không thể tải nguyện vọng giáo viên.",
      ),
    )}</div>`;
  }
}

async function deletePreference(id, button) {
  const confirmed = await confirmAction(
    "Xóa nguyện vọng này? Thao tác này không thể hoàn tác.",
    { title: "Xóa nguyện vọng", confirmText: "Xóa" },
  );
  if (!confirmed) return;
  setInlineActionState(button, "loading", {
    idle: "Xóa",
    loading: "Đang xóa...",
  });
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  try {
    const r = await fetch(`/api/projects/${projectId}/preferences/${id}`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const result = await readApiResponse(r);
    if (!r.ok) {
      setInlineActionState(button, "error", { idle: "Xóa", error: "Không thể xóa" }, 2200);
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể xóa nguyện vọng."),
        "error",
        5000,
      );
      return;
    }
    setInlineActionState(button, "success", { idle: "Xóa", success: "Đã xóa" });
    await wait(350);
    await loadPreferenceInbox();
  } catch (error) {
    setInlineActionState(button, "error", { idle: "Xóa", error: "Chưa xóa được" }, 2200);
    showToast(requestFailureMessage(error), "error", 5000);
  }
}

async function deleteAllPreferences(button) {
  const confirmed = await confirmAction(
    "Xóa toàn bộ nguyện vọng giáo viên trong bộ thời khóa biểu này? Thao tác này không thể hoàn tác.",
    { title: "Xóa tất cả nguyện vọng", confirmText: "Xóa tất cả" },
  );
  if (!confirmed) return;
  setInlineActionState(button, "loading", {
    idle: "Xóa tất cả",
    loading: "Đang xóa...",
  });
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  try {
    const r = await fetch(`/api/projects/${projectId}/preferences`, {
      method: "DELETE",
      headers: operationHeaders(),
    });
    const result = await readApiResponse(r);
    if (!r.ok) {
      setInlineActionState(
        button,
        "error",
        { idle: "Xóa tất cả", error: "Không thể xóa" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể xóa toàn bộ nguyện vọng."),
        "error",
        5000,
      );
      return;
    }
    const deleted = Number(result.deleted || 0);
    setInlineActionState(button, "success", {
      idle: "Xóa tất cả",
      success: deleted ? `Đã xóa ${deleted}` : "Không có dữ liệu",
    });
    await wait(450);
    await loadPreferenceInbox();
  } catch (error) {
    setInlineActionState(
      button,
      "error",
      { idle: "Xóa tất cả", error: "Chưa xóa được" },
      2200,
    );
    showToast(requestFailureMessage(error), "error", 5000);
  }
}

async function reviewPreference(id, action, button) {
  const idle = action === "accept" ? "Ghi nhận" : "Từ chối",
    loading = action === "accept" ? "Đang ghi nhận..." : "Đang từ chối...",
    success = action === "accept" ? "Đã ghi nhận" : "Đã từ chối";
  setInlineActionState(button, "loading", { idle, loading });
  const projectId = window.PROJECT_ID || data?.project?.id || PROJECT_ID;
  try {
    const r = await fetch(
      `/api/projects/${projectId}/preferences/${id}/review`,
      {
        method: "POST",
        headers: operationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ action }),
      },
    );
    const result = await readApiResponse(r);
    if (r.ok) {
      setInlineActionState(button, "success", { idle, success });
      await wait(600);
      const refreshed = await refreshAfterSuccessfulMutation(
        null,
        "Nguyện vọng đã được cập nhật trên máy chủ nhưng giao diện chưa thể tải lại dữ liệu mới. Hãy tải lại trang để đồng bộ.",
      );
      if (refreshed) {
        try {
          await loadPreferenceInbox();
        } catch (error) {
          showToast(requestFailureMessage(error), "warning", 5000);
        }
      }
    } else {
      setInlineActionState(
        button,
        "error",
        { idle, error: "Chưa cập nhật" },
        2200,
      );
      showInlineActionFeedback(
        button,
        apiErrorMessage(result, "Không thể cập nhật nguyện vọng."),
        "error",
        5000,
      );
    }
  } catch (error) {
    setInlineActionState(button, "error", { idle, error: "Chưa cập nhật" }, 2200);
    showToast(requestFailureMessage(error), "error", 5000);
  }
}
async function copyTextWithFallback(text) {
  const value = String(text || "");
  if (!value) return false;
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // WebView và một số trình duyệt chặn Clipboard API; dùng fallback bên dưới.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try {
    copied = Boolean(document.execCommand?.("copy"));
  } catch {
    copied = false;
  } finally {
    textarea.remove();
  }
  return copied;
}
function openManualShareDialog(shareUrl) {
  const value = String(shareUrl || "");
  if (!value) {
    showToast("Chưa có liên kết chia sẻ để sao chép.", "error", 4200);
    return;
  }

  let dialog = document.getElementById("manualShareDialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "manualShareDialog";
    dialog.className = "manual-share-dialog";
    dialog.setAttribute("data-app-zoom", "");
    dialog.innerHTML = `
      <div class="modal-form manual-share-modal">
        <div class="manual-share-head">
          <div>
            <h2>Liên kết chia sẻ</h2>
            <p>Trình duyệt đang chặn sao chép tự động. Chọn liên kết bên dưới và sao chép thủ công.</p>
          </div>
          <button type="button" class="manual-share-close" aria-label="Đóng">×</button>
        </div>
        <div class="manual-share-copy-row">
          <input id="manualShareInput" type="text" readonly aria-label="Liên kết chia sẻ">
          <button id="manualShareCopyBtn" type="button" class="btn">Sao chép</button>
        </div>
        <div id="manualShareHint" class="manual-share-hint" aria-live="polite"></div>
      </div>
    `;
    document.body.appendChild(dialog);

    dialog.querySelector(".manual-share-close")?.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.querySelector("#manualShareCopyBtn")?.addEventListener("click", async () => {
      const input = dialog.querySelector("#manualShareInput");
      const hint = dialog.querySelector("#manualShareHint");
      if (!input) return;
      const copied = await copyTextWithFallback(input.value);
      if (copied) {
        if (hint) {
          hint.textContent = "Đã sao chép liên kết.";
          hint.className = "manual-share-hint is-success";
        }
        return;
      }
      input.focus();
      input.select();
      input.setSelectionRange(0, input.value.length);
      if (hint) {
        hint.textContent = "Liên kết đã được chọn. Nhấn Ctrl+C (hoặc Sao chép trên điện thoại).";
        hint.className = "manual-share-hint is-error";
      }
    });
  }

  const input = dialog.querySelector("#manualShareInput");
  const hint = dialog.querySelector("#manualShareHint");
  if (input) input.value = value;
  if (hint) {
    hint.textContent = "";
    hint.className = "manual-share-hint";
  }

  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  setTimeout(() => {
    input?.focus();
    input?.select();
    input?.setSelectionRange(0, input.value.length);
  }, 0);
}
async function copyShare(button) {
  const shareUrl = String(window.SHARE_URL || "");
  if (!shareUrl) {
    showToast("Không tìm thấy liên kết chia sẻ.", "error", 3600);
    return;
  }
  if (button?.dataset.shareBusy === "1") return;

  if (button) {
    button.dataset.shareBusy = "1";
    setInlineActionState(
      button,
      "loading",
      { idle: "Chia sẻ", loading: "Đang sao chép..." },
    );
  }

  try {
    // Sharing is allowed for both valid and currently-invalid timetables.
    // Integrity checking remains a separate diagnostic feature.
    const copied = await copyTextWithFallback(shareUrl);
    if (copied) {
      if (button) {
        setInlineActionState(
          button,
          "success",
          { idle: "Chia sẻ", success: "Đã sao chép" },
          1700,
        );
        showInlineActionFeedback(
          button,
          "Đã sao chép liên kết chia sẻ.",
          "success",
          2400,
        );
      } else {
        showToast("Đã sao chép liên kết chia sẻ.", "success", 2400);
      }
      return;
    }

    if (button) {
      setInlineActionState(
        button,
        "error",
        { idle: "Chia sẻ", error: "Sao chép thủ công" },
        2200,
      );
      showInlineActionFeedback(
        button,
        "Trình duyệt không cho phép sao chép tự động. Liên kết chia sẻ đã được mở để bạn sao chép thủ công.",
        "error",
        5200,
      );
    }
    openManualShareDialog(shareUrl);
  } catch (error) {
    if (button) {
      setInlineActionState(
        button,
        "error",
        { idle: "Chia sẻ", error: "Chưa hoàn tất" },
        2200,
      );
    }
    showToast(
      requestFailureMessage(
        error,
        "Không thể sao chép liên kết chia sẻ. Hãy thử lại hoặc sao chép thủ công.",
      ),
      "error",
      5000,
    );
  } finally {
    if (button) delete button.dataset.shareBusy;
  }
}

function markGlobalBlockedSlots() {
  const blocked = new Set(data.project.blocked_slots || []),
    sessions = data.project.sessions,
    pps = data.project.periods,
    ppd = sessions * pps;

  document.querySelectorAll("[data-slot]").forEach((cell) => {
    cell.classList.remove("global-locked-slot");
    cell.removeAttribute("aria-disabled");
    delete cell.dataset.globalLocked;
    cell.querySelectorAll(".global-lock-label").forEach((label) => label.remove());
    cell.title = cell.dataset.conflictTitle || "";
  });

  for (const slot of blocked) {
    const day = Math.floor(slot / ppd),
      inside = slot % ppd,
      session = Math.floor(inside / pps),
      start = day * ppd + session * pps,
      wholeSession = Array.from(
        { length: pps },
        (_, index) => start + index,
      ).every((value) => blocked.has(value)),
      label = wholeSession ? "KHÓA BUỔI" : "KHÓA TIẾT",
      lockTitle = wholeSession ? "Buổi này đã bị khóa" : "Tiết này đã bị khóa";
    document.querySelectorAll(`[data-slot="${slot}"]`).forEach((cell) => {
      cell.classList.add("global-locked-slot");
      cell.dataset.globalLocked = "true";
      cell.setAttribute("aria-disabled", "true");
      const conflictTitle = cell.dataset.conflictTitle || "";
      cell.title = conflictTitle ? `${lockTitle} · ${conflictTitle}` : lockTitle;
      cell.insertAdjacentHTML(
        "afterbegin",
        `<span class="global-lock-label">${label}</span>`,
      );
    });
  }
}

const renderScheduleWithoutGlobalLocks = renderSchedule;
renderSchedule = function (...args) {
  renderScheduleWithoutGlobalLocks(...args);
  markGlobalBlockedSlots();
  markScheduleAvoidSlots();
};
renderAll();
renderScheduleSelectors();
renderConstraintSelectors();
activateRequestedWorkspaceTab();

entityModal?.addEventListener("close", () => {
  setEntityActionMessage("");
  const button = $("#entitySubmitButton");
  if (button) setInlineActionState(button, "idle", { idle: "Lưu" });
});

document.addEventListener("pointerdown", (event) => {
  const target = event.target.closest(".btn,.nav");
  if (!target) return;
  const rect = target.getBoundingClientRect(),
    ripple = document.createElement("span");
  ripple.className = "button-ripple";
  ripple.style.left = `${event.clientX - rect.left}px`;
  ripple.style.top = `${event.clientY - rect.top}px`;
  target.appendChild(ripple);
  setTimeout(() => ripple.remove(), 700);
});
function tapAssignCapabilities(payload) {
  return {
    schedule: Boolean(payload) && !payload.startsWith("scheduled-assignment:"),
    tray: Boolean(payload) && !payload.startsWith("assignment:"),
  };
}

function syncTapAssignClearance() {
  const bar = document.getElementById("tapAssignBar");
  if (!bar || !bar.isConnected) {
    document.documentElement.style.removeProperty("--tap-assign-clearance");
    return;
  }
  const clearance = Math.ceil(bar.getBoundingClientRect().height + 24);
  document.documentElement.style.setProperty(
    "--tap-assign-clearance",
    `${clearance}px`,
  );
}

function clearTapAssign() {
  document
    .querySelectorAll(".selected-for-assign")
    .forEach((el) => el.classList.remove("selected-for-assign"));
  const workspace = document.querySelector(".workspace");
  workspace?.classList.remove(
    "is-assign-mode",
    "tap-target-schedule",
    "tap-target-tray",
    "placement-scope-pending",
  );
  if (typeof clearPlacementTargetState === "function") clearPlacementTargetState();
  const bar = document.getElementById("tapAssignBar");
  if (bar) bar.remove();
  document.body.classList.remove("tap-assign-active");
  document.documentElement.style.removeProperty("--tap-assign-clearance");
  activeTapAssign = null;
  markScheduleAvoidSlots();
}

function getPayloadLabel(payload) {
  if (!payload || !data) return "Tiết học";
  try {
    if (payload.startsWith("assignment:")) {
      const aid = Number(payload.split(":")[1]);
      const a = data.assignments.find((x) => x.id === aid);
      return a
        ? `${a.subject_short || a.subject_name} (${a.class_name})`
        : "Tiết học";
    }
    if (payload.startsWith("scheduled-assignment:")) {
      const aid = Number(payload.split(":")[1]);
      const a = data.assignments.find((x) => x.id === aid);
      return a
        ? `${a.subject_short || a.subject_name} (${a.class_name})`
        : "Phân công";
    }
    const lid = Number(payload);
    if (Number.isInteger(lid)) {
      const l = data.lessons.find((x) => x.id === lid);
      if (l) {
        const a = data.assignments.find((x) => x.id === l.assignment_id);
        return a
          ? `${a.subject_short || a.subject_name} (${a.class_name})`
          : "Tiết học";
      }
    }
  } catch (e) { }
  return "Tiết học";
}

function tapAssignClusterSize(payload) {
  if ((payload || "").startsWith("assignment:")) {
    return Number(activeTapAssign?.groupSize || 0);
  }
  if (!/^\d+$/.test(payload || "")) return 0;
  if (typeof requiredDoubleBlockLessons !== "function") return 1;
  return requiredDoubleBlockLessons(Number(payload)).length;
}

function tapAssignDefaultMoveScope(payload) {
  if (!/^\d+$/.test(payload || "")) return null;
  const lesson = data?.lessons?.find((item) => Number(item.id) === Number(payload));
  const assignment = lesson
    ? data?.assignments?.find(
      (item) => Number(item.id) === Number(lesson.assignment_id),
    )
    : null;
  return assignment?.block_mode === "required_double" ? "group" : "single";
}

function tapAssignNeedsMoveScope(_payload) {
  // Scope is no longer user-selectable. required_double always moves the persisted block; all other assignments move one lesson.
  return false;
}

function tapAssignInstruction(payload) {
  const capabilities = tapAssignCapabilities(payload);
  if (capabilities.schedule && capabilities.tray) {
    const clusterSize = tapAssignClusterSize(payload);
    if (clusterSize > 1 && activeTapAssign?.moveScope === "group")
      return `Bắt buộc tiết đôi: bấm ô bắt đầu để chuyển cả block ${clusterSize} tiết`;
    return "Bấm ô trên lịch để chuyển, hoặc bấm khay để thu hồi";
  }
  if (capabilities.tray) return "Bấm vào khay để thu hồi";
  const pendingBlockSize = Number(activeTapAssign?.groupSize || 0);
  if (pendingBlockSize > 1)
    return `Bấm ô bắt đầu để xếp block ${pendingBlockSize} tiết liên tiếp`;
  return "Bấm một ô được đánh dấu để xếp";
}

function syncTapAssignSelectionHighlight() {
  document
    .querySelectorAll(".selected-for-assign")
    .forEach((el) => el.classList.remove("selected-for-assign"));
  if (!activeTapAssign) return;
  const payload = activeTapAssign.payload;
  const direct = [...document.querySelectorAll("[data-tap-payload]")].filter(
    (el) => el.dataset.tapPayload === payload,
  );
  direct.forEach((el) => el.classList.add("selected-for-assign"));

  if (!/^\d+$/.test(payload || "")) return;
  const run = requiredDoubleBlockLessons(Number(payload));
  if (run.length <= 1 || activeTapAssign.moveScope === "single") return;
  const ids = new Set(run.map((row) => String(row.id)));
  document.querySelectorAll(".lesson[data-tap-payload]").forEach((el) => {
    if (ids.has(el.dataset.tapPayload)) el.classList.add("selected-for-assign");
  });
}

function renderTapAssignBar() {
  if (!activeTapAssign) return;
  let bar = document.getElementById("tapAssignBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "tapAssignBar";
    bar.className = "tap-assign-bar";
    document.body.appendChild(bar);
  }
  const payload = activeTapAssign.payload;
  const label = getPayloadLabel(payload);
  const clusterSize = tapAssignClusterSize(payload);
  const scopeControls =
    clusterSize > 1 && activeTapAssign.moveScope === "group"
      ? `<div class="tap-assign-scope" aria-label="Phạm vi di chuyển">
          <span class="is-active">Cả block (${clusterSize})</span>
        </div>`
      : "";
  bar.innerHTML = `
    <div class="tap-assign-bar-info">
      <span class="tap-assign-pulse-dot" aria-hidden="true"></span>
      <span>Đang chọn: <b>${esc(label)}</b> · ${esc(tapAssignInstruction(payload))}</span>
    </div>
    ${scopeControls}
    <button type="button" data-tap-assign-cancel>Hủy</button>
  `;
  requestAnimationFrame(syncTapAssignClearance);
}

function selectTapMoveScope(scope) {
  if (!activeTapAssign || !tapAssignNeedsMoveScope(activeTapAssign.payload)) return;
  if (scope !== "single" && scope !== "group") return;
  activeTapAssign.moveScope = scope;
  const workspace = document.querySelector(".workspace");
  workspace?.classList.remove("placement-scope-pending");
  syncTapAssignSelectionHighlight();
  renderTapAssignBar();
  loadPlacementOptionsForTap(activeTapAssign.payload, scope);
}

function handleTapToSelect(source, payload) {
  if (window.READ_ONLY || !source || !payload) return;
  if (activeTapAssign?.payload === payload) {
    clearTapAssign();
    return;
  }

  clearTapAssign();
  const capabilities = tapAssignCapabilities(payload);
  const needsScope = false;
  activeTapAssign = {
    payload,
    moveScope: tapAssignDefaultMoveScope(payload),
    placementLoading: false,
    validSlots: null,
    placementMessage: "",
    groupSize: 0,
  };
  syncTapAssignSelectionHighlight();
  markScheduleAvoidSlots();

  const workspace = document.querySelector(".workspace");
  workspace?.classList.add("is-assign-mode");
  workspace?.classList.toggle("tap-target-schedule", capabilities.schedule);
  workspace?.classList.toggle("tap-target-tray", capabilities.tray);
  workspace?.classList.toggle("placement-scope-pending", needsScope);

  renderTapAssignBar();
  document.body.classList.add("tap-assign-active");

  if (capabilities.schedule && !needsScope) {
    loadPlacementOptionsForTap(payload, activeTapAssign.moveScope);
  }
}

async function finishTapAssignToSchedule(slot) {
  if (!activeTapAssign || !Number.isInteger(slot)) return;
  const payload = activeTapAssign.payload;
  if (!tapAssignCapabilities(payload).schedule) {
    showToast("Phân công này chỉ có thể đưa về khay.", "warning", 2800);
    return;
  }
  const succeeded = await placeLessonPayload(payload, slot);
  if (succeeded && activeTapAssign?.payload === payload) clearTapAssign();
}

async function finishTapAssignToTray() {
  if (!activeTapAssign) return;
  const payload = activeTapAssign.payload;
  if (!tapAssignCapabilities(payload).tray) {
    showToast("Tiết chưa xếp cần được chọn một ô trên lịch.", "warning", 2800);
    return;
  }
  const succeeded = await returnPayloadToTray(payload);
  if (succeeded && activeTapAssign?.payload === payload) clearTapAssign();
}

document.addEventListener("click", (event) => {
  const cancel = event.target.closest("[data-tap-assign-cancel]");
  if (cancel) {
    event.preventDefault();
    clearTapAssign();
    return;
  }

  const scopeButton = event.target.closest("[data-tap-move-scope]");
  if (scopeButton) {
    event.preventDefault();
    selectTapMoveScope(scopeButton.dataset.tapMoveScope);
    return;
  }

  if (
    window.READ_ONLY ||
    event.target.closest("button,a,input,select,textarea,label")
  )
    return;

  const avoided = event.target.closest(".cell.available[data-avoid-reason]");
  if (avoided) {
    event.preventDefault();
    showToast(avoided.dataset.avoidReason, "warning", 4200);
    return;
  }

  const source = event.target.closest("[data-tap-payload]");
  const sourcePayload = source?.dataset.tapPayload || "";

  if (!activeTapAssign) {
    if (sourcePayload) {
      event.preventDefault();
      handleTapToSelect(source, sourcePayload);
    }
    return;
  }

  if (sourcePayload && sourcePayload === activeTapAssign.payload) {
    event.preventDefault();
    clearTapAssign();
    return;
  }

  // Cards in the assignment trays are always selectable sources. Prioritize
  // switching selection over treating the whole tray as a destination.
  if (
    sourcePayload &&
    (source.classList.contains("tray-lesson") ||
      source.classList.contains("scheduled-assignment"))
  ) {
    event.preventDefault();
    handleTapToSelect(source, sourcePayload);
    return;
  }

  const lockedCell = event.target.closest(
    ".cell.available[data-slot].global-locked-slot",
  );
  if (lockedCell) {
    event.preventDefault();
    showPlacementConflict(
      Number(lockedCell.dataset.slot),
      "Tiết này đã bị khóa toàn trường và không được xếp.",
    );
    return;
  }

  const cell = event.target.closest(
    ".cell.available[data-slot]:not(.global-locked-slot)",
  );
  if (cell) {
    event.preventDefault();
    finishTapAssignToSchedule(Number(cell.dataset.slot));
    return;
  }

  const tray = event.target.closest(".unscheduled-tray");
  if (tray) {
    event.preventDefault();
    finishTapAssignToTray();
    return;
  }

  if (sourcePayload) {
    event.preventDefault();
    handleTapToSelect(source, sourcePayload);
    return;
  }

  if (!event.target.closest("#tapAssignBar")) clearTapAssign();
});

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key === "Escape" && activeTapAssign) {
      event.preventDefault();
      clearTapAssign();
    }
  },
  { capture: true },
);

window.addEventListener("beforeprint", () => {
  const scheduleGrid = document.querySelector("#scheduleGrid");
  if (scheduleGrid && !scheduleGrid.querySelector(".timetable"))
    renderSchedule();
});

function syncWorkspaceViewportMetrics() {
  const appbar = document.querySelector(".appbar");
  const height = appbar ? Math.ceil(appbar.getBoundingClientRect().height) : 64;
  document.documentElement.style.setProperty(
    "--workspace-appbar-height",
    `${Math.max(0, height)}px`,
  );
}

syncWorkspaceViewportMetrics();
window.addEventListener("resize", syncWorkspaceViewportMetrics, { passive: true });
window.addEventListener("resize", syncTapAssignClearance, { passive: true });
window.addEventListener("orientationchange", syncWorkspaceViewportMetrics, {
  passive: true,
});
window.addEventListener("orientationchange", syncTapAssignClearance, {
  passive: true,
});

const SIDEBAR_DESKTOP_MEDIA = "(min-width: 901px)";

function syncSidebarCollapseForViewport() {
  const ws = document.querySelector(".workspace");
  if (!ws) return;
  const desktop = window.matchMedia(SIDEBAR_DESKTOP_MEDIA).matches;
  const btn = document.getElementById("sidebarCollapseBtn");

  if (!desktop) {
    ws.classList.remove("sidebar-collapsed");
    if (btn) {
      btn.title = "Thu gọn danh mục";
      btn.setAttribute("aria-label", btn.title);
    }
    return;
  }

  let shouldCollapse = false;
  try {
    shouldCollapse = localStorage.getItem("smart_tkb_sidebar_collapsed") === "1";
  } catch (e) { }
  ws.classList.toggle("sidebar-collapsed", shouldCollapse);
  if (btn) {
    btn.title = shouldCollapse ? "Mở rộng danh mục" : "Thu gọn danh mục";
    btn.setAttribute("aria-label", btn.title);
  }
}

function toggleSidebarCollapse() {
  const ws = document.querySelector(".workspace");
  if (!ws) return;

  // Mobile navigation is horizontal and must never enter the collapsed
  // desktop state, even if that state was saved previously.
  if (!window.matchMedia(SIDEBAR_DESKTOP_MEDIA).matches) {
    ws.classList.remove("sidebar-collapsed");
    return;
  }

  const isCollapsed = ws.classList.toggle("sidebar-collapsed");
  try {
    localStorage.setItem("smart_tkb_sidebar_collapsed", isCollapsed ? "1" : "0");
  } catch (e) { }
  const btn = document.getElementById("sidebarCollapseBtn");
  if (btn) {
    btn.title = isCollapsed ? "Mở rộng danh mục" : "Thu gọn danh mục";
    btn.setAttribute("aria-label", btn.title);
  }
}

document.addEventListener("DOMContentLoaded", syncSidebarCollapseForViewport);
window.addEventListener("resize", syncSidebarCollapseForViewport);

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const cell = event.target.closest(".cell.available[data-avoid-reason]");
  if (!cell) return;
  event.preventDefault();
  showToast(cell.dataset.avoidReason, "warning", 4200);
});
