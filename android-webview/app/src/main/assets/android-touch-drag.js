(function () {
  if (window.__smartTkbAndroidTouchDrag) return;
  window.__smartTkbAndroidTouchDrag = true;

  const HOLD_DELAY = 280;
  const MOVE_CANCEL_DISTANCE = 14;
  const DROP_SELECTOR =
    ".cell.available[data-slot],.unscheduled-tray,.day-slot-card[data-slot],.card-slot[data-slot]";
  const SNAP_RADIUS = 36;
  let pending = null;
  let dragging = null;
  let holdTimer = null;
  let activeDropTarget = null;

  function triggerHaptic(duration = 15) {
    try {
      if (
        window.AndroidBridge &&
        typeof window.AndroidBridge.vibrate === "function"
      ) {
        window.AndroidBridge.vibrate(duration);
      } else if (
        typeof navigator !== "undefined" &&
        typeof navigator.vibrate === "function"
      ) {
        navigator.vibrate(duration);
      }
    } catch (ignored) {}
  }

  function dragValue(element) {
    const handler = element.getAttribute("ondragstart") || "";
    const match = handler.match(/setData\([^,]+,\s*['"]([^'"]+)['"]\s*\)/);
    if (match) return match[1];
    return element.dataset.dragPayload
      ? String(element.dataset.dragPayload)
      : "";
  }

  function markDraggable(element) {
    if (!(element instanceof Element)) return;
    const isDraggableAttr =
      element.getAttribute("draggable") === "true" ||
      element.hasAttribute("data-drag-payload");
    if (!isDraggableAttr) return;
    const value = dragValue(element);
    if (!value) return;
    element.dataset.androidDragValue = value;
    element.draggable = false;
  }

  function scan(root) {
    if (!(root instanceof Element) && root !== document) return;
    if (root instanceof Element) markDraggable(root);
    root
      .querySelectorAll('[draggable="true"],[data-drag-payload]')
      .forEach(markDraggable);
  }

  scan(document);
  new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(function (node) {
        if (node instanceof Element) scan(node);
      });
    });
  }).observe(document.documentElement, { childList: true, subtree: true });

  function clearDropTarget() {
    if (activeDropTarget) {
      activeDropTarget.classList.remove(
        "android-touch-drop-target",
        "android-touch-snap-active",
      );
    }
    activeDropTarget = null;
  }

  function cleanup() {
    clearTimeout(holdTimer);
    holdTimer = null;
    clearDropTarget();
    if (dragging) {
      dragging.source.classList.remove("dragging");
      if (dragging.ghost && dragging.ghost.parentNode) dragging.ghost.remove();
    }
    document.body.classList.remove("is-dragging", "android-touch-dragging");
    pending = null;
    dragging = null;
  }

  function moveGhost(x, y) {
    if (!dragging) return;
    let targetX = x - dragging.offsetX;
    let targetY = y - dragging.offsetY;

    // Hiệu ứng bám dính (magnetic snap-to-grid) khi di chuyển gần tâm ô nhận diện
    if (activeDropTarget) {
      const rect = activeDropTarget.getBoundingClientRect();
      const targetCenterX = rect.left + rect.width / 2;
      const targetCenterY = rect.top + rect.height / 2;
      const dist = Math.hypot(x - targetCenterX, y - targetCenterY);

      if (dist < 48) {
        // Hút nhẹ con trỏ về tâm ô mục tiêu
        const pull = Math.max(0, 1 - dist / 48) * 0.35;
        targetX += (rect.left - targetX) * pull;
        targetY += (rect.top - targetY) * pull;
      }
    }

    dragging.ghost.style.left = targetX + "px";
    dragging.ghost.style.top = targetY + "px";
  }

  function beginDrag(touch) {
    if (!pending || !pending.source.isConnected) return;
    const rect = pending.source.getBoundingClientRect();
    const ghost = pending.source.cloneNode(true);
    ghost.classList.add("android-touch-ghost");
    ghost.style.width = rect.width + "px";
    ghost.style.height = rect.height + "px";
    document.body.appendChild(ghost);

    dragging = {
      source: pending.source,
      value: pending.value,
      ghost: ghost,
      scrollArea: pending.source.closest(
        ".timetable,.unscheduled-tray,.scheduled-cards,.day-card-container",
      ),
      offsetX: Math.max(
        10,
        Math.min(touch.clientX - rect.left, rect.width - 10),
      ),
      offsetY: Math.max(
        10,
        Math.min(touch.clientY - rect.top, rect.height - 10),
      ),
    };
    pending.source.classList.add("dragging");
    document.body.classList.add("is-dragging", "android-touch-dragging");
    triggerHaptic(20);
    moveGhost(touch.clientX, touch.clientY);
  }

  function findDropTargetAt(x, y) {
    let el = document.elementFromPoint(x, y);
    let target = el ? el.closest(DROP_SELECTOR) : null;
    if (target) return target;

    // Vùng thả mở rộng (Enlarged drop zone): Thử các điểm xung quanh trong bán kính SNAP_RADIUS
    const offsets = [
      [0, -SNAP_RADIUS],
      [0, SNAP_RADIUS],
      [-SNAP_RADIUS, 0],
      [SNAP_RADIUS, 0],
      [-SNAP_RADIUS * 0.7, -SNAP_RADIUS * 0.7],
      [SNAP_RADIUS * 0.7, SNAP_RADIUS * 0.7],
    ];
    for (const [dx, dy] of offsets) {
      el = document.elementFromPoint(x + dx, y + dy);
      target = el ? el.closest(DROP_SELECTOR) : null;
      if (target) return target;
    }
    return null;
  }

  function updateDropTarget(x, y) {
    const target = findDropTargetAt(x, y);
    if (target === activeDropTarget) return;

    clearDropTarget();
    activeDropTarget = target;
    if (activeDropTarget) {
      activeDropTarget.classList.add(
        "android-touch-drop-target",
        "android-touch-snap-active",
      );
      triggerHaptic(12); // Rung nhẹ khi bắt trúng ô hợp lệ
    }
  }

  function autoScroll(x, y) {
    if (!dragging) return;
    const margin = 56;
    const step = 16;
    const area = dragging.scrollArea;
    if (area) {
      const rect = area.getBoundingClientRect();
      if (x < rect.left + margin) area.scrollLeft -= step;
      else if (x > rect.right - margin) area.scrollLeft += step;
      if (y < rect.top + margin) area.scrollTop -= step;
      else if (y > rect.bottom - margin) area.scrollTop += step;
    }
    if (y < margin) window.scrollBy(0, -step);
    else if (y > window.innerHeight - margin) window.scrollBy(0, step);
  }

  function fakeDragEvent(value) {
    return {
      dataTransfer: {
        getData: function () {
          return value;
        },
      },
    };
  }

  function finishDrop(target, value) {
    if (!target) {
      triggerHaptic(40);
      if (typeof window.toast === "function")
        window.toast("Hãy thả tiết vào một ô lịch hợp lệ.");
      else if (typeof window.showToast === "function")
        window.showToast("Hãy thả tiết vào một ô lịch hợp lệ.", "warning");
      return;
    }

    triggerHaptic(30); // Rung thành công khi thả
    if (target.hasAttribute("data-slot")) {
      const slot = Number(target.dataset.slot);
      if (Number.isFinite(slot)) {
        if (typeof window.dropLessonPayload === "function") {
          window.dropLessonPayload(value, slot);
        } else if (typeof window.dropLesson === "function") {
          window.dropLesson(fakeDragEvent(value), slot);
        }
      }
      return;
    }
    if (
      target.classList.contains("unscheduled-tray") &&
      typeof window.dropToTray === "function"
    ) {
      window.dropToTray(fakeDragEvent(value));
    }
  }

  document.addEventListener(
    "touchstart",
    function (event) {
      if (event.touches.length !== 1) return;
      if (event.target.closest("button,a,input,select,textarea")) return;
      const source = event.target.closest("[data-android-drag-value]");
      if (!source) return;
      const touch = event.touches[0];
      pending = {
        source: source,
        value: source.dataset.androidDragValue,
        startX: touch.clientX,
        startY: touch.clientY,
        touch: touch,
      };
      clearTimeout(holdTimer);
      holdTimer = setTimeout(function () {
        if (pending) beginDrag(pending.touch);
      }, HOLD_DELAY);
    },
    { passive: true },
  );

  document.addEventListener(
    "touchmove",
    function (event) {
      if (event.touches.length !== 1) return;
      const touch = event.touches[0];
      if (!dragging && pending) {
        const distance = Math.hypot(
          touch.clientX - pending.startX,
          touch.clientY - pending.startY,
        );
        pending.touch = touch;
        if (distance > MOVE_CANCEL_DISTANCE) {
          clearTimeout(holdTimer);
          holdTimer = null;
          pending = null;
        }
        return;
      }
      if (!dragging) return;
      event.preventDefault();
      updateDropTarget(touch.clientX, touch.clientY);
      moveGhost(touch.clientX, touch.clientY);
      autoScroll(touch.clientX, touch.clientY);
    },
    { passive: false },
  );

  document.addEventListener(
    "touchend",
    function (event) {
      clearTimeout(holdTimer);
      holdTimer = null;
      if (!dragging) {
        pending = null;
        return;
      }
      event.preventDefault();
      const touch = event.changedTouches[0];
      const target =
        findDropTargetAt(touch.clientX, touch.clientY) || activeDropTarget;
      const value = dragging.value;
      cleanup();
      finishDrop(target, value);
    },
    { passive: false },
  );

  document.addEventListener("touchcancel", cleanup, { passive: true });
  document.addEventListener("contextmenu", function (event) {
    if (event.target.closest("[data-android-drag-value]"))
      event.preventDefault();
  });
})();
