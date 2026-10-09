const actionStateTimers = new WeakMap();
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function actionStateMarkup(state, label) {
  if (state === "loading")
    return `<svg class="inline-action-icon inline-action-spinner" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.9-4"></path><polyline points="5 3 5 7 9 7"></polyline><path d="M4 13a8 8 0 0 0 14.9 4"></path><polyline points="19 21 19 17 15 17"></polyline></svg><span>${esc(label)}</span>`;
  if (state === "success")
    return `<svg class="inline-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg><span>${esc(label)}</span>`;
  if (state === "error")
    return `<svg class="inline-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5"></path><path d="M12 17h.01"></path><circle cx="12" cy="12" r="9"></circle></svg><span>${esc(label)}</span>`;
  return `<span>${esc(label)}</span>`;
}
function ensureInlineActionButton(button) {
  if (!button) return null;
  button.classList.add("inline-action-btn");
  let stage = button.querySelector(":scope > .inline-action-stage");
  if (stage) return stage;
  const idle = (button.textContent || "").trim() || "Thực hiện";
  button.dataset.actionIdleLabel = button.dataset.actionIdleLabel || idle;
  button.textContent = "";
  stage = document.createElement("span");
  stage.className = "inline-action-stage";
  const content = document.createElement("span");
  content.className = "inline-action-content";
  content.textContent = idle;
  stage.appendChild(content);
  button.appendChild(stage);
  return stage;
}
function setInlineActionState(button, state, labels = {}, resetAfter = 0) {
  const stage = ensureInlineActionButton(button);
  if (!stage) return;
  const previousTimer = actionStateTimers.get(button);
  if (previousTimer) clearTimeout(previousTimer);
  const idle = labels.idle || button.dataset.actionIdleLabel || "Thực hiện";
  const defaults = {
    loading: "Đang xử lý...",
    success: "Đã hoàn tất",
    error: "Chưa hoàn tất",
  };
  const label =
    state === "idle" ? idle : labels[state] || defaults[state] || idle;
  stage
    .querySelectorAll(".inline-action-content.inline-action-leaving")
    .forEach((node) => node.remove());
  const current = stage.querySelector(".inline-action-content");
  const next = document.createElement("span");
  next.className = `inline-action-content inline-action-enter inline-action-${state}`;
  next.innerHTML = actionStateMarkup(state, label);
  if (current) {
    current.classList.add("inline-action-leaving");
    const cleanup = () => current.remove();
    current.addEventListener("animationend", cleanup, { once: true });
    setTimeout(cleanup, 360);
  }
  stage.appendChild(next);
  button.dataset.actionState = state;
  button.disabled = state === "loading";
  button.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  if (resetAfter > 0) {
    const timer = setTimeout(
      () => setInlineActionState(button, "idle", { idle }),
      resetAfter,
    );
    actionStateTimers.set(button, timer);
  }
}
function showInlineActionFeedback(
  button,
  message,
  kind = "info",
  timeout = 4200,
) {
  if (!button) return;
  let feedback = button.parentElement?.querySelector(
    ":scope > .inline-action-feedback",
  );
  if (!message) {
    if (feedback) feedback.hidden = true;
    return;
  }
  if (!feedback) {
    feedback = document.createElement("span");
    feedback.className = "inline-action-feedback";
    button.insertAdjacentElement("afterend", feedback);
  }
  feedback.className = `inline-action-feedback is-${kind}`;
  feedback.textContent = String(message);
  feedback.hidden = false;
  if (timeout > 0)
    setTimeout(() => {
      if (feedback.isConnected) feedback.hidden = true;
    }, timeout);
}
function setScheduleFeedback(message, kind = "info", timeout = 4200) {
  // Không chèn trạng thái cạnh nút Xếp tự động nữa. Mọi kết quả được đưa vào
  // toast ở góc trên bên phải để nội dung trang không bị dịch/chèn thêm dòng.
  document
    .querySelectorAll("[data-schedule-action]")
    .forEach((button) => {
      const feedback = button.parentElement?.querySelector(
        ":scope > .inline-action-feedback",
      );
      if (feedback) feedback.hidden = true;
    });
  if (message) showToast(message, kind, timeout);
}
function setTrayActionStatus(state, message, resetAfter = 0) {
  // Trạng thái hoàn tất/lỗi của thao tác khay dùng toast thay cho dòng chữ
  // nằm trong panel. Loading đã được thể hiện ngay trên nút/thao tác hiện tại.
  const status = $("#trayActionStatus");
  if (status) status.hidden = true;
  if (!message || state === "loading") return;
  showToast(
    message,
    state === "success" ? "success" : state === "error" ? "error" : "info",
    resetAfter || 3600,
  );
}
function setEntityActionMessage(message, kind = "error") {
  const form = entityModal?.querySelector("form");
  if (!form) return;
  let node = form.querySelector("#entityActionMessage");
  if (!node) {
    node = document.createElement("p");
    node.id = "entityActionMessage";
    node.className = "inline-form-message";
    form.querySelector(".row.end")?.insertAdjacentElement("beforebegin", node);
  }
  if (!message) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  node.hidden = false;
  node.className = `inline-form-message is-${kind}`;
  node.textContent = String(message);
}
function entityActionError(button, message) {
  setInlineActionState(
    button,
    "error",
    { idle: "Lưu", error: "Kiểm tra lại" },
    1800,
  );
  setEntityActionMessage(message, "error");
}
let scheduleActionTimer = null;
let scheduleActionVersion = 0;
function scheduleActionMarkup(state) {
  if (state === "loading")
    return `<svg class="schedule-action-icon schedule-action-spinner" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.9-4"></path><polyline points="5 3 5 7 9 7"></polyline><path d="M4 13a8 8 0 0 0 14.9 4"></path><polyline points="19 21 19 17 15 17"></polyline></svg><span>Đang xếp...</span>`;
  if (state === "success")
    return `<svg class="schedule-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg><span>Đã xếp xong</span>`;
  if (state === "error")
    return `<svg class="schedule-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5"></path><path d="M12 17h.01"></path><circle cx="12" cy="12" r="9"></circle></svg><span>Chưa xếp được</span>`;
  return '<span class="schedule-action-label">Xếp tự động</span>';
}
function setScheduleActionState(state, resetAfter = 0) {
  scheduleActionVersion += 1;
  const version = scheduleActionVersion;
  if (scheduleActionTimer) {
    clearTimeout(scheduleActionTimer);
    scheduleActionTimer = null;
  }
  document.querySelectorAll("[data-schedule-action]").forEach((button) => {
    const stage = button.querySelector(".schedule-action-stage");
    if (!stage) return;
    stage
      .querySelectorAll(".schedule-action-content.schedule-action-leaving")
      .forEach((node) => node.remove());
    const current = stage.querySelector(".schedule-action-content");
    const next = document.createElement("span");
    next.className = `schedule-action-content schedule-action-enter schedule-action-${state}`;
    next.innerHTML = scheduleActionMarkup(state);
    if (current) {
      current.classList.add("schedule-action-leaving");
      const cleanup = () => current.remove();
      current.addEventListener("animationend", cleanup, { once: true });
      setTimeout(cleanup, 360);
    }
    stage.appendChild(next);
    button.dataset.scheduleState = state;
    button.disabled = state === "loading";
    button.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  });
  if (resetAfter > 0)
    scheduleActionTimer = setTimeout(() => {
      if (version === scheduleActionVersion) setScheduleActionState("idle");
    }, resetAfter);
}
function launchConfetti() {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;

  document.querySelectorAll(".schedule-confetti-canvas").forEach((node) =>
    node.remove(),
  );
  const canvas = document.createElement("canvas");
  canvas.className = "schedule-confetti-canvas";
  canvas.style.position = "fixed";
  canvas.style.inset = "0";
  canvas.style.width = "100vw";
  canvas.style.height = "100vh";
  canvas.style.pointerEvents = "none";
  canvas.style.zIndex = "999";
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    canvas.remove();
    return;
  }

  let width = 0;
  let height = 0;
  const resizeCanvas = () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  };
  resizeCanvas();
  window.addEventListener("resize", resizeCanvas, { passive: true });

  const colors = [
    "#2563eb",
    "#06b6d4",
    "#10b981",
    "#f5b83d",
    "#ec4899",
    "#8b5cf6",
  ];
  const particles = [];
  for (let i = 0; i < 120; i++) {
    particles.push({
      x: Math.random() * width,
      y: Math.random() * height - height,
      r: Math.random() * 6 + 4,
      d: Math.random() * width,
      color: colors[Math.floor(Math.random() * colors.length)],
      tilt: Math.random() * 10 - 5,
      tiltAngleIncremental: Math.random() * 0.07 + 0.02,
      tiltAngle: 0,
      velocity: Math.random() * 3 + 2,
    });
  }

  let animationFrameId = null;
  const startedAt = performance.now();
  const cleanup = () => {
    if (animationFrameId != null) cancelAnimationFrame(animationFrameId);
    window.removeEventListener("resize", resizeCanvas);
    canvas.remove();
  };
  function draw(now) {
    if (!canvas.isConnected) {
      cleanup();
      return;
    }
    ctx.clearRect(0, 0, width, height);
    let active = false;
    for (const particle of particles) {
      particle.tiltAngle += particle.tiltAngleIncremental;
      particle.y +=
        ((Math.cos(particle.d) + 3 + particle.r / 2) / 2) *
        particle.velocity *
        0.7;
      particle.x += Math.sin(particle.tiltAngle) * 0.5;
      if (particle.y < height) active = true;
      ctx.beginPath();
      ctx.lineWidth = particle.r;
      ctx.strokeStyle = particle.color;
      ctx.moveTo(particle.x + particle.r / 2 + particle.tilt, particle.y);
      ctx.lineTo(
        particle.x + particle.tilt,
        particle.y + particle.tilt + particle.r / 2,
      );
      ctx.stroke();
    }
    if (active && now - startedAt < 3500)
      animationFrameId = requestAnimationFrame(draw);
    else cleanup();
  }
  animationFrameId = requestAnimationFrame(draw);
}

