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
    const setPasswordVisible = visible => {
      password.type = visible ? 'text' : 'password';
      card.classList.toggle('panda-shy', visible);
      toggle.classList.toggle('is-holding', visible);
      toggle.setAttribute('aria-pressed', String(visible));
      toggle.setAttribute('aria-label', visible ? 'Bấm để ẩn mật khẩu' : 'Bấm để hiện mật khẩu');
    };

    setPasswordVisible(false);

    toggle.addEventListener('click', () => {
      setPasswordVisible(password.type === 'password');
    });
  }

  card.addEventListener('submit', () => {
    card.classList.add('is-submitting');
    const button = card.querySelector('.auth-submit');
    const label = card.querySelector('.auth-submit span');
    if (button) button.disabled = true;
    if (label) label.textContent = 'Đang xác thực...';
  });
})();
