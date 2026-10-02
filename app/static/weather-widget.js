/**
 * Smart TKB - Open-Meteo Weather & 7-Day Forecast System
 * Displays live weather pill in Appbar and 7-Day Forecast in Workspace & Modal
 */
(function () {
  'use strict';

  const CITIES = {
    hanoi: { name: 'Hà Nội', lat: 21.0285, lon: 105.8542 },
    hcm: { name: 'TP. Hồ Chí Minh', lat: 10.8231, lon: 106.6297 },
    haiphong: { name: 'Hải Phòng', lat: 20.8449, lon: 106.6881 },
    danang: { name: 'Đà Nẵng', lat: 16.0544, lon: 108.2022 },
    cantho: { name: 'Cần Thơ', lat: 10.0452, lon: 105.7469 },
    hue: { name: 'Huế', lat: 16.4637, lon: 107.5909 },
    thanhhoa: { name: 'Thanh Hóa', lat: 19.8067, lon: 105.7852 }
  };

  const WEEKDAY_NAMES = [
    'Chủ nhật',
    'Thứ Hai',
    'Thứ Ba',
    'Thứ Tư',
    'Thứ Năm',
    'Thứ Sáu',
    'Thứ Bảy'
  ];

  const WEEKDAY_SHORT = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];

  // Weather Icons SVG Generators (with animated components)
  function getWeatherIcon(code, isDay = 1) {
    // Clear
    if (code === 0) {
      if (isDay) {
        return `<svg class="wx-icon wx-sun" viewBox="0 0 24 24" fill="none"><circle class="wx-sun-core" cx="12" cy="12" r="5" fill="#f59e0b" stroke="#d97706" stroke-width="1.2"><animate attributeName="r" values="4.9;5.3;4.9" dur="3s" repeatCount="indefinite"/></circle><g class="wx-sun-rays"><line x1="12" y1="1.5" x2="12" y2="4" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="20" x2="12" y2="22.5" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><line x1="1.5" y1="12" x2="4" y2="12" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><line x1="20" y1="12" x2="22.5" y2="12" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><line x1="4.6" y1="4.6" x2="6.4" y2="6.4" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><line x1="17.6" y1="17.6" x2="19.4" y2="19.4" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><line x1="4.6" y1="19.4" x2="6.4" y2="17.6" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><line x1="17.6" y1="6.4" x2="19.4" y2="4.6" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="20s" repeatCount="indefinite"/></g></svg>`;
      }
      return `<svg class="wx-icon wx-moon" viewBox="0 0 24 24" fill="none"><path class="wx-moon-body" d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" fill="#38bdf8" stroke="#0284c7" stroke-width="1.4"/><circle class="wx-star wx-star-1" cx="7" cy="5" r="0.8" fill="#38bdf8"/><circle class="wx-star wx-star-2" cx="16" cy="4" r="0.6" fill="#38bdf8"/></svg>`;
    }
    // Partly Cloudy
    if (code === 1 || code === 2) {
      return `<svg class="wx-icon wx-partly-cloudy" viewBox="0 0 24 24" fill="none"><circle class="wx-sun-bg" cx="9" cy="9" r="4.2" fill="#f59e0b"><animate attributeName="r" values="4;4.4;4" dur="3.2s" repeatCount="indefinite"/></circle><g class="wx-sun-rays-mini"><line x1="9" y1="1.8" x2="9" y2="3.8" stroke="#f59e0b" stroke-width="1.6" stroke-linecap="round"/><line x1="1.8" y1="9" x2="3.8" y2="9" stroke="#f59e0b" stroke-width="1.6" stroke-linecap="round"/><line x1="3.9" y1="3.9" x2="5.3" y2="5.3" stroke="#f59e0b" stroke-width="1.6" stroke-linecap="round"/><animate attributeName="opacity" values="0.7;1;0.7" dur="3.2s" repeatCount="indefinite"/></g><path class="wx-cloud-front" d="M7 17h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.8A3.5 3.5 0 0 0 7 17z" fill="#cbd5e1" stroke="#94a3b8" stroke-width="1.5"/></svg>`;
    }
    // Overcast / Cloudy
    if (code === 3) {
      return `<svg class="wx-icon wx-cloudy" viewBox="0 0 24 24" fill="none"><path class="wx-cloud-back" d="M14 14h6a3.5 3.5 0 0 0 0-7 4.8 4.8 0 0 0-9.2 1.6A3 3 0 0 0 14 14z" fill="#cbd5e1" opacity="0.65"/><path class="wx-cloud-front" d="M17.5 19H6.5A4.5 4.5 0 0 1 6.5 10a6 6 0 0 1 11.7-1.4A4 4 0 0 1 17.5 19z" fill="#94a3b8" stroke="#64748b" stroke-width="1.5"/></svg>`;
    }
    // Fog
    if (code === 45 || code === 48) {
      return `<svg class="wx-icon wx-fog" viewBox="0 0 24 24" fill="none"><path class="wx-fog-line wx-fog-1" d="M4 9h16" stroke="#94a3b8" stroke-width="2" stroke-linecap="round"/><path class="wx-fog-line wx-fog-2" d="M2.5 13.5h19" stroke="#64748b" stroke-width="2" stroke-linecap="round"/><path class="wx-fog-line wx-fog-3" d="M5 18h14" stroke="#94a3b8" stroke-width="2" stroke-linecap="round"/></svg>`;
    }
    // Drizzle
    if (code >= 51 && code <= 57) {
      return `<svg class="wx-icon wx-drizzle" viewBox="0 0 24 24" fill="none"><path class="wx-cloud-front" d="M7 14h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.8A3.5 3.5 0 0 0 7 14z" fill="#94a3b8"/><line class="wx-drop wx-drop-1" x1="8" y1="16" x2="6.8" y2="19.5" stroke="#38bdf8" stroke-width="1.8" stroke-linecap="round"/><line class="wx-drop wx-drop-2" x1="12" y1="16" x2="10.8" y2="19.5" stroke="#38bdf8" stroke-width="1.8" stroke-linecap="round"/><line class="wx-drop wx-drop-3" x1="16" y1="16" x2="14.8" y2="19.5" stroke="#38bdf8" stroke-width="1.8" stroke-linecap="round"/></svg>`;
    }
    // Rain
    if (code >= 61 && code <= 67) {
      return `<svg class="wx-icon wx-rain" viewBox="0 0 24 24" fill="none"><path class="wx-cloud-front" d="M7 13h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.8A3.5 3.5 0 0 0 7 13z" fill="#64748b"/><line class="wx-drop wx-drop-1" x1="8" y1="15" x2="6.2" y2="20.5" stroke="#0284c7" stroke-width="2.2" stroke-linecap="round"/><line class="wx-drop wx-drop-2" x1="12" y1="15" x2="10.2" y2="20.5" stroke="#0284c7" stroke-width="2.2" stroke-linecap="round"/><line class="wx-drop wx-drop-3" x1="16" y1="15" x2="14.2" y2="20.5" stroke="#0284c7" stroke-width="2.2" stroke-linecap="round"/></svg>`;
    }
    // Snow
    if (code >= 71 && code <= 77) {
      return `<svg class="wx-icon wx-snow" viewBox="0 0 24 24" fill="none"><path class="wx-cloud-front" d="M7 13h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.8A3.5 3.5 0 0 0 7 13z" fill="#94a3b8"/><circle class="wx-flake wx-flake-1" cx="8" cy="18" r="1.5" fill="#38bdf8"/><circle class="wx-flake wx-flake-2" cx="12" cy="19" r="1.5" fill="#38bdf8"/><circle class="wx-flake wx-flake-3" cx="16" cy="18" r="1.5" fill="#38bdf8"/></svg>`;
    }
    // Showers
    if (code >= 80 && code <= 82) {
      return `<svg class="wx-icon wx-showers" viewBox="0 0 24 24" fill="none"><path class="wx-cloud-front" d="M7 13h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.8A3.5 3.5 0 0 0 7 13z" fill="#475569"/><line class="wx-drop wx-drop-heavy wx-drop-1" x1="7" y1="15" x2="4.8" y2="21" stroke="#0284c7" stroke-width="2.4" stroke-linecap="round"/><line class="wx-drop wx-drop-heavy wx-drop-2" x1="11" y1="15" x2="8.8" y2="21" stroke="#0284c7" stroke-width="2.4" stroke-linecap="round"/><line class="wx-drop wx-drop-heavy wx-drop-3" x1="15" y1="15" x2="12.8" y2="21" stroke="#0284c7" stroke-width="2.4" stroke-linecap="round"/></svg>`;
    }
    // Thunderstorm
    if (code >= 95) {
      return `<svg class="wx-icon wx-thunder" viewBox="0 0 24 24" fill="none"><path class="wx-cloud-storm" d="M17.5 14H6.5A4.5 4.5 0 0 1 6.5 5a6 6 0 0 1 11.7-1.4A4 4 0 0 1 17.5 14z" fill="#334155"/><polygon class="wx-bolt" points="13 13 9 19 13 19 11 23 16 16 12 16" fill="#f59e0b" stroke="#d97706" stroke-width="1.2"/></svg>`;
    }
    // Unknown conditions use the same clear-day icon.
    return getWeatherIcon(0);
  }

  function getWeatherDesc(code) {
    const map = {
      0: 'Trời quang đãng',
      1: 'Ít mây, trời trong',
      2: 'Mây rải rác',
      3: 'Nhiều mây, âm u',
      45: 'Sương mù',
      48: 'Sương mù đọng sương',
      51: 'Mưa phùn nhẹ',
      53: 'Mưa phùn vừa',
      55: 'Mưa phùn hạt to',
      56: 'Mưa phùn lạnh nhẹ',
      57: 'Mưa phùn lạnh buốt',
      61: 'Mưa nhỏ ngắt quãng',
      63: 'Mưa vừa',
      65: 'Mưa to diện rộng',
      66: 'Mưa đá nhẹ',
      67: 'Mưa đá to',
      71: 'Tuyết rơi nhẹ',
      73: 'Tuyết rơi vừa',
      75: 'Tuyết rơi dày',
      77: 'Hạt tuyết rơi',
      80: 'Mưa rào nhẹ',
      81: 'Mưa rào vừa',
      82: 'Mưa rào rất to',
      85: 'Mưa tuyết rào nhẹ',
      86: 'Mưa tuyết rào to',
      95: 'Giông bão sét',
      96: 'Dông sét kèm mưa đá nhỏ',
      99: 'Dông sét kèm mưa đá to'
    };
    return map[code] || 'Thời tiết ổn định';
  }

  function getHeroTheme(code) {
    if (code === 0) return 'theme-sunny';
    if (code >= 1 && code <= 3) return 'theme-cloudy';
    if (code >= 51) return 'theme-rainy';
    return '';
  }

  const WEATHER_CACHE_TTL_MS = 10 * 60 * 1000;
  const LOCATION_MAX_AGE_MS = 10 * 60 * 1000;
  const LOCATION_TIMEOUT_MS = 5000;
  const LOCATION_REUSE_DISTANCE_KM = 3;
  const LAST_LOCATION_KEY = 'smart_tkb_weather_last_location';
  const FALLBACK_CITY_KEY = 'smart_tkb_weather_city';

  let currentWeatherState = null;
  let selectedCityKey = localStorage.getItem(FALLBACK_CITY_KEY) || 'hanoi';
  if (!CITIES[selectedCityKey]) {
    selectedCityKey = 'hanoi';
    localStorage.setItem(FALLBACK_CITY_KEY, selectedCityKey);
  }

  let locationSelectionRevision = 0;
  let weatherRequestRevision = 0;

  function parseStoredLocation() {
    try {
      const raw = localStorage.getItem(LAST_LOCATION_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      const lat = Number(parsed.lat);
      const lon = Number(parsed.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
      if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
      return {
        name: 'Vị trí gần nhất',
        lat,
        lon,
        source: 'gps'
      };
    } catch (e) {
      return null;
    }
  }

  const storedLocation = parseStoredLocation();
  let activeLocation = storedLocation || { ...CITIES[selectedCityKey], source: 'city' };

  function getActiveCoords() {
    return activeLocation;
  }

  function locationSignature(coords) {
    return `${Number(coords.lat).toFixed(3)},${Number(coords.lon).toFixed(3)}`;
  }

  function getClientCacheKey(coords) {
    return `smart_tkb_weather_cache_${locationSignature(coords)}`;
  }

  function distanceKm(a, b) {
    const toRad = value => value * Math.PI / 180;
    const earthRadiusKm = 6371;
    const lat1 = toRad(Number(a.lat));
    const lat2 = toRad(Number(b.lat));
    const dLat = lat2 - lat1;
    const dLon = toRad(Number(b.lon) - Number(a.lon));
    const h = Math.sin(dLat / 2) ** 2
      + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return 2 * earthRadiusKm * Math.asin(Math.sqrt(h));
  }

  function saveCurrentLocation(coords) {
    localStorage.setItem(LAST_LOCATION_KEY, JSON.stringify({
      lat: coords.lat,
      lon: coords.lon
    }));
  }

  function setLocationButtonBusy(isBusy) {
    const button = document.getElementById('weatherUseLocationBtn');
    if (!button) return;
    button.classList.toggle('is-locating', isBusy);
    button.disabled = isBusy;
  }

  function syncLocationControls() {
    const select = document.getElementById('weatherCitySelect');
    if (select && select.value !== selectedCityKey) select.value = selectedCityKey;

    const button = document.getElementById('weatherUseLocationBtn');
    if (button) {
      const gpsActive = getActiveCoords().source === 'gps';
      button.classList.toggle('is-active', gpsActive);
      button.setAttribute('aria-pressed', gpsActive ? 'true' : 'false');
      button.title = gpsActive
        ? (getActiveCoords().name === 'Vị trí gần nhất' ? 'Đang dùng vị trí gần nhất đã lưu' : 'Đang dùng vị trí hiện tại')
        : 'Dùng vị trí hiện tại';
    }
  }

  function selectFallbackCity(cityKey) {
    if (!CITIES[cityKey]) return;
    locationSelectionRevision += 1;
    selectedCityKey = cityKey;
    localStorage.setItem(FALLBACK_CITY_KEY, selectedCityKey);
    activeLocation = { ...CITIES[selectedCityKey], source: 'city' };
    currentWeatherState = null;
    syncLocationControls();
    updateAllWeatherUI();
    fetchWeatherData(false);
  }

  function requestCurrentLocation() {
    if (!navigator.geolocation) {
      console.warn('Smart TKB Weather: Trình duyệt không hỗ trợ định vị.');
      return Promise.resolve(false);
    }

    const requestSelectionRevision = locationSelectionRevision;
    setLocationButtonBusy(true);

    return new Promise(resolve => {
      navigator.geolocation.getCurrentPosition(
        position => {
          setLocationButtonBusy(false);

          // Nếu người dùng vừa tự chọn tỉnh/thành trong lúc hộp quyền GPS đang mở,
          // không tự động ghi đè lựa chọn đó. Nút định vị thủ công vẫn có thể ghi đè.
          if (requestSelectionRevision !== locationSelectionRevision) {
            resolve(false);
            return;
          }

          const nextLocation = {
            name: 'Vị trí hiện tại',
            lat: Number(position.coords.latitude),
            lon: Number(position.coords.longitude),
            source: 'gps'
          };

          const previousLocation = getActiveCoords();
          const wasGps = previousLocation.source === 'gps';
          const movedKm = distanceKm(previousLocation, nextLocation);

          activeLocation = nextLocation;
          saveCurrentLocation(nextLocation);
          syncLocationControls();

          // Nếu đang dùng GPS đã lưu và vị trí mới chỉ lệch rất ít, giữ dữ liệu đang hiển thị.
          // Việc này tránh thêm một request không cần thiết khi vừa mở trang.
          if (wasGps && movedKm < LOCATION_REUSE_DISTANCE_KM && currentWeatherState) {
            updateAllWeatherUI();
            resolve(true);
            return;
          }

          fetchWeatherData(false).finally(() => resolve(true));
        },
        error => {
          setLocationButtonBusy(false);
          const reasons = {
            1: 'người dùng từ chối quyền vị trí',
            2: 'không xác định được vị trí',
            3: 'hết thời gian chờ vị trí'
          };
          console.info(`Smart TKB Weather: dùng địa điểm dự phòng vì ${reasons[error.code] || 'lỗi định vị'}.`);
          resolve(false);
        },
        {
          enableHighAccuracy: false,
          timeout: LOCATION_TIMEOUT_MS,
          maximumAge: LOCATION_MAX_AGE_MS
        }
      );
    });
  }

  // Fetch weather data with client-side caching & fallback.
  // Hàm luôn chụp lại vị trí tại thời điểm request và bỏ qua response cũ
  // nếu người dùng đã chuyển sang vị trí khác trước khi request hoàn tất.
  async function fetchWeatherData(forceRefresh = false) {
    const coords = { ...getActiveCoords() };
    const requestSignature = locationSignature(coords);
    const requestRevision = ++weatherRequestRevision;
    const cacheKey = getClientCacheKey(coords);
    const now = Date.now();

    if (!forceRefresh) {
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (now - parsed.timestamp < WEATHER_CACHE_TTL_MS) {
            if (requestSignature === locationSignature(getActiveCoords())) {
              currentWeatherState = parsed.data;
              updateAllWeatherUI();
            }
            return;
          }
        } catch (e) { }
      }
    }

    try {
      let res;
      try {
        res = await fetch(`/api/weather?latitude=${coords.lat}&longitude=${coords.lon}`, {
          cache: forceRefresh ? 'no-cache' : 'default'
        });
      } catch (err) {
        // Backend không truy cập được: thử Open-Meteo trực tiếp ở bước dưới.
      }

      let data;
      if (res && res.ok) {
        data = await res.json();
      } else {
        const openMeteoUrl = `https://api.open-meteo.com/v1/forecast?latitude=${coords.lat}&longitude=${coords.lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max&timezone=auto&forecast_days=7`;
        const omRes = await fetch(openMeteoUrl);
        if (!omRes.ok) throw new Error('Open-Meteo API error');
        data = await omRes.json();
      }

      localStorage.setItem(cacheKey, JSON.stringify({ timestamp: now, data }));

      if (requestRevision === weatherRequestRevision && requestSignature === locationSignature(getActiveCoords())) {
        currentWeatherState = data;
        updateAllWeatherUI();
      }
    } catch (error) {
      console.warn('Smart TKB Weather Fetch Warning:', error);
    }
  }

  // Update Appbar badge
  function updateAppbarBadge() {
    const appbar = document.querySelector('.appbar');
    if (!appbar) return;

    let badge = document.getElementById('appbarWeatherBtn');
    if (!badge) {
      badge = document.createElement('button');
      badge.id = 'appbarWeatherBtn';
      badge.className = 'appbar-weather';
      badge.type = 'button';
      badge.setAttribute('aria-label', 'Xem dự báo thời tiết cả tuần');
      badge.setAttribute('title', 'Xem thời tiết & dự báo 7 ngày cho tuần học');
      badge.onclick = openWeatherModal;

      const dt = appbar.querySelector('.appbar-datetime');
      if (dt) {
        dt.insertAdjacentElement('afterend', badge);
      } else {
        const spacer = appbar.querySelector('.spacer');
        if (spacer) spacer.insertAdjacentElement('afterend', badge);
        else appbar.appendChild(badge);
      }
    }

    if (!currentWeatherState || !currentWeatherState.current) {
      badge.innerHTML = `<span class="appbar-weather-icon"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="4" fill="#3b82f6"/></svg></span><span class="appbar-weather-temp">Thời tiết</span>`;
      return;
    }

    const cur = currentWeatherState.current;
    const coords = getActiveCoords();
    const icon = getWeatherIcon(cur.weather_code, cur.is_day);
    const temp = Math.round(cur.temperature_2m);

    badge.innerHTML = `
      <span class="appbar-weather-icon">${icon}</span>
      <span class="appbar-weather-temp">${temp}°C</span>
      <span class="appbar-weather-city">${coords.name}</span>
    `;
  }

  // School context analysis
  function generateSchoolAdvice(weather) {
    if (!weather || !weather.daily) return '';
    const codes = weather.daily.weather_code || [];
    const maxProbs = weather.daily.precipitation_probability_max || [];
    const maxTemps = weather.daily.temperature_2m_max || [];

    const hasThunder = codes.some(c => c >= 95);
    const highRainIdx = maxProbs.findIndex(p => p >= 65);
    const hasHighRain = highRainIdx !== -1;
    const maxTempWeek = Math.max(...maxTemps);

    if (hasThunder) {
      return {
        icon: '⚡',
        text: 'Có dự báo giông sét trong tuần. Ban giám hiệu và giáo viên thể dục cần lưu ý chuyển các tiết học ngoài trời vào nhà đa năng/phòng học có mái che khi thời tiết xấu.'
      };
    }
    if (hasHighRain) {
      const dayName = highRainIdx === 0 ? 'hôm nay' : `vào ${WEEKDAY_NAMES[new Date(weather.daily.time[highRainIdx]).getDay()]}`;
      return {
        icon: '🌧️',
        text: `Khả năng mưa lớn (${maxProbs[highRainIdx]}%) ${dayName}. Nhà trường nên chủ động chuẩn bị phương án sinh hoạt và tiết thể dục dự phòng trong phòng chức năng.`
      };
    }
    if (maxTempWeek >= 35) {
      return {
        icon: '☀️',
        text: `Nhiệt độ dự báo có ngày lên tới ${Math.round(maxTempWeek)}°C. Cần lưu ý nhắc nhở học sinh bổ sung đủ nước, bật quạt/điều hòa thông thoáng phòng học.`
      };
    }
    return {
      icon: '🌤️',
      text: 'Thời tiết tuần này nhìn chung thuận lợi cho lịch học tập, thể dục thể thao và các hoạt động giáo dục ngoài trời của nhà trường.'
    };
  }

  // Update Workspace Overview Card
  function updateWorkspaceOverview() {
    const overviewTab = document.getElementById('overview');
    if (!overviewTab) return;

    let panel = document.getElementById('workspaceWeatherOverview');
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'workspaceWeatherOverview';
      panel.className = 'weather-overview-panel';

      const stats = overviewTab.querySelector('.stats');
      if (stats) {
        stats.insertAdjacentElement('afterend', panel);
      } else {
        overviewTab.appendChild(panel);
      }
    }

    if (!currentWeatherState || !currentWeatherState.daily) {
      panel.innerHTML = '<p class="muted">Đang tải dữ liệu thời tiết tuần...</p>';
      return;
    }

    const cur = currentWeatherState.current || {};
    const daily = currentWeatherState.daily;
    const coords = getActiveCoords();
    const advice = generateSchoolAdvice(currentWeatherState);

    let daysHtml = '';
    const count = Math.min(7, daily.time.length);
    for (let i = 0; i < count; i++) {
      const dateStr = daily.time[i];
      const d = new Date(dateStr);
      const isToday = i === 0;
      const dayLabel = isToday ? 'Hôm nay' : WEEKDAY_SHORT[d.getDay()];
      const dateFormatted = `${d.getDate()}/${d.getMonth() + 1}`;
      const code = daily.weather_code[i];
      const icon = getWeatherIcon(code, 1);
      const maxT = Math.round(daily.temperature_2m_max[i]);
      const minT = Math.round(daily.temperature_2m_min[i]);
      const rain = daily.precipitation_probability_max ? daily.precipitation_probability_max[i] : null;

      daysHtml += `
        <div class="weather-col-card ${isToday ? 'is-today' : ''}" title="${getWeatherDesc(code)}">
          <span class="weather-col-day">${dayLabel}</span>
          <span class="weather-col-date">${dateFormatted}</span>
          <div class="weather-col-icon">${icon}</div>
          <div class="weather-col-temp">${maxT}° <span class="weather-col-min">${minT}°</span></div>
          ${rain != null && rain > 20 ? `<span class="weather-col-rain">💧${rain}%</span>` : '<span class="weather-col-rain" style="opacity:0.4">—</span>'}
        </div>
      `;
    }

    panel.innerHTML = `
      <div class="weather-overview-head">
        <div class="weather-overview-title">
          <h3>Thời tiết tuần &amp; Hoạt động trường học</h3>
          <span class="weather-overview-badge">${coords.name} · ${cur.temperature_2m ? Math.round(cur.temperature_2m) + '°C' : ''}</span>
        </div>
      </div>
      <div class="weather-overview-grid">
        ${daysHtml}
      </div>
      ${advice ? `
        <div class="weather-school-tip" style="margin-top:2px">
          <span class="weather-school-tip-icon">${advice.icon}</span>
          <span><b>Lưu ý thời khóa biểu:</b> ${advice.text}</span>
        </div>
      ` : ''}
    `;

    const grid = panel.querySelector('.weather-overview-grid');
    if (grid) {
      setupWeatherDockMagnification(grid);
    }
  }

  /* --------------------------------------------------------------------------
     HIỆU ỨNG DOCK MAGNIFICATION (PHÓNG TO DẠNG SÓNG PARABOL KIỂU MACOS)
     -------------------------------------------------------------------------- */
  function setupWeatherDockMagnification(grid) {
    if (!grid) return;

    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }

    let rafId = null;
    let cardData = [];

    function cacheCardCenters() {
      const cards = Array.from(grid.querySelectorAll('.weather-col-card'));
      cardData = cards.map(card => {
        const rect = card.getBoundingClientRect();
        return {
          card,
          cx: rect.left + rect.width / 2,
          cy: rect.top + rect.height / 2,
          width: rect.width
        };
      });
    }

    function resetAllCards() {
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      grid.querySelectorAll('.weather-col-card').forEach(card => {
        card.style.transform = '';
        card.style.zIndex = '';
        card.style.boxShadow = '';
        card.style.borderColor = '';
      });
    }

    grid.addEventListener('mouseenter', () => {
      cacheCardCenters();
    });

    grid.addEventListener('mousemove', (e) => {
      const mouseX = e.clientX;
      const mouseY = e.clientY;

      if (rafId) cancelAnimationFrame(rafId);

      rafId = requestAnimationFrame(() => {
        if (!cardData.length) cacheCardCenters();
        if (!cardData.length) return;

        const isDark = document.documentElement.classList.contains('dark-mode') || document.body.classList.contains('dark-mode');
        const cardW = cardData[0].width || 100;
        // Bán kính sóng parabol (khoảng 1.8 đến 2.0 lần bề rộng thẻ để tạo độ dốc hình chuông đẹp mắt)
        const radius = Math.max(cardW * 1.85, 150);
        const maxScale = 1.18; // Tỉ lệ đỉnh sóng phóng to 18%
        const maxLift = 10;    // Đỉnh sóng nhấc lên 10px

        cardData.forEach(({ card, cx, cy }) => {
          const dist = Math.hypot(mouseX - cx, mouseY - cy);

          if (dist < radius) {
            // Hàm Cosine tạo sóng Parabol đối xứng kinh điển của macOS Dock
            const factor = Math.cos((dist / radius) * (Math.PI / 2));
            const scale = 1 + (maxScale - 1) * factor;
            const lift = maxLift * factor;
            const zIndex = Math.round(factor * 20) + 2;

            card.style.transform = `scale(${scale.toFixed(3)}) translateY(-${lift.toFixed(1)}px)`;
            card.style.zIndex = String(zIndex);

            if (isDark) {
              card.style.boxShadow = factor > 0.05
                ? `0 ${Math.round(4 + 8 * factor)}px ${Math.round(14 + 16 * factor)}px rgba(0, 0, 0, ${(0.35 + 0.35 * factor).toFixed(2)})`
                : '';
              if (factor > 0.45 && !card.classList.contains('is-today')) {
                card.style.borderColor = 'rgba(59, 130, 246, 0.45)';
              } else if (!card.classList.contains('is-today')) {
                card.style.borderColor = '';
              }
            } else {
              card.style.boxShadow = factor > 0.05
                ? `0 ${Math.round(4 + 8 * factor)}px ${Math.round(12 + 14 * factor)}px rgba(37, 99, 235, ${(0.08 + 0.14 * factor).toFixed(2)})`
                : '';
              if (factor > 0.45 && !card.classList.contains('is-today')) {
                card.style.borderColor = 'rgba(37, 99, 235, 0.35)';
              } else if (!card.classList.contains('is-today')) {
                card.style.borderColor = '';
              }
            }
          } else {
            card.style.transform = 'scale(1) translateY(0)';
            card.style.zIndex = '1';
            card.style.boxShadow = '';
            if (!card.classList.contains('is-today')) {
              card.style.borderColor = '';
            }
          }
        });
      });
    });

    grid.addEventListener('mouseleave', () => {
      resetAllCards();
    });

    window.addEventListener('resize', () => {
      cardData = [];
    }, { passive: true });
  }

  // Ensure Modal exists in DOM
  function ensureWeatherModal() {
    let modal = document.getElementById('weatherModal');
    if (modal) return modal;

    modal = document.createElement('dialog');
    modal.id = 'weatherModal';
    modal.className = 'weather-modal';
    modal.setAttribute('data-app-zoom', 'true');

    modal.innerHTML = `
      <div class="weather-modal-shell">
        <div class="weather-modal-head">
          <div class="weather-head-title">
            <span style="font-size:20px">⛅</span>
            <h2>Dự báo thời tiết 7 ngày</h2>
          </div>
          <div class="weather-head-actions">
            <div class="weather-city-select-wrap">
              <button id="weatherUseLocationBtn" class="weather-icon-btn weather-location-btn" type="button" title="Dùng vị trí hiện tại" aria-label="Dùng vị trí hiện tại" aria-pressed="false">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><circle cx="12" cy="12" r="8"/></svg>
              </button>
              <select id="weatherCitySelect" class="weather-city-select" aria-label="Chọn tỉnh hoặc thành phố dự phòng" title="Địa điểm dự phòng khi không dùng được GPS">
                ${Object.entries(CITIES).map(([k, v]) => `<option value="${k}">${v.name}</option>`).join('')}
              </select>
            </div>
            <button id="weatherRefreshBtn" class="weather-icon-btn" type="button" title="Làm mới dữ liệu">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            </button>
            <button class="weather-icon-btn" type="button" onclick="document.getElementById('weatherModal').close()" title="Đóng">✕</button>
          </div>
        </div>
        <div class="weather-modal-body" id="weatherModalBody">
          <div class="empty-state">Đang tải dữ liệu thời tiết...</div>
        </div>
        <div class="weather-modal-foot">
          <span>Dự báo thời gian thực múi giờ Việt Nam (UTC+7)</span>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    const select = modal.querySelector('#weatherCitySelect');
    select.value = selectedCityKey;
    select.onchange = function () {
      selectFallbackCity(this.value);
    };

    const locationBtn = modal.querySelector('#weatherUseLocationBtn');
    locationBtn.onclick = function () {
      requestCurrentLocation();
    };
    syncLocationControls();

    const refreshBtn = modal.querySelector('#weatherRefreshBtn');
    refreshBtn.onclick = function () {
      refreshBtn.classList.add('is-spinning');
      fetchWeatherData(true).finally(() => {
        setTimeout(() => refreshBtn.classList.remove('is-spinning'), 500);
      });
    };

    return modal;
  }

  let lastRenderedSig = null;

  // Populate Weather Modal Content
  function renderModalBody(force = false) {
    const modal = document.getElementById('weatherModal');
    if (!modal) return;
    const body = modal.querySelector('#weatherModalBody');
    if (!body) return;

    if (!currentWeatherState || !currentWeatherState.daily) {
      if (lastRenderedSig !== '__empty__') {
        body.innerHTML = '<div class="empty-state">Đang tải dữ liệu thời tiết...</div>';
        lastRenderedSig = '__empty__';
      }
      return;
    }

    const cur = currentWeatherState.current || {};
    const daily = currentWeatherState.daily;
    const coords = getActiveCoords();
    const sig = `${Number(coords.lat).toFixed(3)}_${Number(coords.lon).toFixed(3)}_${cur.temperature_2m}_${cur.weather_code}_${daily.time?.[0]}`;

    if (!force && lastRenderedSig === sig) {
      return; // Already rendered! No DOM demolition or re-parsing needed
    }
    lastRenderedSig = sig;

    const heroTheme = getHeroTheme(cur.weather_code);
    const heroIcon = getWeatherIcon(cur.weather_code, cur.is_day);
    const curTemp = Math.round(cur.temperature_2m);
    const apparent = Math.round(cur.apparent_temperature);
    const desc = getWeatherDesc(cur.weather_code);
    const todayMax = Math.round(daily.temperature_2m_max[0]);
    const todayMin = Math.round(daily.temperature_2m_min[0]);
    const advice = generateSchoolAdvice(currentWeatherState);

    // 7 days forecast rows
    let rowsHtml = '';
    const count = Math.min(7, daily.time.length);
    for (let i = 0; i < count; i++) {
      const dateStr = daily.time[i];
      const d = new Date(dateStr);
      const isToday = i === 0;
      const dayName = isToday ? 'Hôm nay' : WEEKDAY_NAMES[d.getDay()];
      const dateFormatted = `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
      const code = daily.weather_code[i];
      const icon = getWeatherIcon(code, 1);
      const statusText = getWeatherDesc(code);
      const min = Math.round(daily.temperature_2m_min[i]);
      const max = Math.round(daily.temperature_2m_max[i]);
      const rainProb = daily.precipitation_probability_max ? daily.precipitation_probability_max[i] : 0;

      rowsHtml += `
        <div class="weather-day-row ${isToday ? 'is-today' : ''}">
          <div class="weather-day-name">
            <span class="weather-day-title">${dayName}</span>
            <span class="weather-day-date">${dateFormatted}</span>
          </div>
          <div class="weather-day-icon">${icon}</div>
          <div class="weather-day-status">${statusText}</div>
          <div class="weather-temp-range">
            <span class="weather-min-temp">${min}°</span>
            <div class="weather-temp-bar-wrap">
              <div class="weather-temp-bar-fill" style="width: 100%;"></div>
            </div>
            <span class="weather-max-temp">${max}°</span>
          </div>
          <div class="weather-day-rain">
            ${rainProb > 0 ? `<span>💧 ${rainProb}%</span>` : '<span style="opacity:0.4">—</span>'}
          </div>
        </div>
      `;
    }

    body.innerHTML = `
      <div class="weather-hero-card ${heroTheme}">
        <div class="weather-hero-head-row">
          <div class="weather-hero-location-badge">
            <span class="weather-hero-location-pin">📍</span>
            <span class="weather-hero-location-name">${coords.name}</span>
            <span class="weather-hero-condition-tag">${desc}</span>
          </div>
          <div class="weather-hero-time-badge">Múi giờ Việt Nam (UTC+7)</div>
        </div>

        <div class="weather-hero-body-row">
          <div class="weather-hero-temp-group">
            <div class="weather-hero-icon">${heroIcon}</div>
            <div class="weather-hero-temp">${curTemp}°C</div>
          </div>
          <div class="weather-hero-chips-wrap">
            <div class="weather-hero-chip">
              <span>🌡️</span>
              <span>Cảm giác như: <b>${apparent}°C</b></span>
            </div>
            <div class="weather-hero-chip">
              <span>📊</span>
              <span>Biên độ hôm nay: <b>${todayMin}°C – ${todayMax}°C</b></span>
            </div>
          </div>
        </div>

        <div class="weather-hero-stats">
          <div class="weather-stat-item">
            <span class="weather-stat-label">Độ ẩm</span>
            <span class="weather-stat-value">${cur.relative_humidity_2m || 0}%</span>
          </div>
          <div class="weather-stat-item">
            <span class="weather-stat-label">Gió</span>
            <span class="weather-stat-value">${cur.wind_speed_10m || 0} km/h</span>
          </div>
          <div class="weather-stat-item">
            <span class="weather-stat-label">Lượng mưa</span>
            <span class="weather-stat-value">${cur.precipitation || 0} mm</span>
          </div>
          <div class="weather-stat-item">
            <span class="weather-stat-label">Mưa hôm nay</span>
            <span class="weather-stat-value">${daily.precipitation_probability_max ? daily.precipitation_probability_max[0] : 0}%</span>
          </div>
        </div>
      </div>

      <div class="weather-forecast-section">
        <div class="weather-forecast-heading">
          <h3>Dự báo cả tuần (7 ngày)</h3>
          <span style="font-size:12px;color:var(--muted)">Đơn vị: °C</span>
        </div>
        <div class="weather-forecast-list">
          ${rowsHtml}
        </div>
      </div>

      ${advice ? `
        <div class="weather-school-tip">
          <span class="weather-school-tip-icon">${advice.icon}</span>
          <div>
            <div style="font-weight:700;margin-bottom:2px">Lưu ý xếp lịch &amp; hoạt động tuần này:</div>
            <div>${advice.text}</div>
          </div>
        </div>
      ` : ''}
    `;
  }

  function updateAllWeatherUI() {
    syncLocationControls();
    updateAppbarBadge();
    updateWorkspaceOverview();
    renderModalBody(true);
  }

  function openWeatherModal() {
    const modal = ensureWeatherModal();
    renderModalBody(false);
    if (typeof modal.showModal === 'function') {
      modal.showModal();
    } else {
      modal.setAttribute('open', '');
    }
  }

  window.openWeatherModal = openWeatherModal;

  // Initialize on page load
  function init() {
    updateAppbarBadge();
    updateWorkspaceOverview();

    // Pre-create modal in background/idle so opening never has DOM construction lag
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(() => {
        ensureWeatherModal();
        renderModalBody(false);
      }, { timeout: 1200 });
    } else {
      setTimeout(() => {
        ensureWeatherModal();
        renderModalBody(false);
      }, 400);
    }

    // Hiển thị ngay bằng vị trí GPS đã lưu (nếu có), nếu không thì dùng tỉnh/thành dự phòng.
    // Không chờ GPS nên phần còn lại của trang và weather cache không bị chặn.
    fetchWeatherData(false);

    // Xin vị trí mới song song. Khi GPS trả về, chỉ cập nhật weather nếu vị trí thực sự thay đổi.
    requestCurrentLocation();

    // Refresh dữ liệu thời tiết mỗi 15 phút. Cache phía client/backend vẫn tránh request dư thừa.
    setInterval(() => fetchWeatherData(false), 15 * 60 * 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
