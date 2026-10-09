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
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAvatars);
  } else {
    initAvatars();
  }
})();
