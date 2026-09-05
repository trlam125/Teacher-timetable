(() => {
  function swapElements(first, second) {
    if (!first || !second || first === second) return;
    const marker = document.createElement('span');
    first.replaceWith(marker);
    second.replaceWith(first);
    marker.replaceWith(second);
  }

  document.querySelectorAll('.visual-captcha').forEach((captcha) => {
    const kind = captcha.dataset.captchaKind;
    const answer = captcha.querySelector('.captcha-answer');
    const status = captcha.querySelector('.captcha-status');
    const requiredCount = Number(captcha.dataset.requiredCount || 0);

    if (!answer) return;

    if (kind === 'images') {
      const tiles = [...captcha.querySelectorAll('.captcha-image-tile')];
      const update = () => {
        const selected = tiles.filter((tile) => tile.classList.contains('is-selected'));
        answer.value = selected.map((tile) => tile.dataset.captchaValue).sort().join(',');
        status.textContent = selected.length
          ? `Đã chọn ${selected.length}/${requiredCount} hình.`
          : 'Chưa chọn hình nào.';
        status.classList.toggle('is-ready', selected.length === requiredCount);
      };
      tiles.forEach((tile) => {
        tile.addEventListener('click', () => {
          tile.classList.toggle('is-selected');
          tile.setAttribute('aria-pressed', tile.classList.contains('is-selected') ? 'true' : 'false');
          update();
        });
      });
      update();
    }

    if (kind === 'puzzle') {
      const board = captcha.querySelector('.captcha-puzzle');
      let active = null;
      let dragging = null;

      const update = () => {
        const pieces = [...board.querySelectorAll('.captcha-puzzle-piece')];
        answer.value = pieces.map((piece) => piece.dataset.captchaValue).join(',');
        status.textContent = 'Sắp xếp xong thì gửi biểu mẫu để kiểm tra.';
      };

      board.querySelectorAll('.captcha-puzzle-piece').forEach((piece) => {
        piece.addEventListener('click', () => {
          if (!active) {
            active = piece;
            piece.classList.add('is-active');
            status.textContent = 'Đã chọn 1 mảnh. Chọn mảnh thứ hai để đổi chỗ.';
            return;
          }
          active.classList.remove('is-active');
          if (active !== piece) swapElements(active, piece);
          active = null;
          update();
        });

        piece.addEventListener('dragstart', (event) => {
          dragging = piece;
          piece.classList.add('is-dragging');
          if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', piece.dataset.captchaValue || 'piece');
          }
        });
        piece.addEventListener('dragend', () => {
          piece.classList.remove('is-dragging');
          dragging = null;
        });
        piece.addEventListener('dragover', (event) => {
          event.preventDefault();
          if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        });
        piece.addEventListener('drop', (event) => {
          event.preventDefault();
          if (dragging && dragging !== piece) {
            swapElements(dragging, piece);
            update();
          }
        });
      });
      update();
    }

    const form = captcha.closest('form');
    if (!form) return;
    form.addEventListener('submit', (event) => {
      const enforce = captcha.dataset.enforce || 'always';
      const action = event.submitter?.getAttribute('formaction') || form.getAttribute('action') || '';
      if (enforce === 'resend' && !action.includes('/register/resend')) return;

      if (kind === 'images') {
        const selectedCount = answer.value ? answer.value.split(',').filter(Boolean).length : 0;
        if (selectedCount !== requiredCount) {
          event.preventDefault();
          status.textContent = `Hãy chọn đúng ${requiredCount} hình trước khi tiếp tục.`;
          status.classList.add('is-error');
          captcha.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    });
  });
})();
