/**
 * FabMotion - Floating Action Buttons Convergence & Glide Orchestrator
 *
 * Choreography:
 * 1. Target button clicked: Other buttons converge to target's position (target stays on top).
 * 2. Entire stack glides down to the bottom-most button's position.
 * 3. Concurrently, the respective panel/popup opens smoothly in sync with the downward glide.
 * 4. Closing reverses the effects: panel collapses while stack moves up, then buttons disperse.
 * 5. Multi-frame Ghost Trail (ảo ảnh từng frame) follows every movement with subtle, elegant opacity.
 */
(function () {
  if (window.FabMotion) return;

  const CONFIG = {
    durationConverge: 360,
    durationGlide: 480,
    easeConverge: 'cubic-bezier(0.22, 1, 0.36, 1)',
    easeGlide: 'cubic-bezier(0.19, 1, 0.22, 1)',
    easePanel: 'cubic-bezier(0.19, 1, 0.22, 1)'
  };

  const PROFILES = {
    generalChatFab: {
      name: 'Chat chung',
      gradient: 'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)',
      glow: 'rgba(99, 102, 241, 0.85)',
      borderGlow: '#c7d2fe'
    },
    chatbotFab: {
      name: 'Trợ lý AI',
      gradient: 'linear-gradient(135deg, #2563eb 0%, #06b6d4 100%)',
      glow: 'rgba(14, 165, 233, 0.85)',
      borderGlow: '#bae6fd'
    }
  };

  let isAnimating = false;
  let activeFab = null;
  let activePopup = null;
  let baselineTops = new Map();

  function getFabList() {
    const list = [];
    const generalFab = document.getElementById('generalChatFab');
    const chatbotFab = document.getElementById('chatbotFab');
    if (generalFab) list.push(generalFab);
    if (chatbotFab) list.push(chatbotFab);

    // Sort from top to bottom based on physical baseline
    return list.sort((a, b) => {
      const topA = getBaselineTop(a);
      const topB = getBaselineTop(b);
      return topA - topB;
    });
  }

  function getBaselineTop(el) {
    if (baselineTops.has(el)) return baselineTops.get(el);
    const rect = el.getBoundingClientRect();
    const currentY = parseFloat(el.dataset.motionY || 0);
    const baseline = rect.top - currentY;
    baselineTops.set(el, baseline);
    return baseline;
  }

  function updateAllBaselines() {
    baselineTops.clear();
    const fabs = [
      document.getElementById('generalChatFab'),
      document.getElementById('chatbotFab')
    ].filter(Boolean);

    fabs.forEach(el => {
      const rect = el.getBoundingClientRect();
      const currentY = parseFloat(el.dataset.motionY || 0);
      baselineTops.set(el, rect.top - currentY);
    });
  }

  window.addEventListener('resize', updateAllBaselines);

  /**
   * Spawn a single translucent ghost echo disc
   */
  function spawnGhostEcho(btn, profile) {
    const rect = btn.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const echo = document.createElement('div');
    echo.className = 'fab-ghost-echo';
    echo.style.left = `${rect.left}px`;
    echo.style.top = `${rect.top}px`;
    echo.style.width = `${rect.width}px`;
    echo.style.height = `${rect.height}px`;
    echo.style.background = profile?.gradient || 'linear-gradient(135deg, #4f46e5, #7c3aed)';
    echo.style.setProperty('--echo-glow', profile?.glow || 'rgba(99, 102, 241, 0.4)');
    echo.style.borderColor = profile?.borderGlow || 'rgba(255, 255, 255, 0.65)';

    document.body.appendChild(echo);
    setTimeout(() => echo.remove(), 420);
  }

  /**
   * Continuous Ghost Trail Generator using requestAnimationFrame
   */
  function startGhostTrail(buttonList, durationMs, profileOverride = null) {
    const startTime = performance.now();
    let lastStamp = 0;
    const stampInterval = 24;

    function frameLoop(now) {
      const elapsed = now - startTime;
      if (elapsed > durationMs + 20) return;

      if (now - lastStamp >= stampInterval) {
        lastStamp = now;
        buttonList.forEach(btn => {
          const profile = profileOverride || PROFILES[btn.id] || PROFILES.generalChatFab;
          spawnGhostEcho(btn, profile);
        });
      }
      requestAnimationFrame(frameLoop);
    }
    requestAnimationFrame(frameLoop);
  }

  /**
   * MASTER OPEN CHOREOGRAPHY
   */
  async function open(triggerFab, popupEl, options = {}) {
    if (isAnimating) return;
    isAnimating = true;

    // If another popup is open, close its UI first without resetting layout
    if (activePopup && activePopup !== popupEl) {
      activePopup.classList.remove('is-open');
      activePopup.setAttribute('aria-hidden', 'true');
    }

    updateAllBaselines();
    const fabs = getFabList();
    if (fabs.length === 0) {
      isAnimating = false;
      return;
    }

    const lastIndex = fabs.length - 1;
    const lastFab = fabs[lastIndex];
    const k = fabs.indexOf(triggerFab);
    activeFab = triggerFab;
    activePopup = popupEl;

    const targetTop = getBaselineTop(triggerFab);
    const lastTop = getBaselineTop(lastFab);
    const profile = PROFILES[triggerFab.id] || PROFILES.generalChatFab;

    // SPECIAL CASE: Trigger button is ALREADY the bottom-most button
    if (k === lastIndex) {
      const subordinates = fabs.filter(b => b !== triggerFab);
      startGhostTrail(subordinates, CONFIG.durationGlide, profile);

      // Open popup simultaneously
      if (popupEl) {
        popupEl.classList.add('is-open');
        popupEl.setAttribute('aria-hidden', 'false');
      }
      triggerFab.setAttribute('aria-expanded', 'true');
      triggerFab.classList.add('is-on-top');
      subordinates.forEach(b => b.classList.remove('is-on-top'));

      subordinates.forEach(btn => {
        btn.classList.add('anim-motion');
        const delta = lastTop - getBaselineTop(btn);
        btn.style.transform = `translateY(${delta}px) scale(0.92)`;
        btn.dataset.motionY = `${delta}`;
        btn.classList.add('is-stacked-behind');
      });

      triggerFab.classList.add('anim-motion');
      triggerFab.style.transform = 'translateY(0px)';
      triggerFab.dataset.motionY = '0';
      triggerFab.classList.remove('is-stacked-behind');

      await new Promise(r => setTimeout(r, CONFIG.durationGlide));
      if (typeof options.onOpened === 'function') options.onOpened();
      isAnimating = false;
      return;
    }

    // GENERAL CASE: Trigger button is above the bottom button (e.g. generalChatFab)
    // Step 1: Convergence
    const subordinates = fabs.filter(b => b !== triggerFab);
    startGhostTrail(subordinates, CONFIG.durationConverge, profile);

    triggerFab.classList.add('is-on-top');
    triggerFab.classList.remove('is-stacked-behind');
    triggerFab.classList.add('anim-motion-fast');
    triggerFab.style.transform = 'translateY(0px)';
    triggerFab.dataset.motionY = '0';

    subordinates.forEach(btn => {
      btn.classList.remove('is-on-top');
      btn.classList.add('is-stacked-behind');
      btn.classList.add('anim-motion-fast');
      const delta = targetTop - getBaselineTop(btn);
      btn.style.transform = `translateY(${delta}px) scale(0.92)`;
      btn.dataset.motionY = `${delta}`;
    });

    // Continuous velocity transfer: begin gliding slightly before convergence ends
    const overlapDelay = 35;
    await new Promise(r => setTimeout(r, CONFIG.durationConverge - overlapDelay));

    // Step 2: Downward Glide of the whole stack + Synchronized Popup Opening
    if (popupEl) {
      popupEl.classList.add('is-open');
      popupEl.setAttribute('aria-hidden', 'false');
    }
    triggerFab.setAttribute('aria-expanded', 'true');

    startGhostTrail([triggerFab], CONFIG.durationGlide, profile);

    fabs.forEach(btn => {
      btn.classList.remove('anim-motion-fast');
      btn.classList.add('anim-motion');
      const finalDelta = lastTop - getBaselineTop(btn);
      if (btn === triggerFab) {
        btn.style.transform = `translateY(${finalDelta}px) scale(1)`;
      } else {
        btn.style.transform = `translateY(${finalDelta}px) scale(0.92)`;
      }
      btn.dataset.motionY = `${finalDelta}`;
    });

    await new Promise(r => setTimeout(r, CONFIG.durationGlide + overlapDelay));
    if (typeof options.onOpened === 'function') options.onOpened();
    isAnimating = false;
  }

  /**
   * MASTER CLOSE CHOREOGRAPHY (REVERSE EFFECT)
   */
  async function close(triggerFab, popupEl, options = {}) {
    if (isAnimating) return;
    isAnimating = true;

    updateAllBaselines();
    const fabs = getFabList();
    if (fabs.length === 0) {
      isAnimating = false;
      return;
    }

    const lastIndex = fabs.length - 1;
    const lastFab = fabs[lastIndex];
    const k = fabs.indexOf(triggerFab);
    const targetTop = getBaselineTop(triggerFab);
    const profile = PROFILES[triggerFab.id] || PROFILES.generalChatFab;

    if (popupEl) {
      popupEl.classList.remove('is-open');
      popupEl.setAttribute('aria-hidden', 'true');
    }
    triggerFab.setAttribute('aria-expanded', 'false');

    // SPECIAL CASE: Closing from bottom button
    if (k === lastIndex) {
      const subordinates = fabs.filter(b => b !== triggerFab);
      startGhostTrail(subordinates, CONFIG.durationGlide, profile);

      subordinates.forEach(btn => {
        btn.classList.remove('anim-motion-fast');
        btn.classList.add('anim-motion');
        btn.style.transform = 'translateY(0px) scale(1)';
        btn.dataset.motionY = '0';
        btn.classList.remove('is-stacked-behind', 'is-on-top');
      });

      triggerFab.classList.remove('is-on-top');
      triggerFab.style.transform = 'translateY(0px)';
      triggerFab.dataset.motionY = '0';

      await new Promise(r => setTimeout(r, CONFIG.durationGlide));
      fabs.forEach(btn => btn.classList.remove('anim-motion', 'anim-motion-fast'));
      activeFab = null;
      activePopup = null;
      if (typeof options.onClosed === 'function') options.onClosed();
      isAnimating = false;
      return;
    }

    // GENERAL CASE: Closing from upper button (e.g. generalChatFab)
    // Phase A: Stack glides back UP to triggerFab's baseline position with upward ghost trail
    startGhostTrail([triggerFab], CONFIG.durationGlide, profile);

    fabs.forEach(btn => {
      btn.classList.remove('anim-motion-fast');
      btn.classList.add('anim-motion');
      const delta = targetTop - getBaselineTop(btn);
      if (btn === triggerFab) {
        btn.style.transform = 'translateY(0px) scale(1)';
      } else {
        btn.style.transform = `translateY(${delta}px) scale(0.92)`;
      }
      btn.dataset.motionY = (btn === triggerFab) ? '0' : `${delta}`;
    });

    const overlapDelay = 35;
    await new Promise(r => setTimeout(r, CONFIG.durationGlide - overlapDelay));

    // Phase B: Other buttons disperse back down to their resting positions
    const subordinates = fabs.filter(b => b !== triggerFab);
    startGhostTrail(subordinates, CONFIG.durationConverge, profile);

    subordinates.forEach(btn => {
      btn.classList.remove('anim-motion');
      btn.classList.add('anim-motion-fast');
      btn.style.transform = 'translateY(0px) scale(1)';
      btn.dataset.motionY = '0';
      btn.classList.remove('is-stacked-behind', 'is-on-top');
    });

    triggerFab.classList.remove('is-on-top');
    triggerFab.style.transform = 'translateY(0px)';
    triggerFab.dataset.motionY = '0';

    await new Promise(r => setTimeout(r, CONFIG.durationConverge + overlapDelay));
    fabs.forEach(btn => btn.classList.remove('anim-motion', 'anim-motion-fast'));

    activeFab = null;
    activePopup = null;
    if (typeof options.onClosed === 'function') options.onClosed();
    isAnimating = false;
  }

  // Export Global API
  window.FabMotion = {
    open,
    close,
    isAnimating: () => isAnimating,
    getActiveFab: () => activeFab,
    getActivePopup: () => activePopup,
    startGhostTrail
  };
})();
