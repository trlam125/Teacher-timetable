(() => {
  'use strict';

  // Check reduced motion preference
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReducedMotion) return;

  const canvas = document.createElement('canvas');
  canvas.className = 'auth-effects-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  canvas.id = 'authAtmosphereCanvas';

  // Append canvas to document.body so it floats over the entire page and forms
  function attachCanvas() {
    if (document.body.classList.contains('front-surface')) {
      canvas.style.zIndex = '0';
    }
    document.body.appendChild(canvas);
  }

  if (document.body) {
    attachCanvas();
  } else {
    document.addEventListener('DOMContentLoaded', attachCanvas);
  }

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  let width = 0;
  let height = 0;
  let dpr = 1;
  let isMobile = false;

  // Mode & Transition state
  let isDarkMode = document.documentElement.classList.contains('dark-mode');
  let snowOpacity = isDarkMode ? 1.0 : 0.0;
  let bubbleOpacity = isDarkMode ? 0.0 : 1.0;
  const FADE_SPEED = 0.045; // Smooth cross-fade speed (~400-500ms)

  // Mouse tracking for breeze & bubble interactions
  const mouse = {
    x: -9999,
    y: -9999,
    prevX: -9999,
    prevY: -9999,
    vx: 0,
    vy: 0,
    isHovering: false,
    isOverCard: false,
    lastMoveTime: 0
  };

  // Color palettes for iridescent rainbow bubbles & sparkles
  const RAINBOW_STOPS = [
    'rgba(244, 114, 182, 0.72)', // Pink
    'rgba(251, 191, 36, 0.68)',  // Amber Gold
    'rgba(52, 211, 153, 0.72)',  // Mint Green
    'rgba(56, 189, 248, 0.76)',  // Sky Blue
    'rgba(192, 132, 252, 0.72)', // Lavender Purple
    'rgba(244, 114, 182, 0.72)'  // Loop back to Pink
  ];

  const SPARKLE_COLORS = [
    '#f472b6', '#fbbf24', '#34d399', '#38bdf8', '#c084fc', '#ffffff'
  ];

  /* ==========================================================================
     SNOW ENGINE (Dark Mode)
     ========================================================================== */
  class Snowflake {
    constructor(initial = false) {
      this.reset(initial);
    }

    reset(initial = false) {
      this.layer = Math.random() < 0.45 ? 1 : (Math.random() < 0.75 ? 2 : 3);

      if (this.layer === 1) {
        // Deep background layer: small, faint, slow
        this.radius = 0.9 + Math.random() * 0.9;
        this.baseVy = 0.45 + Math.random() * 0.45;
        this.baseAlpha = 0.25 + Math.random() * 0.22;
        this.swayAmp = 8 + Math.random() * 12;
        this.swaySpeed = 0.008 + Math.random() * 0.008;
        this.isCrystal = false;
      } else if (this.layer === 2) {
        // Midground layer: medium, glowing
        this.radius = 1.9 + Math.random() * 1.5;
        this.baseVy = 0.95 + Math.random() * 0.65;
        this.baseAlpha = 0.48 + Math.random() * 0.28;
        this.swayAmp = 14 + Math.random() * 18;
        this.swaySpeed = 0.012 + Math.random() * 0.012;
        this.isCrystal = Math.random() < 0.12;
      } else {
        // Foreground layer: large, prominent, soft glow, some crystal stars
        this.radius = 3.6 + Math.random() * 2.8;
        this.baseVy = 1.6 + Math.random() * 0.9;
        this.baseAlpha = 0.75 + Math.random() * 0.22;
        this.swayAmp = 22 + Math.random() * 26;
        this.swaySpeed = 0.015 + Math.random() * 0.015;
        this.isCrystal = Math.random() < 0.25;
      }

      this.x = Math.random() * (width + 60) - 30;
      this.baseX = this.x;
      this.y = initial ? Math.random() * height : -20 - Math.random() * 40;
      this.phase = Math.random() * Math.PI * 2;
      this.rot = Math.random() * Math.PI * 2;
      this.rotSpeed = (Math.random() - 0.5) * 0.03;
      this.pulse = Math.random() * Math.PI * 2;
      this.pulseSpeed = 0.02 + Math.random() * 0.03;
    }

    update(time, windOffset) {
      this.phase += this.swaySpeed;
      this.pulse += this.pulseSpeed;
      this.rot += this.rotSpeed;

      // Natural sway
      const sway = Math.sin(this.phase) * this.swayAmp;
      this.baseX += windOffset * (this.layer * 0.4);
      this.x = this.baseX + sway;

      // Mouse breeze repulsion
      if (mouse.isHovering) {
        const dx = this.x - mouse.x;
        const dy = this.y - mouse.y;
        const distSq = dx * dx + dy * dy;
        const radiusLimit = 85;
        if (distSq < radiusLimit * radiusLimit && distSq > 0) {
          const dist = Math.sqrt(distSq);
          const force = (1 - dist / radiusLimit) * 3.5;
          this.x += (dx / dist) * force;
          this.baseX += (dx / dist) * force * 0.5;
          this.y += (dy / dist) * force * 0.5;
        }
      }

      this.y += this.baseVy;

      // Wrap around bounds
      if (this.y > height + 25) {
        this.reset(false);
      }
      if (this.x < -40) {
        this.x = width + 30;
        this.baseX = this.x;
      } else if (this.x > width + 40) {
        this.x = -30;
        this.baseX = this.x;
      }
    }

    draw(ctx, globalAlpha) {
      if (globalAlpha <= 0.005) return;
      const alpha = this.baseAlpha * globalAlpha * (0.85 + Math.sin(this.pulse) * 0.15);

      ctx.save();
      ctx.translate(this.x, this.y);

      if (this.isCrystal && this.radius > 2.8) {
        // Draw 6-arm crystallized snowflake
        ctx.rotate(this.rot);
        ctx.strokeStyle = `rgba(240, 248, 255, ${alpha})`;
        ctx.fillStyle = `rgba(255, 255, 255, ${alpha * 0.9})`;
        ctx.lineWidth = Math.max(1, this.radius * 0.22);
        ctx.lineCap = 'round';

        const r = this.radius;
        for (let i = 0; i < 3; i++) {
          ctx.beginPath();
          ctx.moveTo(-r, 0);
          ctx.lineTo(r, 0);
          ctx.stroke();

          // Little branch v-notches
          const branchR = r * 0.55;
          const branchLen = r * 0.32;
          ctx.beginPath();
          ctx.moveTo(branchR, 0);
          ctx.lineTo(branchR + branchLen, branchLen);
          ctx.moveTo(branchR, 0);
          ctx.lineTo(branchR + branchLen, -branchLen);
          ctx.moveTo(-branchR, 0);
          ctx.lineTo(-branchR - branchLen, branchLen);
          ctx.moveTo(-branchR, 0);
          ctx.lineTo(-branchR - branchLen, -branchLen);
          ctx.stroke();

          ctx.rotate(Math.PI / 3);
        }

        // Center jewel
        ctx.beginPath();
        ctx.arc(0, 0, Math.max(1, r * 0.22), 0, Math.PI * 2);
        ctx.fill();
      } else {
        // Soft glowing snow dot
        if (this.layer >= 2) {
          const glowGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, this.radius * 2.2);
          glowGrad.addColorStop(0, `rgba(255, 255, 255, ${alpha})`);
          glowGrad.addColorStop(0.4, `rgba(224, 242, 254, ${alpha * 0.75})`);
          glowGrad.addColorStop(1, 'rgba(186, 230, 253, 0)');
          ctx.fillStyle = glowGrad;
          ctx.beginPath();
          ctx.arc(0, 0, this.radius * 2.2, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.fillStyle = `rgba(235, 245, 255, ${alpha})`;
          ctx.beginPath();
          ctx.arc(0, 0, this.radius, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.restore();
    }
  }

  /* ==========================================================================
     RAINBOW BUBBLE ENGINE (Light Mode)
     ========================================================================== */
  class Bubble {
    constructor(initial = false) {
      this.reset(initial);
    }

    reset(initial = false) {
      this.radius = 16 + Math.pow(Math.random(), 1.6) * 36; // Range: 16px to 52px
      this.x = Math.random() * (width - 40) + 20;
      this.baseX = this.x;
      this.y = initial
        ? Math.random() * (height + 100) - 50
        : height + this.radius + 15 + Math.random() * 80;

      this.vy = 0.65 + (50 / (this.radius + 15)) * 0.45 + Math.random() * 0.35; // Floats upward
      this.swayAmp = 12 + Math.random() * 22;
      this.swaySpeed = 0.012 + Math.random() * 0.014;
      this.phase = Math.random() * Math.PI * 2;

      this.rotation = Math.random() * Math.PI * 2;
      this.rotSpeed = (Math.random() - 0.5) * 0.012;

      // Soft wobble squish oscillation
      this.wobblePhase = Math.random() * Math.PI * 2;
      this.wobbleSpeed = 0.03 + Math.random() * 0.025;
      this.wobbleAmp = 0.045 + Math.random() * 0.03;

      this.baseAlpha = 0.72 + Math.random() * 0.22;
      this.isPopping = false;
    }

    update(time, onPop) {
      this.phase += this.swaySpeed;
      this.wobblePhase += this.wobbleSpeed;
      this.rotation += this.rotSpeed;

      // Gentle horizontal drift
      this.x = this.baseX + Math.sin(this.phase) * this.swayAmp;
      this.y -= this.vy;

      // Mouse interactive pop & repel (only if mouse is not over a card / interactive element)
      if (mouse.isHovering && !mouse.isOverCard) {
        const dx = mouse.x - this.x;
        const dy = mouse.y - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        // If mouse directly touches bubble, pop it!
        if (dist < this.radius + 10) {
          onPop(this.x, this.y, this.radius);
          this.reset(false);
          return;
        }

        // If near, gently push aside
        if (dist < this.radius + 55 && dist > 0) {
          const push = (1 - dist / (this.radius + 55)) * 2.2;
          this.baseX -= (dx / dist) * push;
        }
      }

      // Reached top of screen
      if (this.y < -this.radius - 20) {
        // 25% chance to pop gracefully at the top, otherwise recycle
        if (Math.random() < 0.25) {
          onPop(this.x, 15, this.radius * 0.85);
        }
        this.reset(false);
      }
    }

    draw(ctx, globalAlpha) {
      if (globalAlpha <= 0.005) return;
      const alpha = this.baseAlpha * globalAlpha;
      const r = this.radius;

      ctx.save();
      ctx.translate(this.x, this.y);
      ctx.rotate(this.rotation);

      // Squish wobble
      const sx = 1 + Math.sin(this.wobblePhase) * this.wobbleAmp;
      const sy = 1 - Math.sin(this.wobblePhase) * this.wobbleAmp;
      ctx.scale(sx, sy);

      // 1. Ultra-subtle internal sheen
      const innerGrad = ctx.createRadialGradient(
        -r * 0.35, -r * 0.35, r * 0.1,
        0, 0, r
      );
      innerGrad.addColorStop(0, `rgba(255, 255, 255, ${0.12 * alpha})`);
      innerGrad.addColorStop(0.65, `rgba(240, 249, 255, ${0.04 * alpha})`);
      innerGrad.addColorStop(0.9, `rgba(251, 207, 232, ${0.14 * alpha})`);
      innerGrad.addColorStop(1, `rgba(199, 210, 254, ${0.28 * alpha})`);

      ctx.fillStyle = innerGrad;
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fill();

      // 2. Iridescent Rainbow Rim
      const rimGrad = ctx.createLinearGradient(-r, -r, r, r);
      rimGrad.addColorStop(0.00, `rgba(244, 114, 182, ${0.72 * alpha})`); // Pink
      rimGrad.addColorStop(0.24, `rgba(251, 191, 36, ${0.68 * alpha})`);  // Gold
      rimGrad.addColorStop(0.48, `rgba(52, 211, 153, ${0.72 * alpha})`);  // Mint
      rimGrad.addColorStop(0.72, `rgba(56, 189, 248, ${0.78 * alpha})`);  // Sky Cyan
      rimGrad.addColorStop(0.88, `rgba(192, 132, 252, ${0.74 * alpha})`); // Violet
      rimGrad.addColorStop(1.00, `rgba(244, 114, 182, ${0.72 * alpha})`); // Pink

      ctx.lineWidth = Math.max(1.8, r * 0.055);
      ctx.strokeStyle = rimGrad;
      ctx.beginPath();
      ctx.arc(0, 0, r - ctx.lineWidth * 0.5, 0, Math.PI * 2);
      ctx.stroke();

      // Secondary fine bright rim
      ctx.lineWidth = 1;
      ctx.strokeStyle = `rgba(255, 255, 255, ${0.65 * alpha})`;
      ctx.beginPath();
      ctx.arc(0, 0, r - 0.5, 0, Math.PI * 2);
      ctx.stroke();

      // 3. Primary Specular Crescent Highlight (Top-left curved gleam)
      ctx.lineWidth = Math.max(2.2, r * 0.1);
      ctx.lineCap = 'round';
      ctx.strokeStyle = `rgba(255, 255, 255, ${0.92 * alpha})`;
      ctx.beginPath();
      ctx.arc(0, 0, r * 0.76, -Math.PI * 0.78, -Math.PI * 0.28);
      ctx.stroke();

      // Secondary dot highlight
      ctx.fillStyle = `rgba(255, 255, 255, ${0.95 * alpha})`;
      ctx.beginPath();
      const dotX = Math.cos(-Math.PI * 0.88) * (r * 0.76);
      const dotY = Math.sin(-Math.PI * 0.88) * (r * 0.76);
      ctx.arc(dotX, dotY, Math.max(1.2, r * 0.055), 0, Math.PI * 2);
      ctx.fill();

      // 4. Opposing Secondary Bottom Glow Reflection
      ctx.lineWidth = Math.max(1.2, r * 0.045);
      ctx.strokeStyle = `rgba(255, 255, 255, ${0.45 * alpha})`;
      ctx.beginPath();
      ctx.arc(0, 0, r * 0.82, Math.PI * 0.22, Math.PI * 0.55);
      ctx.stroke();

      ctx.restore();
    }
  }

  /* ==========================================================================
     POP SPARKLES (Burst when bubbles pop)
     ========================================================================== */
  class Sparkle {
    constructor(x, y, color) {
      this.x = x;
      this.y = y;
      const angle = Math.random() * Math.PI * 2;
      const speed = 1.8 + Math.random() * 4.2;
      this.vx = Math.cos(angle) * speed;
      this.vy = Math.sin(angle) * speed;
      this.life = 1.0;
      this.decay = 0.035 + Math.random() * 0.035;
      this.radius = 1.5 + Math.random() * 2.5;
      this.color = color || SPARKLE_COLORS[Math.floor(Math.random() * SPARKLE_COLORS.length)];
      this.isStar = Math.random() < 0.45;
    }

    update() {
      this.x += this.vx;
      this.y += this.vy;
      this.vx *= 0.94;
      this.vy = this.vy * 0.94 + 0.12; // Mild gravity
      this.life -= this.decay;
      return this.life > 0;
    }

    draw(ctx, globalAlpha) {
      if (this.life <= 0 || globalAlpha <= 0.005) return;
      const alpha = this.life * globalAlpha;

      ctx.save();
      ctx.translate(this.x, this.y);
      ctx.fillStyle = this.color;
      ctx.strokeStyle = this.color;
      ctx.globalAlpha = alpha;

      if (this.isStar) {
        const s = this.radius * 1.8;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(0, -s);
        ctx.lineTo(0, s);
        ctx.moveTo(-s, 0);
        ctx.lineTo(s, 0);
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(0, 0, this.radius * 0.5, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.arc(0, 0, this.radius, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.restore();
    }
  }

  /* ==========================================================================
     MANAGER & ANIMATION LOOP
     ========================================================================== */
  let snowflakes = [];
  let bubbles = [];
  let sparkles = [];

  function initParticles() {
    isMobile = window.innerWidth < 768;

    const snowCount = isMobile ? 52 : 98;
    snowflakes = [];
    for (let i = 0; i < snowCount; i++) {
      snowflakes.push(new Snowflake(true));
    }

    const bubbleCount = isMobile ? 15 : 28;
    bubbles = [];
    for (let i = 0; i < bubbleCount; i++) {
      bubbles.push(new Bubble(true));
    }

    sparkles = [];
  }

  function handleBubblePop(x, y, radius) {
    const count = Math.min(14, Math.max(7, Math.floor(radius * 0.35)));
    for (let i = 0; i < count; i++) {
      sparkles.push(new Sparkle(x, y));
    }
  }

  function onResize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;

    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);

    initParticles();
  }

  // Mouse / Pointer Tracking
  window.addEventListener('pointermove', (e) => {
    const now = performance.now();
    const dt = Math.max(1, now - mouse.lastMoveTime);
    mouse.lastMoveTime = now;

    if (mouse.prevX !== -9999) {
      mouse.vx = (e.clientX - mouse.prevX) / dt;
      mouse.vy = (e.clientY - mouse.prevY) / dt;
    }
    mouse.prevX = mouse.x;
    mouse.prevY = mouse.y;
    mouse.x = e.clientX;
    mouse.y = e.clientY;
    mouse.isHovering = true;
    mouse.isOverCard = !!(e.target && e.target.closest && e.target.closest('.project-card, .appbar, dialog, button, a, input, select, textarea'));
  }, { passive: true });

  window.addEventListener('pointerleave', () => {
    mouse.isHovering = false;
    mouse.isOverCard = false;
    mouse.x = -9999;
    mouse.y = -9999;
    mouse.prevX = -9999;
    mouse.prevY = -9999;
    mouse.vx = 0;
    mouse.vy = 0;
  });

  // Tap/click to pop bubbles directly (skip if user clicked on cards or interactive elements)
  window.addEventListener('pointerdown', (e) => {
    if (!bubbleOpacity || bubbleOpacity < 0.1) return;
    if (e.target && e.target.closest && e.target.closest('.project-card, .appbar, dialog, button, a, input, select, textarea')) {
      return;
    }
    const clickX = e.clientX;
    const clickY = e.clientY;

    for (let i = bubbles.length - 1; i >= 0; i--) {
      const b = bubbles[i];
      const dx = clickX - b.x;
      const dy = clickY - b.y;
      if (dx * dx + dy * dy < (b.radius + 14) * (b.radius + 14)) {
        handleBubblePop(b.x, b.y, b.radius);
        b.reset(false);
        break;
      }
    }
  }, { passive: true });

  // Theme Sync Observer
  function updateThemeState() {
    isDarkMode = document.documentElement.classList.contains('dark-mode') || localStorage.getItem('theme') === 'dark';
  }

  const themeObserver = new MutationObserver(() => {
    updateThemeState();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

  window.addEventListener('storage', (e) => {
    if (e.key === 'theme') {
      updateThemeState();
    }
  });

  window.__triggerAuthThemeChange = (newIsDark) => {
    isDarkMode = newIsDark;
  };

  // Main Render Loop
  let lastTime = performance.now();
  let animationFrameId = null;

  function loop(currentTime) {
    animationFrameId = requestAnimationFrame(loop);

    // Skip drawing if tab hidden
    if (document.hidden) return;

    const delta = Math.min(currentTime - lastTime, 64);
    lastTime = currentTime;

    // Cross-fade opacity between modes
    if (isDarkMode) {
      if (snowOpacity < 1.0) snowOpacity = Math.min(1.0, snowOpacity + FADE_SPEED);
      if (bubbleOpacity > 0.0) bubbleOpacity = Math.max(0.0, bubbleOpacity - FADE_SPEED);
    } else {
      if (bubbleOpacity < 1.0) bubbleOpacity = Math.min(1.0, bubbleOpacity + FADE_SPEED);
      if (snowOpacity > 0.0) snowOpacity = Math.max(0.0, snowOpacity - FADE_SPEED);
    }

    ctx.clearRect(0, 0, width, height);

    // Dynamic wind effect from mouse & nature
    const naturalWind = Math.sin(currentTime * 0.0006) * 0.35;
    const mouseWind = Math.max(-1.5, Math.min(1.5, mouse.vx * 3.5));
    const totalWind = naturalWind + mouseWind;

    // 1. Snow Simulation (Dark Mode)
    if (snowOpacity > 0.005) {
      for (let i = 0; i < snowflakes.length; i++) {
        const flake = snowflakes[i];
        flake.update(currentTime, totalWind);
        flake.draw(ctx, snowOpacity);
      }
    }

    // 2. Rainbow Bubble Simulation (Light Mode)
    if (bubbleOpacity > 0.005) {
      for (let i = 0; i < bubbles.length; i++) {
        const bubble = bubbles[i];
        bubble.update(currentTime, handleBubblePop);
        bubble.draw(ctx, bubbleOpacity);
      }
    }

    // 3. Sparkles Simulation
    if (sparkles.length > 0) {
      for (let i = sparkles.length - 1; i >= 0; i--) {
        const sp = sparkles[i];
        if (sp.update()) {
          sp.draw(ctx, Math.max(snowOpacity, bubbleOpacity));
        } else {
          sparkles.splice(i, 1);
        }
      }
    }
  }

  // Initialize
  onResize();
  window.addEventListener('resize', onResize);
  animationFrameId = requestAnimationFrame(loop);
})();
