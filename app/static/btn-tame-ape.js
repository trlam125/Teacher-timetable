/**
 * Smart TKB - Uiverse tame-ape-82 Button Enhancer
 * Ensures any Add button or Delete button has the proper structure and SVGs.
 */
(function () {
  'use strict';

  const PLUS_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" stroke="currentColor" fill="none" class="svg"><line y2="19" y1="5" x2="12" x1="12"></line><line y2="12" y1="12" x2="19" x1="5"></line></svg>';
  const TRASH_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="svg"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>';

  function enhanceButton(btn) {
    if (!btn || btn.getAttribute('data-tame-ape-ready') === 'true') return;

    const text = btn.textContent.trim().replace(/^\+\s*/, '');
    const isDanger = btn.classList.contains('btn-tame-ape-danger') ||
      btn.classList.contains('danger-btn') ||
      text.includes('Xóa tài khoản') ||
      text.includes('Xóa log');

    btn.classList.add('btn-tame-ape');
    if (isDanger) {
      btn.classList.add('btn-tame-ape-danger');
      btn.classList.remove('ghost');
    }

    // Check if it already has .btn__icon
    if (btn.querySelector('.btn__icon')) {
      btn.setAttribute('data-tame-ape-ready', 'true');
      return;
    }

    const iconSvg = isDanger ? TRASH_SVG : PLUS_SVG;
    btn.innerHTML = `<span class="btn__text">${text}</span><span class="btn__icon">${iconSvg}</span>`;
    btn.setAttribute('data-tame-ape-ready', 'true');
  }

  function scanButtons() {
    // 1. Explicitly targeted buttons
    document.querySelectorAll('.btn-tame-ape').forEach(enhanceButton);

    // 2. Add buttons (text starting with + Thêm or + Tạo)
    document.querySelectorAll('button.btn, a.btn').forEach(btn => {
      const text = btn.textContent.trim();
      if (/^\+\s*(Thêm|Tạo)/i.test(text)) {
        enhanceButton(btn);
      }
    });

    // 3. Delete account and Delete log buttons in users.html
    document.querySelectorAll('.danger-btn').forEach(btn => {
      const text = btn.textContent.trim();
      if (text.includes('Xóa tài khoản') || text.includes('Xóa log')) {
        btn.classList.add('btn-tame-ape-danger');
        enhanceButton(btn);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scanButtons);
  } else {
    scanButtons();
  }

  // Observe dynamically created buttons (e.g. modals or tabs)
  const observer = new MutationObserver(function (mutations) {
    let shouldScan = false;
    for (const m of mutations) {
      if (m.addedNodes.length > 0) {
        shouldScan = true;
        break;
      }
    }
    if (shouldScan) {
      scanButtons();
    }
  });

  observer.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true
  });

  window.enhanceTameApeButtons = scanButtons;
})();
