(() => {
  'use strict';

  const slider = document.querySelector('.auth-form-slider');
  if (!slider) return; // OTP is intentionally outside the sliding interface.

  const panels = {
    login: slider.querySelector('.auth-slide-login'),
    register: slider.querySelector('.auth-slide-register')
  };
  if (!panels.login || !panels.register) return;

  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let mode = slider.dataset.initialMode === 'register' ? 'register' : 'login';
  let focusTimer;

  function show(next, { push = false, animate = true, focus = false } = {}) {
    if (!panels[next]) return;
    if (next === mode && animate) return;
    mode = next;
    slider.classList.toggle('is-register', next === 'register');
    document.body.classList.toggle('auth-login', next === 'login');
    document.body.classList.toggle('auth-register', next === 'register');
    document.title = next === 'register' ? 'Đăng ký tài khoản' : 'Đăng nhập';

    for (const [name, panel] of Object.entries(panels)) {
      const inactive = name !== next;
      panel.inert = inactive;
      panel.setAttribute('aria-hidden', String(inactive));
    }
    if (push) history.pushState({ authMode: next }, '', next === 'register' ? '/register' : '/login');

    clearTimeout(focusTimer);
    if (focus) {
      focusTimer = window.setTimeout(() => {
        const input = panels[next].querySelector('input[type="email"]');
        if (input && mode === next) input.focus({ preventScroll: true });
      }, motion.matches ? 0 : 570);
    }
  }

  // Both complete forms are present from the first render. No page reload,
  // CAPTCHA recreation, script re-execution or interrupted submission is needed.
  for (const [name, panel] of Object.entries(panels)) {
    panel.inert = name !== mode;
    panel.setAttribute('aria-hidden', String(name !== mode));
  }
  slider.classList.toggle('is-register', mode === 'register');
  slider.classList.add('auth-slide-ready');

  slider.querySelectorAll('a[data-auth-switch]').forEach(link => {
    link.addEventListener('click', event => {
      if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      show(link.dataset.authSwitch, { push: true, focus: true });
    });
  });

  window.addEventListener('popstate', () => {
    const path = window.location.pathname.replace(/\/$/, '');
    if (path === '/login' || path === '/register') show(path.slice(1));
    else window.location.reload();
  });
})();
