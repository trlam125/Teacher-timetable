(() => {
  "use strict";

  if (typeof HTMLDialogElement === "undefined") return;

  const proto = HTMLDialogElement.prototype;
  const nativeShowModal = proto.showModal;
  const nativeClose = proto.close;
  if (typeof nativeShowModal !== "function" || typeof nativeClose !== "function") return;
  if (proto.__smartTkbAppZoomInstalled) return;

  Object.defineProperty(proto, "__smartTkbAppZoomInstalled", {
    value: true,
    configurable: false,
    enumerable: false,
    writable: false,
  });

  const states = new WeakMap();
  let lastTrigger = null;
  const OPEN_TRIGGER_TTL = 1800;
  const OPEN_DURATION = 320;
  const CLOSE_DURATION = 320;
  const OPEN_EASING = "cubic-bezier(0.16, 1, 0.3, 1)";
  const CLOSE_EASING = "cubic-bezier(0.2, 0.9, 0.3, 1)";
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  function isEffectsDisabled() {
    return (
      Boolean(reducedMotion?.matches) ||
      document.documentElement.classList.contains("disable-effects") ||
      localStorage.getItem("disable_effects") === "true"
    );
  }

  function isEligible(dialog) {
    return dialog instanceof HTMLDialogElement && dialog.hasAttribute("data-app-zoom");
  }

  function snapshotRect(element) {
    if (!(element instanceof Element)) return null;
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
      centerX: rect.left + rect.width / 2,
      centerY: rect.top + rect.height / 2,
    };
  }

  function rememberTrigger(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const trigger = target.closest(
      'button, [role="button"], input[type="button"], input[type="submit"], summary, .appbar-datetime',
    );
    if (!trigger || trigger.closest("dialog")) return;

    const rect = snapshotRect(trigger);
    if (!rect) return;

    lastTrigger = {
      element: trigger,
      rect,
      time: performance.now(),
    };
  }

  document.addEventListener("pointerdown", rememberTrigger, true);
  document.addEventListener(
    "click",
    (event) => {
      // Keyboard activation has no pointerdown. Capture it here before inline onclick runs.
      if (event.detail === 0) rememberTrigger(event);
    },
    true,
  );

  function recentTriggerRect() {
    if (!lastTrigger) return null;
    if (performance.now() - lastTrigger.time > OPEN_TRIGGER_TTL) return null;
    return { ...lastTrigger.rect };
  }

  function transformToTrigger(dialogRect, triggerRect) {
    const dx = triggerRect.centerX - (dialogRect.left + dialogRect.width / 2);
    const dy = triggerRect.centerY - (dialogRect.top + dialogRect.height / 2);

    let rawScaleX = triggerRect.width / Math.max(dialogRect.width, 1);
    let rawScaleY = triggerRect.height / Math.max(dialogRect.height, 1);

    // Keep scale proportional so narrow pill buttons don't brutally squash dialog into 4% height
    const scaleX = clamp(rawScaleX, 0.12, 0.95);
    const scaleY = clamp(Math.max(rawScaleY, scaleX * 0.42), 0.12, 0.95);

    return {
      transform: `translate3d(${dx}px, ${dy}px, 0) scale(${scaleX}, ${scaleY})`,
    };
  }

  function cleanDialog(dialog) {
    dialog.classList.remove("app-zoom-active", "app-zoom-closing");
    dialog.style.removeProperty("transform-origin");
    dialog.style.removeProperty("will-change");
    dialog.style.removeProperty("overflow");
    dialog.style.removeProperty("opacity");
  }

  function attachCancelHandler(dialog) {
    if (dialog.dataset.appZoomCancelBound === "1") return;
    dialog.dataset.appZoomCancelBound = "1";

    dialog.addEventListener("cancel", (event) => {
      if (!isEligible(dialog)) return;
      const state = states.get(dialog);
      if (!state?.triggerRect || isEffectsDisabled()) return;
      event.preventDefault();
      dialog.close();
    });

    dialog.addEventListener("close", () => {
      const state = states.get(dialog);
      state?.animation?.cancel?.();
      states.delete(dialog);
      cleanDialog(dialog);
    });
  }

  proto.showModal = function (...args) {
    if (!isEligible(this) || isEffectsDisabled()) {
      return nativeShowModal.apply(this, args);
    }

    attachCancelHandler(this);
    const triggerRect = recentTriggerRect();
    const triggerElement = lastTrigger?.element || null;

    // Prevent any 1-frame unstyled flash before Web Animation takes over
    this.style.opacity = "0";
    const result = nativeShowModal.apply(this, args);

    if (!triggerRect) {
      this.style.removeProperty("opacity");
      return result;
    }

    const dialogRect = this.getBoundingClientRect();
    if (!dialogRect.width || !dialogRect.height) {
      this.style.removeProperty("opacity");
      return result;
    }

    const start = transformToTrigger(dialogRect, triggerRect);

    this.classList.add("app-zoom-active");
    this.style.transformOrigin = "center center";
    this.style.willChange = "transform, opacity";
    this.style.overflow = "hidden";
    this.style.removeProperty("opacity");

    // Pure GPU composited transform & opacity: zero CPU rasterization repaints per frame
    const animation = this.animate(
      [
        {
          opacity: 0,
          transform: start.transform,
        },
        {
          opacity: 1,
          transform: "translate3d(0, 0, 0) scale(1, 1)",
        },
      ],
      {
        duration: OPEN_DURATION,
        easing: OPEN_EASING,
        fill: "both",
      },
    );

    states.set(this, {
      triggerElement,
      triggerRect,
      animation,
      closing: false,
    });

    animation.addEventListener(
      "finish",
      () => {
        const state = states.get(this);
        if (!state || state.animation !== animation || state.closing) return;
        this.classList.remove("app-zoom-active");
        this.style.removeProperty("overflow");
        this.style.removeProperty("will-change");
        this.style.removeProperty("transform-origin");
        animation.cancel();
        state.animation = null;
      },
      { once: true },
    );

    return result;
  };

  proto.close = function (returnValue = "") {
    if (!isEligible(this) || !this.open || isEffectsDisabled()) {
      return nativeClose.call(this, returnValue);
    }

    const state = states.get(this);
    if (!state?.triggerRect || state.closing) {
      return nativeClose.call(this, returnValue);
    }

    state.closing = true;
    this.classList.add("app-zoom-active", "app-zoom-closing");

    let currentTriggerRect = state.triggerRect;
    if (state.triggerElement && state.triggerElement.isConnected) {
      const refreshedRect = snapshotRect(state.triggerElement);
      if (refreshedRect) currentTriggerRect = refreshedRect;
    }

    const computed = getComputedStyle(this);
    const currentTransform = computed.transform === "none" ? "translate3d(0, 0, 0) scale(1)" : computed.transform;
    const currentOpacity = Number.parseFloat(computed.opacity || "1");
    state.animation?.cancel?.();

    const dialogRect = this.getBoundingClientRect();
    const target = transformToTrigger(dialogRect, currentTriggerRect);

    this.style.overflow = "hidden";
    this.style.transformOrigin = "center center";
    this.style.willChange = "transform, opacity";

    // Pure GPU composited closing animation
    const animation = this.animate(
      [
        {
          opacity: Number.isFinite(currentOpacity) ? currentOpacity : 1,
          transform: currentTransform,
        },
        {
          opacity: 0,
          transform: target.transform,
        },
      ],
      {
        duration: CLOSE_DURATION,
        easing: CLOSE_EASING,
        fill: "both",
      },
    );
    state.animation = animation;

    // Trigger visual absorb reaction on the button as the dialog converges into it
    if (state.triggerElement && state.triggerElement.isConnected) {
      const triggerEl = state.triggerElement;
      setTimeout(() => {
        triggerEl.classList.add("btn-absorb-pulse");
        setTimeout(() => triggerEl.classList.remove("btn-absorb-pulse"), 380);
      }, Math.max(0, CLOSE_DURATION - 80));
    }

    const finishClose = () => {
      if (!this.open) return;
      animation.cancel();
      cleanDialog(this);
      states.delete(this);
      nativeClose.call(this, returnValue);
    };

    animation.addEventListener("finish", finishClose, { once: true });
    animation.addEventListener("cancel", () => { }, { once: true });

    return undefined;
  };
})();
