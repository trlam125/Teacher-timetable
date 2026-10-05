(() => {
  const title = document.getElementById("statusTitle");
  const text = document.getElementById("statusText");
  const retry = document.getElementById("retryButton");

  const STARTED_AT = Date.now();
  const RETRY_DELAY_MS = 1200;
  const SHOW_RETRY_AFTER_MS = 45000;
  let stopped = false;
  let timer = 0;

  function cleanNextPath() {
    const raw = new URLSearchParams(location.search).get("next") || "/";
    if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
    return raw;
  }

  function joinTarget(base, path) {
    const root = String(base || "").replace(/\/+$/, "");
    return root + (path.startsWith("/") ? path : "/" + path);
  }

  function setWaitingCopy() {
    const elapsed = Date.now() - STARTED_AT;
    if (elapsed > 15000) {
      text.textContent = "M\u00e1y ch\u1ee7 Render \u0111ang th\u1ee9c d\u1eady, b\u1ea1n s\u1ebd \u0111\u01b0\u1ee3c chuy\u1ec3n ti\u1ebfp t\u1ef1 \u0111\u1ed9ng.";
    }
    if (elapsed > SHOW_RETRY_AFTER_MS) retry.hidden = false;
  }

  async function checkBackend() {
    if (stopped) return;
    clearTimeout(timer);
    setWaitingCopy();

    try {
      const response = await fetch(`/api/health?t=${Date.now()}`, {
        method: "GET",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      const data = await response.json().catch(() => null);

      if (response.ok && data?.ready && data?.target) {
        stopped = true;
        retry.hidden = true;
        document.body.classList.add("is-ready");
        title.textContent = "Smart TKB \u0111\u00e3 s\u1eb5n s\u00e0ng";
        text.textContent = "\u0110ang chuy\u1ec3n t\u1edbi \u1ee9ng d\u1ee5ng...";
        const destination = joinTarget(data.target, cleanNextPath());
        window.setTimeout(() => location.replace(destination), 280);
        return;
      }
    } catch (_) {
      // The launcher stays visible and retries instead of exposing a Render error page.
    }

    timer = window.setTimeout(checkBackend, RETRY_DELAY_MS);
  }

  retry.addEventListener("click", () => {
    retry.hidden = true;
    text.textContent = "\u0110ang th\u1eed k\u1ebft n\u1ed1i l\u1ea1i...";
    checkBackend();
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !stopped) checkBackend();
  });

  checkBackend();
})();
