/**
 * User Avatar Dropdown & System Settings Modal
 */
(function () {
  "use strict";

  function initUserMenu() {
    const wrap = document.querySelector("#userAvatarMenu");
    if (!wrap) return;

    const btn = wrap.querySelector("#userAvatarBtn");
    const dropdown = wrap.querySelector("#userAvatarDropdown");
    if (!btn || !dropdown) return;

    function openMenu() {
      dropdown.hidden = false;
      btn.setAttribute("aria-expanded", "true");
    }

    function closeMenu() {
      dropdown.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }

    function toggleMenu(e) {
      e.stopPropagation();
      if (dropdown.hidden) {
        openMenu();
      } else {
        closeMenu();
      }
    }

    btn.addEventListener("click", toggleMenu);

    // Close when clicking outside
    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) {
        closeMenu();
      }
    });

    // Close on Escape
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        if (!dropdown.hidden) {
          closeMenu();
          btn.focus();
        }
      }
    });
  }

  window.openSystemSettingsModal = function () {
    const dropdown = document.querySelector("#userAvatarDropdown");
    if (dropdown) dropdown.hidden = true;
    const btn = document.querySelector("#userAvatarBtn");
    if (btn) btn.setAttribute("aria-expanded", "false");

    if (typeof window.updateEffectsUI === "function") {
      const isOff = document.documentElement.classList.contains("disable-effects") ||
        (typeof localStorage !== "undefined" && localStorage.getItem("disable_effects") === "true");
      window.updateEffectsUI(isOff, false);
    }

    const modal = document.querySelector("#systemSettingsModal");
    if (modal) {
      if (typeof modal.showModal === "function") {
        modal.showModal();
      } else {
        modal.hidden = false;
      }
    }
  };

  window.closeSystemSettingsModal = function () {
    const modal = document.querySelector("#systemSettingsModal");
    if (modal) {
      if (typeof modal.close === "function") {
        modal.close();
      } else {
        modal.hidden = true;
      }
    }
  };

  // Close dialog on backdrop click
  document.addEventListener("click", function (e) {
    const modal = document.querySelector("#systemSettingsModal");
    if (modal && e.target === modal) {
      window.closeSystemSettingsModal();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initUserMenu);
  } else {
    initUserMenu();
  }
})();
