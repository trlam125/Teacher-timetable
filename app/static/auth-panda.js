(() => {
  const card = document.querySelector('.panda-card');
  const panda = document.querySelector('.panda');
  const email = document.querySelector('#authEmail');
  const password = document.querySelector('#authPassword');
  const toggle = document.querySelector('.password-toggle');
  if (!card || !panda || !email || !password) return;

  const setEyes = (x, y) => {
    panda.style.setProperty('--eye-x', `${Math.max(-4, Math.min(4, x))}px`);
    panda.style.setProperty('--eye-y', `${Math.max(-3, Math.min(3, y))}px`);
  };

  document.addEventListener('pointermove', event => {
    if (card.classList.contains('panda-shy') || document.activeElement === email) return;
    const face = panda.getBoundingClientRect();
    setEyes((event.clientX - face.left - face.width / 2) / 32, (event.clientY - face.top - face.height / 2) / 35);
  });

  email.addEventListener('focus', () => card.classList.remove('panda-shy'));
  email.addEventListener('input', () => setEyes(-3.5 + Math.min(email.value.length, 28) / 4, 2));
  email.addEventListener('blur', () => setEyes(0, 0));

  if (toggle) {
    const revealPassword = () => {
      password.type = 'text';
      card.classList.add('panda-shy');
      toggle.classList.add('is-holding');
      toggle.setAttribute('aria-pressed', 'true');
      toggle.setAttribute('aria-label', 'Thả để ẩn mật khẩu');
    };
    const hidePassword = () => {
      password.type = 'password';
      card.classList.remove('panda-shy');
      toggle.classList.remove('is-holding');
      toggle.setAttribute('aria-pressed', 'false');
      toggle.setAttribute('aria-label', 'Giữ để hiện mật khẩu');
    };

    toggle.addEventListener('pointerdown', event => {
      revealPassword();
      toggle.setPointerCapture?.(event.pointerId);
    });
    toggle.addEventListener('pointerup', hidePassword);
    toggle.addEventListener('pointercancel', hidePassword);
    toggle.addEventListener('lostpointercapture', hidePassword);
    toggle.addEventListener('mouseleave', hidePassword);
    toggle.addEventListener('keydown', event => {
      if (event.key === ' ' || event.key === 'Enter') {
        event.preventDefault();
        revealPassword();
      }
    });
    toggle.addEventListener('keyup', hidePassword);
    toggle.addEventListener('blur', hidePassword);
    toggle.addEventListener('click', event => event.preventDefault());
  }

  card.addEventListener('submit', () => {
    card.classList.add('is-submitting');
    const button = card.querySelector('.auth-submit');
    const label = card.querySelector('.auth-submit span');
    if (button) button.disabled = true;
    if (label) label.textContent = 'Đang xác thực...';
  });
})();
