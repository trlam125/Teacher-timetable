function restoreTransientActionButton(button, original, message, delay = 1400) {
  const errorMessage = message || "Thao tác chưa hoàn tất.";
  showToast(errorMessage, "error", Math.max(3600, delay + 1200));
  if (!button) return;

  const originalTitle = button.title || "";
  const originalAriaLabel = button.getAttribute("aria-label") || "";
  button.disabled = false;
  button.textContent = "!";
  button.title = errorMessage;
  button.setAttribute("aria-label", errorMessage);

  setTimeout(() => {
    if (!button.isConnected) return;
    button.innerHTML = original;
    button.title = originalTitle;
    if (originalAriaLabel) button.setAttribute("aria-label", originalAriaLabel);
    else button.removeAttribute("aria-label");
    button.disabled = false;
  }, delay);
}
function hasUnsavedConstraintChanges() {
  return constraintDraftDirty || globalLocksDraftDirty;
}
function discardUnsavedConstraintChanges() {
  constraintDraftDirty = false;
  globalLocksDraftDirty = false;
}
async function confirmDiscardConstraintChanges(message) {
  if (!hasUnsavedConstraintChanges()) return true;
  return confirmAction(
    message ||
    "Bạn có thay đổi ràng buộc chưa lưu. Nếu tiếp tục, các thay đổi này sẽ bị bỏ.",
    { title: "Thay đổi chưa lưu", confirmText: "Bỏ thay đổi" },
  );
}
function syncMobileNavSelect(tabName = null) {
  const select = document.querySelector("#mobileNavSelect");
  if (!select) return;
  const activeTab =
    tabName || document.querySelector(".nav.active")?.dataset.tab || "overview";
  if ([...select.options].some((option) => option.value === activeTab)) {
    select.value = activeTab;
  }
}

let currentWorkspaceTabTransition = null;

function cancelCurrentWorkspaceTabTransition() {
  if (currentWorkspaceTabTransition) {
    currentWorkspaceTabTransition.cleanup();
    currentWorkspaceTabTransition = null;
  }
}

async function activateWorkspaceTab(tabName, options = {}) {
  const b = document.querySelector(`.nav[data-tab="${tabName}"]`);
  if (!b) {
    syncMobileNavSelect();
    return false;
  }
  const currentActiveNav = document.querySelector(".nav.active");
  const current = currentActiveNav?.dataset.tab;
  if (current === tabName) {
    syncMobileNavSelect(tabName);
    return true;
  }
  if (current === "constraints" && tabName !== "constraints") {
    if (constraintSaveInFlight || globalSaveInFlight) {
      showToast("Đang lưu ràng buộc. Vui lòng chờ hoàn tất.", "info", 2400);
      syncMobileNavSelect(current);
      return false;
    }
    const confirmed = await confirmDiscardConstraintChanges(
      "Bạn có thay đổi trong Ràng buộc chưa lưu. Rời tab này sẽ bỏ các thay đổi đó.",
    );
    if (!confirmed) {
      syncMobileNavSelect(current);
      return false;
    }
    discardUnsavedConstraintChanges();
  }
  if (typeof clearTapAssign === "function") clearTapAssign();

  // If an animation is in progress, finalize it cleanly immediately
  cancelCurrentWorkspaceTabTransition();

  const tabOld = current ? document.getElementById(current) : null;
  const tabNew = document.getElementById(tabName);

  document
    .querySelectorAll(".nav")
    .forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  syncMobileNavSelect(b.dataset.tab);

  const stage =
    document.getElementById("workspaceTabsStage") ||
    document.querySelector(".workspace .content");
  const prefersReduced = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;

  // Immediate mode for first load, reduced motion, or missing elements
  if (!tabOld || !tabNew || !stage || prefersReduced || options.immediate) {
    document
      .querySelectorAll(".tab")
      .forEach((x) =>
        x.classList.remove(
          "active",
          "is-sliding-out",
          "is-sliding-in",
        ),
      );
    if (tabNew) tabNew.classList.add("active");
    if (tabName === "schedule") renderSchedule();
    if (tabName === "constraints") renderConstraintSelectors({ force: true });
    if (tabName === "preferences") loadPreferenceInbox();
    return true;
  }

  // Pre-render hooks so content is ready as it slides in
  if (tabName === "schedule") renderSchedule();
  if (tabName === "constraints") renderConstraintSelectors({ force: true });
  if (tabName === "preferences") loadPreferenceInbox();

  // Reset scroll of the incoming tab to the top so it enters cleanly
  tabNew.scrollTop = 0;

  // Determine direction based on nav order
  const navTabs = [...document.querySelectorAll(".nav[data-tab]")].map(
    (el) => el.dataset.tab,
  );
  const oldIndex = navTabs.indexOf(current);
  const newIndex = navTabs.indexOf(tabName);
  const isMovingDown =
    newIndex >= 0 && oldIndex >= 0 ? newIndex > oldIndex : true;

  const startNewY = isMovingDown ? "100%" : "-100%";
  const endOldY = isMovingDown ? "-100%" : "100%";
  const shadowClass = isMovingDown ? "shadow-top" : "shadow-bottom";

  // Pre-set offscreen transform, opacity fade, and soft blur BEFORE displaying
  tabNew.style.transform = `translateY(${startNewY})`;
  tabNew.style.opacity = "0.2";
  tabNew.style.filter = "blur(3px)";

  tabOld.style.transform = "translateY(0)";
  tabOld.style.opacity = "1";
  tabOld.style.filter = "blur(0px)";

  tabOld.classList.remove("active");
  tabOld.classList.add("is-sliding-out");

  tabNew.classList.add("active", "is-sliding-in", shadowClass);

  // Force reflow so browser commits the initial state
  void tabNew.offsetHeight;

  const duration = 420;
  const easing = "cubic-bezier(0.76, 0, 0.24, 1)";

  let animOld = null;
  let animNew = null;
  let cleaned = false;

  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    if (animOld) {
      try {
        animOld.cancel();
      } catch (_) { }
    }
    if (animNew) {
      try {
        animNew.cancel();
      } catch (_) { }
    }
    tabOld.style.transform = "";
    tabOld.style.opacity = "";
    tabOld.style.filter = "";
    tabOld.style.transition = "";

    tabNew.style.transform = "";
    tabNew.style.opacity = "";
    tabNew.style.filter = "";
    tabNew.style.transition = "";

    tabOld.classList.remove("is-sliding-out");
    tabNew.classList.remove("is-sliding-in", "shadow-top", "shadow-bottom");
    currentWorkspaceTabTransition = null;
  };

  currentWorkspaceTabTransition = { cleanup };

  if (typeof tabNew.animate === "function") {
    animOld = tabOld.animate(
      [
        { transform: "translateY(0)", opacity: 1, filter: "blur(0px)" },
        {
          transform: `translateY(${endOldY})`,
          opacity: 0.2,
          filter: "blur(3px)",
        },
      ],
      { duration, easing, fill: "forwards" },
    );

    animNew = tabNew.animate(
      [
        {
          transform: `translateY(${startNewY})`,
          opacity: 0.2,
          filter: "blur(3px)",
        },
        { transform: "translateY(0)", opacity: 1, filter: "blur(0px)" },
      ],
      { duration, easing, fill: "forwards" },
    );

    animNew.onfinish = cleanup;
  } else {
    tabOld.style.transition = `transform ${duration}ms ${easing}, opacity ${duration}ms ${easing}, filter ${duration}ms ${easing}`;
    tabNew.style.transition = `transform ${duration}ms ${easing}, opacity ${duration}ms ${easing}, filter ${duration}ms ${easing}`;
    requestAnimationFrame(() => {
      tabOld.style.transform = `translateY(${endOldY})`;
      tabOld.style.opacity = "0.2";
      tabOld.style.filter = "blur(3px)";

      tabNew.style.transform = "translateY(0)";
      tabNew.style.opacity = "1";
      tabNew.style.filter = "blur(0px)";
      setTimeout(cleanup, duration + 20);
    });
  }

  return true;
}
document
  .querySelectorAll(".nav")
  .forEach((b) => (b.onclick = () => void activateWorkspaceTab(b.dataset.tab)));
document.querySelector("#mobileNavSelect")?.addEventListener("change", (event) => {
  void activateWorkspaceTab(event.target.value);
});
syncMobileNavSelect();
function activateRequestedWorkspaceTab() {
  const tab = new URLSearchParams(window.location.search).get("tab");
  if (tab) void activateWorkspaceTab(tab, { immediate: true });
}
window.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedConstraintChanges()) return;
  event.preventDefault();
  event.returnValue = "";
});
