(function () {
  "use strict";
  function initAvatars() {
    document.querySelectorAll("img[data-profile-image]").forEach(function (img) {
      function update() {
        img.parentElement.classList.toggle("has-image", img.complete && img.naturalWidth > 0);
      }
      img.addEventListener("load", update);
      img.addEventListener("error", update);
      update();
    });

    // Handle interactive avatar file inputs
    document.querySelectorAll(".avatar-clickable").forEach(function (label) {
      var input = label.querySelector('input[type="file"]');
      if (!input) return;

      label.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          input.click();
        }
      });

      input.addEventListener("change", function () {
        if (this.files && this.files.length > 0) {
          var overlay = label.querySelector(".avatar-overlay");
          if (overlay) {
            overlay.style.opacity = "1";
            overlay.style.visibility = "visible";
            var text = overlay.querySelector(".avatar-overlay-text");
            if (text) text.textContent = "Đang tải...";
          }
          if (this.form) {
            this.form.submit();
          }
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAvatars);
  } else {
    initAvatars();
  }
})();
