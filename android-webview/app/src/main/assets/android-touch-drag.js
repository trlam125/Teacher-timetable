(function () {
  if (window.__smartTkbAndroidTouchDrag) return;
  window.__smartTkbAndroidTouchDrag = true;

  const HOLD_DELAY = 320;
  const MOVE_CANCEL_DISTANCE = 12;
  const DROP_SELECTOR = '.cell.available[data-slot],.unscheduled-tray';
  let pending = null;
  let dragging = null;
  let holdTimer = null;
  let activeDropTarget = null;

  function dragValue(element) {
    const handler = element.getAttribute('ondragstart') || '';
    const match = handler.match(/setData\([^,]+,\s*['"]([^'"]+)['"]\s*\)/);
    return match ? match[1] : '';
  }

  function markDraggable(element) {
    if (!(element instanceof Element) || element.getAttribute('draggable') !== 'true') return;
    const value = dragValue(element);
    if (!value) return;
    element.dataset.androidDragValue = value;
    element.draggable = false;
  }

  function scan(root) {
    if (!(root instanceof Element) && root !== document) return;
    if (root instanceof Element) markDraggable(root);
    root.querySelectorAll('[draggable="true"]').forEach(markDraggable);
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
    if (activeDropTarget) activeDropTarget.classList.remove('android-touch-drop-target');
    activeDropTarget = null;
  }

  function cleanup() {
    clearTimeout(holdTimer);
    holdTimer = null;
    clearDropTarget();
    if (dragging) {
      dragging.source.classList.remove('dragging');
      dragging.ghost.remove();
    }
    document.body.classList.remove('is-dragging', 'android-touch-dragging');
    pending = null;
    dragging = null;
  }

  function moveGhost(x, y) {
    if (!dragging) return;
    dragging.ghost.style.left = (x - dragging.offsetX) + 'px';
    dragging.ghost.style.top = (y - dragging.offsetY) + 'px';
  }

  function beginDrag(touch) {
    if (!pending || !pending.source.isConnected) return;
    const rect = pending.source.getBoundingClientRect();
    const ghost = pending.source.cloneNode(true);
    ghost.classList.add('android-touch-ghost');
    ghost.style.width = rect.width + 'px';
    ghost.style.height = rect.height + 'px';
    document.body.appendChild(ghost);

    dragging = {
      source: pending.source,
      value: pending.value,
      ghost: ghost,
      scrollArea: pending.source.closest('.timetable,.unscheduled-tray,.scheduled-cards'),
      offsetX: Math.max(10, Math.min(touch.clientX - rect.left, rect.width - 10)),
      offsetY: Math.max(10, Math.min(touch.clientY - rect.top, rect.height - 10))
    };
    pending.source.classList.add('dragging');
    document.body.classList.add('is-dragging', 'android-touch-dragging');
    moveGhost(touch.clientX, touch.clientY);
  }

  function updateDropTarget(x, y) {
    const element = document.elementFromPoint(x, y);
    const target = element ? element.closest(DROP_SELECTOR) : null;
    if (target === activeDropTarget) return;
    clearDropTarget();
    activeDropTarget = target;
    if (activeDropTarget) activeDropTarget.classList.add('android-touch-drop-target');
  }

  function autoScroll(x, y) {
    if (!dragging) return;
    const margin = 64;
    const step = 18;
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
    return { dataTransfer: { getData: function () { return value; } } };
  }

  function finishDrop(target, value) {
    if (!target) {
      if (typeof window.toast === 'function') window.toast('Hãy thả tiết vào một ô lịch hợp lệ.');
      return;
    }
    if (target.classList.contains('available')) {
      const slot = Number(target.dataset.slot);
      if (Number.isFinite(slot) && typeof window.dropLesson === 'function') {
        window.dropLesson(fakeDragEvent(value), slot);
      }
      return;
    }
    if (target.classList.contains('unscheduled-tray') && typeof window.dropToTray === 'function') {
      window.dropToTray(fakeDragEvent(value));
    }
  }

  document.addEventListener('touchstart', function (event) {
    if (event.touches.length !== 1) return;
    if (event.target.closest('button,a,input,select,textarea')) return;
    const source = event.target.closest('[data-android-drag-value]');
    if (!source) return;
    const touch = event.touches[0];
    pending = {
      source: source,
      value: source.dataset.androidDragValue,
      startX: touch.clientX,
      startY: touch.clientY,
      touch: touch
    };
    clearTimeout(holdTimer);
    holdTimer = setTimeout(function () {
      if (pending) beginDrag(pending.touch);
    }, HOLD_DELAY);
  }, { passive: true });

  document.addEventListener('touchmove', function (event) {
    if (event.touches.length !== 1) return;
    const touch = event.touches[0];
    if (!dragging && pending) {
      const distance = Math.hypot(touch.clientX - pending.startX, touch.clientY - pending.startY);
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
    moveGhost(touch.clientX, touch.clientY);
    updateDropTarget(touch.clientX, touch.clientY);
    autoScroll(touch.clientX, touch.clientY);
  }, { passive: false });

  document.addEventListener('touchend', function (event) {
    clearTimeout(holdTimer);
    holdTimer = null;
    if (!dragging) {
      pending = null;
      return;
    }
    event.preventDefault();
    const touch = event.changedTouches[0];
    const element = touch ? document.elementFromPoint(touch.clientX, touch.clientY) : null;
    const target = element ? element.closest(DROP_SELECTOR) : activeDropTarget;
    const value = dragging.value;
    cleanup();
    finishDrop(target, value);
  }, { passive: false });

  document.addEventListener('touchcancel', cleanup, { passive: true });
  document.addEventListener('contextmenu', function (event) {
    if (event.target.closest('[data-android-drag-value]')) event.preventDefault();
  });
})();
