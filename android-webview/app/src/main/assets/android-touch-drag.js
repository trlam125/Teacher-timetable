(() => {
  "use strict";

  // Timetable editing now uses the same tap/click flow on desktop and Android.
  // Keep this legacy asset as a no-op so older WebView shells that still try to
  // inject it cannot re-enable a second touch-drag implementation.
  window.__smartTkbAndroidTapMode = true;
})();
