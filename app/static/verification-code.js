/* A single native field keeps paste, password managers and SMS autofill usable. */
(() => {
  'use strict';
  document.querySelectorAll('[data-verification-code]').forEach(input => {
    input.addEventListener('paste', event => {
      const text = event.clipboardData?.getData('text');
      if (typeof text !== 'string') return;
      const code = text.replace(/[\s-]/g, '');
      if (/^[0-9]{6}$/.test(code)) {
        event.preventDefault();
        input.value = code;
        input.dispatchEvent(new Event('input', {bubbles: true}));
      }
    });
    input.addEventListener('input', () => {
      input.setCustomValidity('');
      input.removeAttribute('aria-invalid');
    });
    input.addEventListener('invalid', () => {
      input.setCustomValidity('Vui lòng nhập hoặc dán đủ 6 chữ số.');
      input.setAttribute('aria-invalid', 'true');
    });
  });
})();
