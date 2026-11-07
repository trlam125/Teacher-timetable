(function () {
  "use strict";

  try {
    if (localStorage.getItem("theme") === "dark") {
      document.documentElement.classList.add("dark-mode");
    }
  } catch (_) {
    // Navigation remains available when browser storage is disabled.
  }

  document.addEventListener("DOMContentLoaded", function () {
    const backButton = document.getElementById("error-back");
    if (backButton && window.history.length > 1) {
      backButton.hidden = false;
      backButton.addEventListener("click", function () {
        window.history.back();
      });
    }
  });
})();
