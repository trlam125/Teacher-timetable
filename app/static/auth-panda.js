(() => {
  // Each panel has its own panda, inputs and password toggle. Initialize both
  // without allowing the hidden registration form to affect the login form.
  document.querySelectorAll('.panda-card').forEach(card => {
    const panda = card.querySelector('.panda');
    const email = card.querySelector('input[type="email"]');
    const password = card.querySelector('input[name="password"]');
    const toggle = card.querySelector('.password-toggle');
    if (!panda || !email || !password) return; // OTP has no password field.

    const setEyes = (x, y) => {
      panda.style.setProperty('--eye-x', `${Math.max(-4, Math.min(4, x))}px`);
      panda.style.setProperty('--eye-y', `${Math.max(-3, Math.min(3, y))}px`);
    };

    document.addEventListener('pointermove', event => {
      if (card.inert || card.classList.contains('panda-shy') || document.activeElement === email) return;
      const face = panda.getBoundingClientRect();
      setEyes((event.clientX - face.left - face.width / 2) / 32,
        (event.clientY - face.top - face.height / 2) / 35);
    });

    email.addEventListener('focus', () => card.classList.remove('panda-shy'));
    email.addEventListener('input', () => setEyes(-3.5 + Math.min(email.value.length, 28) / 4, 2));
    email.addEventListener('blur', () => setEyes(0, 0));

    if (toggle) {
      const setPasswordVisible = visible => {
        password.type = visible ? 'text' : 'password';
        card.classList.toggle('panda-shy', visible);
        toggle.classList.toggle('is-holding', visible);
        toggle.setAttribute('aria-pressed', String(visible));
        toggle.setAttribute('aria-label', visible ? 'Bấm để ẩn mật khẩu' : 'Bấm để hiện mật khẩu');
      };
      setPasswordVisible(false);
      toggle.addEventListener('click', () => setPasswordVisible(password.type === 'password'));
    }

    if (!card.querySelector('.loginButton')) {
      card.addEventListener('submit', event => {
        // The CAPTCHA validator can prevent submission. Check afterwards
        // rather than leaving the button permanently disabled on an invalid CAPTCHA.
        setTimeout(() => {
          if (event.defaultPrevented || !card.checkValidity()) return;
          card.classList.add('is-submitting');
          const button = card.querySelector('.auth-submit');
          const label = card.querySelector('.auth-submit span');
          if (button) button.disabled = true;
          if (label) label.textContent = 'Đang xác thực...';
        }, 0);
      });
    }
  });
})();
