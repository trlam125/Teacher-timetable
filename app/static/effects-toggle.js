(function () {
  let feedbackTimer = null;

  function isEffectsDisabled() {
    return document.documentElement.classList.contains('disable-effects') ||
      localStorage.getItem('disable_effects') === 'true';
  }

  function triggerBtnPop(el) {
    if (!el) return;
    el.classList.remove('btn-toggle-pop');
    void el.offsetWidth;
    el.classList.add('btn-toggle-pop');
    setTimeout(function () { el.classList.remove('btn-toggle-pop'); }, 360);
  }

  function updateEffectsUI(isOff, isInteractive) {
    const buttons = document.querySelectorAll('.appbar-effects-btn');
    if (!buttons.length) return;

    if (feedbackTimer) {
      clearTimeout(feedbackTimer);
      feedbackTimer = null;
    }

    buttons.forEach((btn) => {
      const iconWrap = btn.querySelector('.appbar-effects-icon-wrap');
      const textEl = btn.querySelector('.appbar-effects-text');

      btn.setAttribute('title', isOff ? 'Hiệu ứng đang tắt - Bấm để bật' : 'Hiệu ứng đang bật - Bấm để tắt');
      btn.setAttribute('aria-label', isOff ? 'Bật hiệu ứng' : 'Tắt hiệu ứng');

      if (isInteractive) {
        if (isOff) {
          btn.classList.remove('is-feedback-on');
          btn.classList.add('is-feedback', 'is-feedback-off');
          if (iconWrap) {
            // Dùng dấu X tĩnh thay cho GIF khi vừa TẮT hiệu ứng. Khi class
            // `disable-effects` được bật, toàn bộ animation CSS bị vô hiệu hóa;
            // icon tĩnh bảo đảm phản hồi "Đã tắt hiệu ứng" luôn hiện rõ.
            iconWrap.innerHTML = '<span class="appbar-effects-cross" aria-hidden="true">✕</span>';
          }
          if (textEl) {
            textEl.textContent = 'Đã tắt hiệu ứng';
          }
        } else {
          btn.classList.remove('is-feedback-off');
          btn.classList.add('is-feedback', 'is-feedback-on');
          if (iconWrap) {
            iconWrap.innerHTML = '<img class="appbar-effects-gif is-on" src="/static/tick.gif?v=1&play=' + Date.now() + '" width="20" height="20" alt="✓">';
          }
          if (textEl) {
            textEl.textContent = 'Đã bật hiệu ứng';
          }
        }
      } else {
        btn.classList.remove('is-feedback', 'is-feedback-on', 'is-feedback-off');
        if (iconWrap) {
          iconWrap.innerHTML = isOff
            ? '<span class="appbar-effects-icon" aria-hidden="true">🚫</span>'
            : '<span class="appbar-effects-icon" aria-hidden="true">✨</span>';
        }
        if (textEl) {
          textEl.textContent = isOff ? 'Hiệu ứng: Tắt' : 'Hiệu ứng: Bật';
        }
      }
    });

    if (isInteractive) {
      feedbackTimer = setTimeout(function () {
        buttons.forEach((btn) => {
          btn.classList.remove('is-feedback', 'is-feedback-on', 'is-feedback-off');
          const iconWrap = btn.querySelector('.appbar-effects-icon-wrap');
          const textEl = btn.querySelector('.appbar-effects-text');
          if (iconWrap) {
            iconWrap.innerHTML = isOff
              ? '<span class="appbar-effects-icon" aria-hidden="true">🚫</span>'
              : '<span class="appbar-effects-icon" aria-hidden="true">✨</span>';
          }
          if (textEl) {
            textEl.textContent = isOff ? 'Hiệu ứng: Tắt' : 'Hiệu ứng: Bật';
          }
        });
        feedbackTimer = null;
      }, 2400);
    }
  }

  function toggleEffects(callerBtn) {
    const wasOff = isEffectsDisabled();
    const isOff = !wasOff;

    if (callerBtn) {
      triggerBtnPop(callerBtn);
    } else {
      document.querySelectorAll('.appbar-effects-btn').forEach(triggerBtnPop);
    }

    document.documentElement.classList.toggle('disable-effects', isOff);
    localStorage.setItem('disable_effects', isOff ? 'true' : 'false');
    updateEffectsUI(isOff, true);

    window.dispatchEvent(new CustomEvent('effectsToggle', { detail: { disabled: isOff } }));
  }

  // Expose globally
  window.toggleEffects = toggleEffects;

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      updateEffectsUI(isEffectsDisabled(), false);
    });
  } else {
    updateEffectsUI(isEffectsDisabled(), false);
  }
})();
