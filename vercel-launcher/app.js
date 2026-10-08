(() => {
  const title = document.getElementById("statusTitle");
  const text = document.getElementById("statusText");
  const retry = document.getElementById("retryButton");
  const quoteEl = document.getElementById("schoolQuote");

  const STARTED_AT = Date.now();
  const RETRY_DELAY_MS = 1200;
  const SHOW_RETRY_AFTER_MS = 45000;
  let stopped = false;
  let timer = 0;

  // ==========================================
  // School Inspirational Quotes Cycler
  // ==========================================
  const schoolQuotes = [
    "Đồng hành cùng Thầy Cô và Học sinh trong từng tiết học",
    "Mỗi tiết học là một hành trình khám phá tri thức mới",
    "Tối ưu thời khóa biểu – Tiết kiệm thời gian cho nhà trường",
    "Chúc Thầy Cô và các em học sinh một ngày học tập thật hứng khởi!",
    "Phân bổ tiết dạy khoa học, giảng dạy thăng hoa và hiệu quả"
  ];
  let quoteIndex = 0;
  let quoteTimer = 0;

  function cycleQuote() {
    if (stopped || !quoteEl) return;
    quoteIndex = (quoteIndex + 1) % schoolQuotes.length;
    quoteEl.classList.add("is-fading");
    setTimeout(() => {
      if (stopped) return;
      quoteEl.textContent = schoolQuotes[quoteIndex];
      quoteEl.classList.remove("is-fading");
    }, 350);
  }

  quoteTimer = setInterval(cycleQuote, 4600);

  // ==========================================
  // Starlight & Chalk Dust Particle Canvas
  // ==========================================
  const canvas = document.getElementById("schoolDustCanvas");
  let ctx = null;
  let particles = [];
  let animFrameId = 0;
  let mouseX = window.innerWidth / 2;
  let mouseY = window.innerHeight / 2;
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (canvas && !prefersReducedMotion) {
    ctx = canvas.getContext("2d");

    function resizeCanvas() {
      if (!canvas) return;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas, { passive: true });

    class DustParticle {
      constructor() {
        this.reset(true);
      }
      reset(init = false) {
        if (!canvas) return;
        this.x = Math.random() * canvas.width;
        this.y = init ? Math.random() * canvas.height : canvas.height + 15;
        this.radius = Math.random() * 2.2 + 0.8;
        this.speedY = Math.random() * 0.45 + 0.2;
        this.speedX = (Math.random() - 0.5) * 0.25;
        this.opacity = Math.random() * 0.5 + 0.2;
        this.waveFreq = Math.random() * 0.02 + 0.01;
        this.waveAmp = Math.random() * 1.2 + 0.5;
        this.time = Math.random() * 100;
        // Warm gold, soft azure, gentle violet
        const colors = [
          "rgba(251, 191, 36, ",  // gold
          "rgba(96, 165, 250, ",  // sky blue
          "rgba(167, 139, 250, ", // soft violet
          "rgba(52, 211, 153, "   // mint
        ];
        this.colorPrefix = colors[Math.floor(Math.random() * colors.length)];
      }
      update() {
        this.time += this.waveFreq;
        this.y -= this.speedY;
        this.x += Math.sin(this.time) * this.waveAmp + this.speedX;

        // Subtle reaction to mouse
        const dx = mouseX - this.x;
        const dy = mouseY - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 100) {
          const force = (100 - dist) / 100;
          this.x -= (dx / dist) * force * 1.5;
          this.y -= (dy / dist) * force * 1.5;
        }

        if (this.y < -20 || this.x < -20 || (canvas && this.x > canvas.width + 20)) {
          this.reset(false);
        }
      }
      draw() {
        if (!ctx) return;
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        ctx.fillStyle = `${this.colorPrefix}${this.opacity})`;
        ctx.shadowColor = `${this.colorPrefix}0.6)`;
        ctx.shadowBlur = 6;
        ctx.fill();
      }
    }

    const count = Math.min(36, Math.floor(window.innerWidth / 30));
    for (let i = 0; i < count; i++) {
      particles.push(new DustParticle());
    }

    function renderParticles() {
      if (stopped || !ctx || !canvas) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.shadowBlur = 0;
      for (let i = 0; i < particles.length; i++) {
        particles[i].update();
        particles[i].draw();
      }
      animFrameId = requestAnimationFrame(renderParticles);
    }

    renderParticles();
  }

  // ==========================================
  // Mouse & Touch Parallax for School Floaters
  // ==========================================
  const floaters = document.querySelectorAll(".floater");
  if (floaters.length > 0 && !prefersReducedMotion) {
    let targetX = 0;
    let targetY = 0;
    let currentX = 0;
    let currentY = 0;
    let parallaxActive = true;

    window.addEventListener("mousemove", (e) => {
      mouseX = e.clientX;
      mouseY = e.clientY;
      const normX = (e.clientX / window.innerWidth) - 0.5;
      const normY = (e.clientY / window.innerHeight) - 0.5;
      targetX = normX * 36;
      targetY = normY * 36;
    }, { passive: true });

    function updateParallax() {
      if (stopped || !parallaxActive) return;
      currentX += (targetX - currentX) * 0.08;
      currentY += (targetY - currentY) * 0.08;

      floaters.forEach((el) => {
        const depth = parseFloat(el.getAttribute("data-depth") || "0.04");
        const px = (currentX * depth * 35).toFixed(2);
        const py = (currentY * depth * 35).toFixed(2);
        el.style.setProperty("--parallax-x", `${px}px`);
        el.style.setProperty("--parallax-y", `${py}px`);
      });

      requestAnimationFrame(updateParallax);
    }
    updateParallax();
  }

  // ==========================================
  // Backend Wakeup & Health Polling System
  // ==========================================
  function cleanNextPath() {
    const raw = new URLSearchParams(location.search).get("next") || "/";
    if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
    return raw;
  }

  function joinTarget(base, path) {
    const root = String(base || "").replace(/\/+$/, "");
    return root + (path.startsWith("/") ? path : "/" + path);
  }

  function setWaitingCopy() {
    const elapsed = Date.now() - STARTED_AT;
    if (elapsed > 15000) {
      text.textContent = "Đang khởi động máy chủ ...";
    }
    if (elapsed > SHOW_RETRY_AFTER_MS) retry.hidden = false;
  }

  async function checkBackend() {
    if (stopped) return;
    clearTimeout(timer);
    setWaitingCopy();

    try {
      const response = await fetch(`/api/health?t=${Date.now()}`, {
        method: "GET",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      const data = await response.json().catch(() => null);

      if (response.ok && data?.ready && data?.target) {
        stopped = true;
        clearInterval(quoteTimer);
        cancelAnimationFrame(animFrameId);
        retry.hidden = true;
        document.body.classList.add("is-ready");
        title.textContent = "Smart TKB đã sẵn sàng!";
        text.textContent = "Đang chuyển tiếp tới ứng dụng...";
        if (quoteEl) {
          quoteEl.textContent = "🎉 Chúc Thầy Cô và các bạn có buổi làm việc tuyệt vời!";
        }
        const destination = joinTarget(data.target, cleanNextPath());
        window.setTimeout(() => location.replace(destination), 280);
        return;
      }
    } catch (_) {
      // The launcher stays visible and retries instead of exposing a Render error page.
    }

    timer = window.setTimeout(checkBackend, RETRY_DELAY_MS);
  }

  retry.addEventListener("click", () => {
    retry.hidden = true;
    text.textContent = "Đang thử kết nối lại...";
    checkBackend();
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !stopped) checkBackend();
  });

  checkBackend();
})();
