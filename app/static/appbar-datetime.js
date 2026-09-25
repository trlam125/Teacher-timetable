(function () {
  'use strict';

  const WEEKDAYS = [
    'Chủ nhật',
    'Thứ Hai',
    'Thứ Ba',
    'Thứ Tư',
    'Thứ Năm',
    'Thứ Sáu',
    'Thứ Bảy'
  ];
  const VIETNAM_OFFSET_MS = 7 * 60 * 60 * 1000;
  const RESYNC_INTERVAL_MS = 5 * 60 * 1000;
  const RETRY_INTERVAL_MS = 10 * 1000;

  let baseServerEpochMs = null;
  let basePerformanceMs = null;
  let syncTimer = null;

  function pad(value) {
    return String(value).padStart(2, '0');
  }

  function currentServerEpochMs() {
    if (baseServerEpochMs === null || basePerformanceMs === null) return null;
    return baseServerEpochMs + (performance.now() - basePerformanceMs);
  }

  function formatVietnamDateTime(epochMs) {
    // Shift the authoritative UTC epoch to UTC+7, then read it through UTC getters.
    // This keeps the result independent from the user's device timezone.
    const date = new Date(epochMs + VIETNAM_OFFSET_MS);
    const weekday = WEEKDAYS[date.getUTCDay()];
    const day = pad(date.getUTCDate());
    const month = pad(date.getUTCMonth() + 1);
    const year = date.getUTCFullYear();
    const hours = pad(date.getUTCHours());
    const minutes = pad(date.getUTCMinutes());
    const seconds = pad(date.getUTCSeconds());
    return `${weekday}, ${day}/${month}/${year} · ${hours}:${minutes}:${seconds}`;
  }

  function ensureDateTimeElement(appbar) {
    let target = appbar.querySelector('.appbar-datetime');
    if (target) return target;

    target = document.createElement('span');
    target.className = 'appbar-datetime';
    target.setAttribute('aria-label', 'Thứ, ngày và giờ Việt Nam hiện tại');
    target.setAttribute('role', 'status');
    target.setAttribute('aria-live', 'off');

    const themeButton = appbar.querySelector('.theme-toggle-btn');
    if (themeButton) {
      themeButton.insertAdjacentElement('afterend', target);
      return target;
    }

    const spacer = appbar.querySelector('.spacer');
    if (spacer) {
      spacer.insertAdjacentElement('afterend', target);
      return target;
    }

    appbar.appendChild(target);
    return target;
  }

  async function syncServerTime() {
    const requestStartedAt = performance.now();
    try {
      const response = await fetch('/api/server-time', {
        method: 'GET',
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const raw = await response.text();
      let data;
      try {
        data = JSON.parse(raw);
      } catch {
        throw new Error(`Invalid server time response (HTTP ${response.status})`);
      }
      const serverEpochMs = Number(data.epoch_ms);
      if (!Number.isFinite(serverEpochMs)) throw new Error('Invalid server time');

      const receivedAt = performance.now();
      // Compensate approximately for one half of the request round-trip time.
      baseServerEpochMs = serverEpochMs + (receivedAt - requestStartedAt) / 2;
      basePerformanceMs = receivedAt;

      window.clearTimeout(syncTimer);
      syncTimer = window.setTimeout(syncServerTime, RESYNC_INTERVAL_MS);
    } catch (error) {
      console.warn('Không thể đồng bộ thời gian từ server:', error);
      window.clearTimeout(syncTimer);
      syncTimer = window.setTimeout(syncServerTime, RETRY_INTERVAL_MS);
    }
  }

  function startAppbarClock() {
    const appbars = Array.from(document.querySelectorAll('header.appbar, header.landing-top'));
    if (!appbars.length) return;

    const targets = appbars.map(ensureDateTimeElement);

    function update() {
      const epochMs = currentServerEpochMs();
      if (epochMs === null) {
        targets.forEach((target) => {
          target.textContent = 'Đang đồng bộ thời gian...';
        });
        return;
      }

      const text = formatVietnamDateTime(epochMs);
      targets.forEach((target) => {
        target.textContent = text;
      });
    }

    update();
    syncServerTime().then(update);
    window.setInterval(update, 1000);

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) syncServerTime().then(update);
    });

    syncThemeSwitches();
  }

  function syncThemeSwitches() {
    const isDark = document.documentElement.classList.contains('dark-mode') ||
      (typeof localStorage !== 'undefined' && localStorage.getItem('theme') === 'dark');
    document.querySelectorAll('.theme-switch__checkbox').forEach((cb) => {
      cb.checked = isDark;
    });
  }

  window.toggleTheme = function () {
    const isDark = document.documentElement.classList.toggle('dark-mode');
    try {
      localStorage.setItem('theme', isDark ? 'dark' : 'light');
    } catch (_) { }
    document.querySelectorAll('.theme-switch__checkbox').forEach((cb) => {
      cb.checked = isDark;
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      startAppbarClock();
      syncThemeSwitches();
    }, { once: true });
  } else {
    startAppbarClock();
    syncThemeSwitches();
  }
})();

