/**
 * Smart TKB - Perpetual Calendar & Clock (Lịch Vạn Niên & Đồng Hồ Việt Nam)
 * Thuật toán Âm lịch thiên văn Hồ Ngọc Đức (UTC+7)
 * Hiển thị đồng hồ thời gian thực, Dương lịch, Âm lịch, Can Chi, Tiết Khí, Giờ Hoàng Đạo & Ngày Lễ
 */
(function () {
  'use strict';

  const PI = Math.PI;
  const TIMEZONE = 7.0;

  function INT(d) {
    return Math.floor(d);
  }

  function pad(n) {
    return String(n).padStart(2, '0');
  }

  /* --------------------------------------------------------------------------
     1. THUẬT TOÁN ÂM LỊCH THIÊN VĂN (HỒ NGỌC ĐỨC)
     -------------------------------------------------------------------------- */
  function jdFromDate(dd, mm, yy) {
    let a = INT((14 - mm) / 12);
    let y = yy + 4800 - a;
    let m = mm + 12 * a - 3;
    let jd = dd + INT((153 * m + 2) / 5) + 365 * y + INT(y / 4) - INT(y / 100) + INT(y / 400) - 32045;
    if (jd < 2299161) {
      jd = dd + INT((153 * m + 2) / 5) + 365 * y + INT(y / 4) - 32083;
    }
    return jd;
  }

  function NewMoon(k) {
    let T = k / 1236.85;
    let T2 = T * T;
    let T3 = T2 * T;
    let dr = PI / 180;
    let Jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3;
    Jd1 += 0.00033 * Math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr);
    let M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3;
    let Mpr = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3;
    let F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3;
    let C1 = (0.1734 - 0.000393 * T) * Math.sin(M * dr) + 0.0021 * Math.sin(2 * dr * M);
    C1 -= 0.4068 * Math.sin(Mpr * dr) + 0.0161 * Math.sin(dr * 2 * Mpr);
    C1 -= 0.0004 * Math.sin(dr * 3 * Mpr);
    C1 += 0.0104 * Math.sin(dr * 2 * F) - 0.0051 * Math.sin(dr * (M + Mpr));
    C1 -= 0.0074 * Math.sin(dr * (M - Mpr)) + 0.0004 * Math.sin(dr * (2 * F + M));
    C1 -= 0.0004 * Math.sin(dr * (2 * F - M)) - 0.0006 * Math.sin(dr * (2 * F + Mpr));
    C1 += 0.0010 * Math.sin(dr * (2 * F - Mpr)) + 0.0005 * Math.sin(dr * (M + 2 * Mpr));
    let deltat;
    if (T < -11) {
      deltat = 0.001 + 0.000839 * T + 0.0002261 * T2 - 0.00000845 * T3 - 0.000000081 * T * T3;
    } else {
      deltat = -0.000278 + 0.000265 * T + 0.000262 * T2;
    }
    return Jd1 + C1 - deltat;
  }

  function SunLongitude(jdn) {
    let T = (jdn - 2451545.0) / 36525;
    let T2 = T * T;
    let dr = PI / 180;
    let M = 357.52910 + 35999.05030 * T - 0.0001559 * T2 - 0.00000048 * T * T2;
    let L0 = 280.46645 + 36000.76983 * T + 0.0003032 * T2;
    let DL = (1.914600 - 0.004817 * T - 0.000014 * T2) * Math.sin(dr * M);
    DL += (0.019993 - 0.000101 * T) * Math.sin(dr * 2 * M) + 0.000290 * Math.sin(dr * 3 * M);
    let L = L0 + DL;
    L = L * dr;
    L = L - PI * 2 * INT(L / (PI * 2));
    return L;
  }

  function getSunLongitude(dayNumber, timeZone) {
    return INT((SunLongitude(dayNumber - 0.5 - timeZone / 24) / PI) * 6);
  }

  function getNewMoonDay(k, timeZone) {
    return INT(NewMoon(k) + 0.5 + timeZone / 24);
  }

  function getLunarMonth11(yy, timeZone) {
    let off = jdFromDate(31, 12, yy) - 2415021;
    let k = INT(off / 29.530588853);
    let nm = getNewMoonDay(k, timeZone);
    let sunLong = getSunLongitude(nm, timeZone);
    if (sunLong >= 9) {
      nm = getNewMoonDay(k - 1, timeZone);
    }
    return nm;
  }

  function getLeapMonthOffset(a11, timeZone) {
    let k = INT((a11 - 2415021.076998695) / 29.530588853 + 0.5);
    let last = 0;
    let i = 1;
    let arc = getSunLongitude(getNewMoonDay(k + i, timeZone), timeZone);
    do {
      last = arc;
      i++;
      arc = getSunLongitude(getNewMoonDay(k + i, timeZone), timeZone);
    } while (arc !== last && i < 14);
    return i - 1;
  }

  const lunarCache = new Map();

  function convertSolar2Lunar(dd, mm, yy, timeZone = TIMEZONE) {
    let cacheKey = `${dd}/${mm}/${yy}/${timeZone}`;
    let cached = lunarCache.get(cacheKey);
    if (cached) return cached;

    let dayNumber = jdFromDate(dd, mm, yy);
    let k = INT((dayNumber - 2415021.076998695) / 29.530588853);
    let monthStart = getNewMoonDay(k + 1, timeZone);
    if (monthStart > dayNumber) {
      monthStart = getNewMoonDay(k, timeZone);
    }
    let a11 = getLunarMonth11(yy, timeZone);
    let b11 = a11;
    let lunarYear;
    if (a11 >= monthStart) {
      lunarYear = yy;
      a11 = getLunarMonth11(yy - 1, timeZone);
    } else {
      lunarYear = yy + 1;
      b11 = getLunarMonth11(yy + 1, timeZone);
    }
    let lunarDay = dayNumber - monthStart + 1;
    let diff = INT((monthStart - a11) / 29);
    let lunarLeap = 0;
    let lunarMonth = diff + 11;
    if (b11 - a11 > 365) {
      let leapMonthDiff = getLeapMonthOffset(a11, timeZone);
      if (diff >= leapMonthDiff) {
        lunarMonth = diff + 10;
        if (diff === leapMonthDiff) {
          lunarLeap = 1;
        }
      }
    }
    if (lunarMonth > 12) {
      lunarMonth = lunarMonth - 12;
    }
    if (lunarMonth >= 11 && diff < 4) {
      lunarYear -= 1;
    }
    let result = {
      day: lunarDay,
      month: lunarMonth,
      year: lunarYear,
      isLeap: lunarLeap === 1
    };
    lunarCache.set(cacheKey, result);
    return result;
  }

  /* --------------------------------------------------------------------------
     2. CAN CHI, TIẾT KHÍ, GIỜ HOÀNG ĐẠO & NGÀY LỄ
     -------------------------------------------------------------------------- */
  const CAN = ['Giáp', 'Ất', 'Bính', 'Đinh', 'Mậu', 'Kỷ', 'Canh', 'Tân', 'Nhâm', 'Quý'];
  const CHI = ['Tý', 'Sửu', 'Dần', 'Mão', 'Thìn', 'Tỵ', 'Ngọ', 'Mùi', 'Thân', 'Dậu', 'Tuất', 'Hợi'];
  const WEEKDAYS = ['Chủ nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];

  const SOLAR_TERMS = [
    'Xuân Phân', 'Thanh Minh', 'Cốc Vũ', 'Lập Hạ', 'Tiểu Mãn', 'Mang Chủng',
    'Hạ Chí', 'Tiểu Thử', 'Đại Thử', 'Lập Thu', 'Xử Thử', 'Bạch Lộ',
    'Thu Phân', 'Hàn Lộ', 'Sương Giáng', 'Lập Đông', 'Tiểu Tuyết', 'Đại Tuyết',
    'Đông Chí', 'Tiểu Hàn', 'Đại Hàn', 'Lập Xuân', 'Vũ Thủy', 'Kinh Trập'
  ];

  function getCanChiYear(year) {
    return `${CAN[(year + 6) % 10]} ${CHI[(year + 8) % 12]}`;
  }

  function getCanChiDay(dd, mm, yy) {
    let jd = jdFromDate(dd, mm, yy);
    return `${CAN[(jd + 9) % 10]} ${CHI[(jd + 1) % 12]}`;
  }

  function getCanChiMonth(lunarMonth, lunarYear) {
    return `${CAN[(lunarYear * 12 + lunarMonth + 3) % 10]} ${CHI[(lunarMonth + 1) % 12]}`;
  }

  function getSolarTerm(dd, mm, yy) {
    let jd = jdFromDate(dd, mm, yy);
    let sl = SunLongitude(jd - 0.5 - TIMEZONE / 24);
    let deg = (sl * 180) / PI;
    let idx = Math.floor(deg / 15) % 24;
    return SOLAR_TERMS[idx] || 'Bình thường';
  }

  // Giờ hoàng đạo theo Chi của ngày
  function getAuspiciousHours(dd, mm, yy) {
    let jd = jdFromDate(dd, mm, yy);
    let chiDayIdx = (jd + 1) % 12; // 0: Tý, 1: Sửu, 2: Dần...
    // Nhóm chi ngày tương đương: Tý/Ngọ, Sửu/Mùi, Dần/Thân, Mão/Dậu, Thìn/Tuất, Tỵ/Hợi
    const schedules = {
      0: ['Tý (23h-1h)', 'Sửu (1h-3h)', 'Mão (5h-7h)', 'Ngọ (11h-13h)', 'Thân (15h-17h)', 'Dậu (17h-19h)'], // Tý
      1: ['Dần (3h-5h)', 'Mão (5h-7h)', 'Tỵ (9h-11h)', 'Thân (15h-17h)', 'Tuất (19h-21h)', 'Hợi (21h-23h)'], // Sửu
      2: ['Tý (23h-1h)', 'Sửu (1h-3h)', 'Thìn (7h-9h)', 'Tỵ (9h-11h)', 'Mùi (13h-15h)', 'Tuất (19h-21h)'], // Dần
      3: ['Tý (23h-1h)', 'Dần (3h-5h)', 'Mão (5h-7h)', 'Ngọ (11h-13h)', 'Mùi (13h-15h)', 'Dậu (17h-19h)'], // Mão
      4: ['Dần (3h-5h)', 'Thìn (7h-9h)', 'Tỵ (9h-11h)', 'Thân (15h-17h)', 'Dậu (17h-19h)', 'Hợi (21h-23h)'], // Thìn
      5: ['Sửu (1h-3h)', 'Thìn (7h-9h)', 'Ngọ (11h-13h)', 'Mùi (13h-15h)', 'Tuất (19h-21h)', 'Hợi (21h-23h)'], // Tỵ
      6: ['Tý (23h-1h)', 'Sửu (1h-3h)', 'Mão (5h-7h)', 'Ngọ (11h-13h)', 'Thân (15h-17h)', 'Dậu (17h-19h)'], // Ngọ
      7: ['Dần (3h-5h)', 'Mão (5h-7h)', 'Tỵ (9h-11h)', 'Thân (15h-17h)', 'Tuất (19h-21h)', 'Hợi (21h-23h)'], // Mùi
      8: ['Tý (23h-1h)', 'Sửu (1h-3h)', 'Thìn (7h-9h)', 'Tỵ (9h-11h)', 'Mùi (13h-15h)', 'Tuất (19h-21h)'], // Thân
      9: ['Tý (23h-1h)', 'Dần (3h-5h)', 'Mão (5h-7h)', 'Ngọ (11h-13h)', 'Mùi (13h-15h)', 'Dậu (17h-19h)'], // Dậu
      10: ['Dần (3h-5h)', 'Thìn (7h-9h)', 'Tỵ (9h-11h)', 'Thân (15h-17h)', 'Dậu (17h-19h)', 'Hợi (21h-23h)'], // Tuất
      11: ['Sửu (1h-3h)', 'Thìn (7h-9h)', 'Ngọ (11h-13h)', 'Mùi (13h-15h)', 'Tuất (19h-21h)', 'Hợi (21h-23h)']  // Hợi
    };
    return schedules[chiDayIdx] || [];
  }

  const SOLAR_HOLIDAYS = {
    '1-1': 'Tết Dương Lịch',
    '14-2': 'Lễ tình nhân (Valentine)',
    '27-2': 'Ngày Thầy thuốc Việt Nam',
    '8-3': 'Quốc tế Phụ nữ',
    '26-3': 'Ngày thành lập Đoàn TNCS HCM',
    '30-4': 'Ngày Giải phóng miền Nam',
    '1-5': 'Quốc tế Lao động',
    '15-5': 'Ngày thành lập Đội TNTP HCM',
    '19-5': 'Kỷ niệm sinh nhật Bác Hồ',
    '1-6': 'Quốc tế Thiếu nhi',
    '27-7': 'Ngày Thương binh Liệt sĩ',
    '19-8': 'Cách mạng Tháng Tám',
    '2-9': 'Quốc khánh Việt Nam',
    '5-9': 'Ngày Khai giảng năm học mới 🎒',
    '20-10': 'Ngày Phụ nữ Việt Nam',
    '20-11': 'Ngày Nhà giáo Việt Nam 💐',
    '22-12': 'Ngày thành lập Quân đội Nhân dân VN',
    '25-12': 'Lễ Giáng sinh (Noel)'
  };

  const LUNAR_HOLIDAYS = {
    '1-1': 'Mùng 1 Tết Nguyên Đán',
    '2-1': 'Mùng 2 Tết',
    '3-1': 'Mùng 3 Tết',
    '15-1': 'Tết Nguyên Tiêu (Rằm tháng Giêng)',
    '3-3': 'Tết Hàn Thực',
    '10-3': 'Giỗ Tổ Hùng Vương (mùng 10/3 ÂL)',
    '15-4': 'Lễ Phật Đản',
    '5-5': 'Tết Đoan Ngọ',
    '15-7': 'Lễ Vu Lan (Rằm tháng 7)',
    '15-8': 'Tết Trung Thu (Rằm tháng 8)',
    '23-12': 'Tiễn Táo Quân về trời'
  };

  function getHolidays(sDay, sMonth, lDay, lMonth) {
    let res = [];
    let sKey = `${sDay}-${sMonth}`;
    let lKey = `${lDay}-${lMonth}`;
    if (SOLAR_HOLIDAYS[sKey]) res.push(SOLAR_HOLIDAYS[sKey]);
    if (LUNAR_HOLIDAYS[lKey]) res.push(LUNAR_HOLIDAYS[lKey]);
    return res;
  }

  /* --------------------------------------------------------------------------
     3. STATE QUẢN LÝ THỜI GIAN & LỊCH THÁNG
     -------------------------------------------------------------------------- */
  const VIETNAM_OFFSET_MS = 7 * 60 * 60 * 1000;
  let viewDate = new Date(); // Tháng đang xem
  let selectedDate = new Date(); // Ngày đang chọn xem chi tiết

  function getNowInVietnam() {
    // Lấy thời gian hiện tại chuẩn UTC+7
    let now = new Date();
    let utc = now.getTime() + now.getTimezoneOffset() * 60000;
    return new Date(utc + VIETNAM_OFFSET_MS);
  }

  /* --------------------------------------------------------------------------
     4. KHỞI TẠO VÀ HIỂN THỊ MODAL LỊCH VẠN NIÊN
     -------------------------------------------------------------------------- */
  function ensureCalendarModal() {
    let modal = document.getElementById('calendarModal');
    if (modal) return modal;

    modal = document.createElement('dialog');
    modal.id = 'calendarModal';
    modal.className = 'calendar-modal';
    modal.setAttribute('data-app-zoom', 'true');

    modal.innerHTML = `
      <div class="calendar-modal-shell">
        <header class="calendar-modal-head">
          <div class="calendar-head-title">
            <span class="calendar-head-icon" aria-hidden="true">📅</span>
            <div>
              <h2>Đồng hồ &amp; Lịch Vạn Niên</h2>
              <span class="calendar-head-sub">Múi giờ Việt Nam (UTC+7) · Âm dương đối chiếu</span>
            </div>
          </div>
          <div class="calendar-head-actions">
            <button class="calendar-icon-btn" type="button" onclick="document.getElementById('calendarModal').close()" title="Đóng cửa sổ" aria-label="Đóng">✕</button>
          </div>
        </header>

        <div class="calendar-modal-body">
          <!-- CỘT TRÁI: ĐỒNG HỒ & CHI TIẾT NGÀY -->
          <aside class="calendar-spotlight-col">
            <!-- ĐỒNG HỒ THỜI GIAN THỰC -->
            <div class="calendar-clock-card">
              <div class="calendar-clock-dial-wrap">
                <svg class="calendar-analog-clock" viewBox="0 0 100 100" aria-hidden="true">
                  <circle cx="50" cy="50" r="46" class="clock-face"/>
                  <!-- Vạch số 12, 3, 6, 9 -->
                  <line x1="50" y1="9" x2="50" y2="15" class="clock-tick-major"/>
                  <line x1="91" y1="50" x2="85" y2="50" class="clock-tick-major"/>
                  <line x1="50" y1="91" x2="50" y2="85" class="clock-tick-major"/>
                  <line x1="9" y1="50" x2="15" y2="50" class="clock-tick-major"/>
                  <!-- Kim -->
                  <line id="calendarHourHand" x1="50" y1="50" x2="50" y2="24" class="clock-hand clock-hour"/>
                  <line id="calendarMinuteHand" x1="50" y1="50" x2="50" y2="16" class="clock-hand clock-minute"/>
                  <line id="calendarSecondHand" x1="50" y1="56" x2="50" y2="12" class="clock-hand clock-second"/>
                  <circle cx="50" cy="50" r="3.5" class="clock-pin"/>
                </svg>
              </div>
              <div class="calendar-digital-wrap">
                <div class="calendar-digital-time" id="calendarDigitalTime">--:--:--</div>
                <div class="calendar-digital-date" id="calendarDigitalDate">Đang cập nhật...</div>
              </div>
            </div>

            <!-- CHI TIẾT NGÀY ĐANG CHỌN -->
            <div class="calendar-day-detail-card" id="calendarDayDetailCard">
              <!-- Render động -->
            </div>
          </aside>

          <!-- CỘT PHẢI: LƯỚI LỊCH THÁNG (LỊCH VẠN NIÊN) -->
          <main class="calendar-grid-col">
            <!-- THANH ĐIỀU HƯỚNG THÁNG -->
            <div class="calendar-nav-toolbar">
              <div class="calendar-month-picker-wrap">
                <button type="button" class="calendar-btn-nav" id="calendarPrevMonthBtn" title="Tháng trước" aria-label="Tháng trước">‹</button>
                <div class="calendar-month-display">
                  <span class="calendar-month-label" id="calendarMonthLabel">Tháng --, ----</span>
                  <span class="calendar-lunar-month-label" id="calendarLunarMonthLabel">Tháng -- ÂL</span>
                </div>
                <button type="button" class="calendar-btn-nav" id="calendarNextMonthBtn" title="Tháng sau" aria-label="Tháng sau">›</button>
              </div>

              <div class="calendar-toolbar-actions">
                <button type="button" class="calendar-btn-today" id="calendarTodayBtn">Hôm nay</button>
              </div>
            </div>

            <!-- TIÊU ĐỀ THỨ TRONG TUẦN -->
            <div class="calendar-weekday-header">
              <span class="weekday-item">T2</span>
              <span class="weekday-item">T3</span>
              <span class="weekday-item">T4</span>
              <span class="weekday-item">T5</span>
              <span class="weekday-item">T6</span>
              <span class="weekday-item is-weekend">T7</span>
              <span class="weekday-item is-weekend is-sunday">CN</span>
            </div>

            <!-- BẢNG CÁC Ô NGÀY TRONG THÁNG (VIEWPORT CÓ ANIMATION LƯỚT) -->
            <div class="calendar-grid-viewport" id="calendarGridViewport">
              <div class="calendar-days-grid" id="calendarDaysGrid">
                <!-- Render bằng JS -->
              </div>
            </div>

            <div class="calendar-grid-legend">
              <span><b style="color:var(--ink)">Số lớn:</b> Dương lịch</span>
              <span><b style="color:var(--muted)">Số nhỏ:</b> Âm lịch</span>
              <span><b style="color:#e11d48">Chữ đỏ:</b> Mùng 1 / Rằm 15</span>
              <span><b style="color:#d97706">★:</b> Ngày lễ</span>
            </div>
          </main>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Khởi tạo và vẽ sẵn lưới tháng hiện tại để khi bấm mở thì mở tức thì không có độ trễ
    let now = getNowInVietnam();
    viewDate = new Date(now.getFullYear(), now.getMonth(), 1);
    selectedDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    renderCalendarGrid();
    renderSelectedDayDetail();
    modal.dataset.renderedMonth = `${now.getFullYear()}-${now.getMonth()}`;
    modal.dataset.renderedDate = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;

    // Gắn sự kiện nút điều hướng tháng (animation lướt)
    modal.querySelector('#calendarPrevMonthBtn').onclick = () => {
      viewDate.setMonth(viewDate.getMonth() - 1);
      renderCalendarGrid('prev');
    };

    modal.querySelector('#calendarNextMonthBtn').onclick = () => {
      viewDate.setMonth(viewDate.getMonth() + 1);
      renderCalendarGrid('next');
    };

    modal.querySelector('#calendarTodayBtn').onclick = () => {
      let tNow = getNowInVietnam();
      let prevMonthIndex = viewDate.getFullYear() * 12 + viewDate.getMonth();
      let targetMonthIndex = tNow.getFullYear() * 12 + tNow.getMonth();
      let direction = null;
      if (targetMonthIndex > prevMonthIndex) direction = 'next';
      else if (targetMonthIndex < prevMonthIndex) direction = 'prev';

      viewDate = new Date(tNow.getFullYear(), tNow.getMonth(), 1);
      selectedDate = new Date(tNow.getFullYear(), tNow.getMonth(), tNow.getDate());
      renderCalendarGrid(direction);
      renderSelectedDayDetail();
    };

    // Hỗ trợ vuốt tay (touch swipe) sang ngang trên điện thoại / máy tính bảng
    let viewport = modal.querySelector('#calendarGridViewport');
    if (viewport) {
      let startX = 0;
      let startY = 0;
      viewport.addEventListener('touchstart', (e) => {
        if (e.touches.length === 1) {
          startX = e.touches[0].clientX;
          startY = e.touches[0].clientY;
        }
      }, { passive: true });

      viewport.addEventListener('touchend', (e) => {
        if (e.changedTouches.length === 1) {
          let dx = e.changedTouches[0].clientX - startX;
          let dy = e.changedTouches[0].clientY - startY;
          if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.5) {
            if (dx < 0) {
              modal.querySelector('#calendarNextMonthBtn')?.click();
            } else {
              modal.querySelector('#calendarPrevMonthBtn')?.click();
            }
          }
        }
      }, { passive: true });
    }

    // Hỗ trợ phím mũi tên trái / phải để lướt tháng
    modal.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        modal.querySelector('#calendarPrevMonthBtn')?.click();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        modal.querySelector('#calendarNextMonthBtn')?.click();
      }
    });

    return modal;
  }

  /* --------------------------------------------------------------------------
     5. RENDER CHI TIẾT NGÀY ĐANG CHỌN (DAY SPOTLIGHT)
     -------------------------------------------------------------------------- */
  function renderSelectedDayDetail() {
    let modal = document.getElementById('calendarModal');
    if (!modal) return;
    let card = modal.querySelector('#calendarDayDetailCard');
    if (!card) return;

    let sDay = selectedDate.getDate();
    let sMonth = selectedDate.getMonth() + 1;
    let sYear = selectedDate.getFullYear();
    let sWDay = selectedDate.getDay();

    let lunar = convertSolar2Lunar(sDay, sMonth, sYear, TIMEZONE);
    let canChiDay = getCanChiDay(sDay, sMonth, sYear);
    let canChiMonth = getCanChiMonth(lunar.month, lunar.year);
    let canChiYear = getCanChiYear(lunar.year);
    let solarTerm = getSolarTerm(sDay, sMonth, sYear);
    let auspicious = getAuspiciousHours(sDay, sMonth, sYear);
    let holidays = getHolidays(sDay, sMonth, lunar.day, lunar.month);

    let isSelectedToday = false;
    let now = getNowInVietnam();
    if (sDay === now.getDate() && sMonth === (now.getMonth() + 1) && sYear === now.getFullYear()) {
      isSelectedToday = true;
    }

    card.innerHTML = `
      <div class="spotlight-head">
        <div class="spotlight-eyebrow">
          <span>${WEEKDAYS[sWDay]}</span>
          ${isSelectedToday ? '<span class="spotlight-today-tag">Hôm nay</span>' : ''}
        </div>
        <div class="spotlight-solar-date">
          <span class="solar-day-num">${pad(sDay)}</span>
          <div class="solar-month-year">
            <span class="solar-my-text">Tháng ${sMonth}</span>
            <span class="solar-y-text">Năm ${sYear}</span>
          </div>
        </div>
      </div>

      <div class="spotlight-lunar-banner">
        <div class="lunar-tag">ÂM LỊCH</div>
        <div class="lunar-large-date">
          Ngày <b>${lunar.day}</b> Tháng <b>${lunar.month}</b>${lunar.isLeap ? ' (Nhuận)' : ''}
        </div>
        <div class="lunar-canchi-line">
          Năm <b>${canChiYear}</b> · Tháng <b>${canChiMonth}</b> · Ngày <b>${canChiDay}</b>
        </div>
      </div>

      ${holidays.length ? `
        <div class="spotlight-holiday-pill">
          <span class="holiday-star">★</span>
          <span><b>Sự kiện:</b> ${holidays.join(' · ')}</span>
        </div>
      ` : ''}

      <div class="spotlight-meta-list">
        <div class="spotlight-meta-item">
          <span class="meta-label">Tiết khí:</span>
          <span class="meta-value">${solarTerm}</span>
        </div>
        <div class="spotlight-meta-item">
          <span class="meta-label">Giờ Hoàng Đạo:</span>
          <div class="auspicious-tags">
            ${auspicious.map(h => `<span class="auspicious-pill">${h}</span>`).join('')}
          </div>
        </div>
      </div>
    `;
  }

  /* --------------------------------------------------------------------------
     6. RENDER BẢNG LỊCH THÁNG (CALENDAR GRID CÓ ANIMATION LƯỚT)
     -------------------------------------------------------------------------- */
  function buildCalendarMonthHtml(vYear, vMonth) {
    let now = getNowInVietnam();
    let todayD = now.getDate();
    let todayM = now.getMonth();
    let todayY = now.getFullYear();

    let selD = selectedDate.getDate();
    let selM = selectedDate.getMonth();
    let selY = selectedDate.getFullYear();

    // Ngày đầu tháng & số ngày trong tháng
    let firstDayObj = new Date(vYear, vMonth, 1);
    let startDayOfWeek = (firstDayObj.getDay() + 6) % 7; // Chuyển sang T2 = 0, CN = 6
    let daysInMonth = new Date(vYear, vMonth + 1, 0).getDate();
    let daysInPrevMonth = new Date(vYear, vMonth, 0).getDate();

    let html = '';

    // Ô của tháng trước (faded)
    for (let i = startDayOfWeek - 1; i >= 0; i--) {
      let pDay = daysInPrevMonth - i;
      let pDate = new Date(vYear, vMonth - 1, pDay);
      let pLunar = convertSolar2Lunar(pDay, pDate.getMonth() + 1, pDate.getFullYear(), TIMEZONE);
      let lunarText = pLunar.day === 1 ? `${pLunar.day}/${pLunar.month}` : String(pLunar.day);

      html += `
        <button type="button" class="calendar-day-cell is-other-month" data-date="${pDate.getFullYear()}-${pDate.getMonth()}-${pDay}">
          <span class="cell-solar">${pDay}</span>
          <span class="cell-lunar">${lunarText}</span>
        </button>
      `;
    }

    // Các ô của tháng hiện tại
    for (let d = 1; d <= daysInMonth; d++) {
      let cLunar = convertSolar2Lunar(d, vMonth + 1, vYear, TIMEZONE);
      let isToday = (d === todayD && vMonth === todayM && vYear === todayY);
      let isSelected = (d === selD && vMonth === selM && vYear === selY);
      let isMajorLunar = (cLunar.day === 1 || cLunar.day === 15);
      let holidays = getHolidays(d, vMonth + 1, cLunar.day, cLunar.month);
      let hasHoliday = holidays.length > 0;

      let lunarDisplay = cLunar.day === 1 ? `${cLunar.day}/${cLunar.month}` : String(cLunar.day);

      let classes = ['calendar-day-cell'];
      if (isToday) classes.push('is-today');
      if (isSelected) classes.push('is-selected');
      if (isMajorLunar) classes.push('is-major-lunar');
      if (hasHoliday) classes.push('has-holiday');

      html += `
        <button type="button" class="${classes.join(' ')}" data-date="${vYear}-${vMonth}-${d}" title="${d}/${vMonth + 1}/${vYear} (ÂL: ${cLunar.day}/${cLunar.month})${hasHoliday ? ' - ' + holidays[0] : ''}">
          <span class="cell-solar">${d}</span>
          <span class="cell-lunar">${lunarDisplay}</span>
          ${hasHoliday ? '<span class="cell-holiday-dot" aria-hidden="true">★</span>' : ''}
        </button>
      `;
    }

    // Ô của tháng sau để làm đầy lưới 6 tuần
    let totalCells = startDayOfWeek + daysInMonth;
    let nextDaysCount = (totalCells % 7 === 0) ? 0 : 7 - (totalCells % 7);
    if (totalCells + nextDaysCount < 42) {
      nextDaysCount += 7; // Giữ chiều cao lưới ổn định
    }

    for (let nd = 1; nd <= nextDaysCount; nd++) {
      let nDate = new Date(vYear, vMonth + 1, nd);
      let nLunar = convertSolar2Lunar(nd, nDate.getMonth() + 1, nDate.getFullYear(), TIMEZONE);
      let lunarText = nLunar.day === 1 ? `${nLunar.day}/${nLunar.month}` : String(nLunar.day);

      html += `
        <button type="button" class="calendar-day-cell is-other-month" data-date="${nDate.getFullYear()}-${nDate.getMonth()}-${nd}">
          <span class="cell-solar">${nd}</span>
          <span class="cell-lunar">${lunarText}</span>
        </button>
      `;
    }

    return html;
  }

  function bindDayCellEvents(gridElement) {
    if (!gridElement) return;
    let modal = document.getElementById('calendarModal');
    if (!modal) return;

    gridElement.querySelectorAll('.calendar-day-cell').forEach(btn => {
      btn.onclick = function () {
        let raw = this.getAttribute('data-date');
        if (!raw) return;
        let parts = raw.split('-').map(Number);
        selectedDate = new Date(parts[0], parts[1], parts[2]);

        let isOtherMonth = (parts[1] !== viewDate.getMonth() || parts[0] !== viewDate.getFullYear());
        if (isOtherMonth) {
          let oldIndex = viewDate.getFullYear() * 12 + viewDate.getMonth();
          let newIndex = parts[0] * 12 + parts[1];
          let dir = newIndex > oldIndex ? 'next' : 'prev';
          viewDate = new Date(parts[0], parts[1], 1);
          renderCalendarGrid(dir);
        } else {
          // Trong cùng tháng: chỉ đổi ô được chọn tức thì
          gridElement.querySelectorAll('.calendar-day-cell.is-selected').forEach(c => c.classList.remove('is-selected'));
          btn.classList.add('is-selected');
        }
        renderSelectedDayDetail();
      };
    });
  }

  function renderCalendarGrid(direction = null) {
    let modal = document.getElementById('calendarModal');
    if (!modal) return;

    let vYear = viewDate.getFullYear();
    let vMonth = viewDate.getMonth(); // 0-based

    // Cập nhật tiêu đề tháng
    let monthLabel = modal.querySelector('#calendarMonthLabel');
    if (monthLabel) {
      monthLabel.textContent = `Tháng ${vMonth + 1}, ${vYear}`;
    }

    // Tính ước lượng tháng Âm lịch tương ứng của giữa tháng
    let midLunar = convertSolar2Lunar(15, vMonth + 1, vYear, TIMEZONE);
    let lunarMonthLabel = modal.querySelector('#calendarLunarMonthLabel');
    if (lunarMonthLabel) {
      let canChiYear = getCanChiYear(midLunar.year);
      lunarMonthLabel.textContent = `Tháng ${midLunar.month} ÂL · Năm ${canChiYear}`;
    }

    // Animation lướt cho tiêu đề tháng
    let monthDisplay = modal.querySelector('.calendar-month-display');
    if (monthDisplay && direction) {
      monthDisplay.classList.remove('slide-month-next', 'slide-month-prev');
      void monthDisplay.offsetWidth; // Force reflow
      monthDisplay.classList.add(direction === 'next' ? 'slide-month-next' : 'slide-month-prev');
    }

    let viewport = modal.querySelector('#calendarGridViewport');
    let currentGrid = modal.querySelector('#calendarDaysGrid');
    let html = buildCalendarMonthHtml(vYear, vMonth);

    // Nếu không có hiệu ứng lướt (mở modal lần đầu hoặc cùng tháng)
    if (!direction || !viewport || !currentGrid) {
      if (viewport) {
        viewport.querySelectorAll('.calendar-days-grid').forEach(el => {
          if (el !== currentGrid) el.remove();
        });
      }
      if (currentGrid) {
        currentGrid.className = 'calendar-days-grid';
        currentGrid.innerHTML = html;
        bindDayCellEvents(currentGrid);
      }
      return;
    }

    // ANIMATION LƯỚT:
    // 1. Dọn dẹp ngay các lưới đang lướt ra trước đó nếu người dùng nhấn chuyển tháng liên tục
    viewport.querySelectorAll('.calendar-days-grid.is-leaving').forEach(el => el.remove());

    // 2. Chuyển lưới hiện tại thành lưới trượt ra (is-leaving)
    let oldGrid = currentGrid;
    oldGrid.removeAttribute('id');
    oldGrid.classList.remove('is-entering', 'slide-in-right', 'slide-in-left');
    oldGrid.classList.add('is-leaving');
    oldGrid.classList.add(direction === 'next' ? 'slide-out-left' : 'slide-out-right');

    // 3. Tạo lưới mới trượt vào (is-entering)
    let newGrid = document.createElement('div');
    newGrid.id = 'calendarDaysGrid';
    newGrid.className = `calendar-days-grid is-entering ${direction === 'next' ? 'slide-in-right' : 'slide-in-left'}`;
    newGrid.innerHTML = html;
    bindDayCellEvents(newGrid);

    viewport.appendChild(newGrid);

    // 4. Dọn dẹp khi animation kết thúc
    let cleaned = false;
    let onAnimationDone = () => {
      if (cleaned) return;
      cleaned = true;
      if (oldGrid.parentNode) {
        oldGrid.remove();
      }
      newGrid.classList.remove('is-entering', 'slide-in-right', 'slide-in-left');
    };

    newGrid.addEventListener('animationend', onAnimationDone, { once: true });
    setTimeout(onAnimationDone, 300);
  }

  /* --------------------------------------------------------------------------
     7. VÒNG LẶP ĐỒNG HỒ THỜI GIAN THỰC (LIVE CLOCK TICKER)
     -------------------------------------------------------------------------- */
  let clockTimer = null;

  function updateLiveClock() {
    let modal = document.getElementById('calendarModal');
    if (!modal) return;

    let now = getNowInVietnam();
    let hours = now.getHours();
    let minutes = now.getMinutes();
    let seconds = now.getSeconds();

    // Cập nhật số điện tử
    let digitalEl = modal.querySelector('#calendarDigitalTime');
    if (digitalEl) {
      digitalEl.textContent = `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
    }

    let dateEl = modal.querySelector('#calendarDigitalDate');
    if (dateEl) {
      let w = WEEKDAYS[now.getDay()];
      dateEl.textContent = `${w}, ngày ${pad(now.getDate())}/${pad(now.getMonth() + 1)}/${now.getFullYear()}`;
    }

    // Cập nhật kim đồng hồ analog
    let hourDeg = (hours % 12) * 30 + minutes * 0.5;
    let minDeg = minutes * 6 + seconds * 0.1;
    let secDeg = seconds * 6;

    let hHand = modal.querySelector('#calendarHourHand');
    let mHand = modal.querySelector('#calendarMinuteHand');
    let sHand = modal.querySelector('#calendarSecondHand');

    if (hHand) hHand.setAttribute('transform', `rotate(${hourDeg} 50 50)`);
    if (mHand) mHand.setAttribute('transform', `rotate(${minDeg} 50 50)`);
    if (sHand) sHand.setAttribute('transform', `rotate(${secDeg} 50 50)`);
  }

  function startLiveClock() {
    updateLiveClock();
    if (!clockTimer) {
      clockTimer = setInterval(updateLiveClock, 1000);
    }
  }

  /* --------------------------------------------------------------------------
     8. HÀM MỞ MODAL LỊCH VẠN NIÊN (HỖ TRỢ DATA-APP-ZOOM)
     -------------------------------------------------------------------------- */
  let isOpeningCalendar = false;

  function openCalendarModal() {
    let modal = ensureCalendarModal();
    if (!modal) return;
    if (modal.open || isOpeningCalendar) return;

    isOpeningCalendar = true;
    setTimeout(() => { isOpeningCalendar = false; }, 360);

    let now = getNowInVietnam();
    let mKey = `${now.getFullYear()}-${now.getMonth()}`;
    let dKey = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;

    // Chỉ tính toán và render lại khi sang tháng mới hoặc sang ngày mới
    if (modal.dataset.renderedMonth !== mKey || modal.dataset.renderedDate !== dKey) {
      viewDate = new Date(now.getFullYear(), now.getMonth(), 1);
      selectedDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      renderCalendarGrid();
      renderSelectedDayDetail();
      modal.dataset.renderedMonth = mKey;
      modal.dataset.renderedDate = dKey;
    }

    startLiveClock();

    if (typeof modal.showModal === 'function') {
      modal.showModal();
    } else {
      modal.setAttribute('open', '');
    }
  }

  window.openCalendarModal = openCalendarModal;

  // Tự động gán sự kiện mở Lịch Vạn Niên cho tất cả các nút .appbar-datetime
  function bindAppbarDatetimeTriggers() {
    let targets = document.querySelectorAll('.appbar-datetime');
    targets.forEach(btn => {
      btn.setAttribute('title', 'Xem Đồng hồ & Lịch Vạn Niên (Âm Dương đối chiếu)');
      if (btn.dataset.calendarTriggerBound === '1') return;
      btn.dataset.calendarTriggerBound = '1';
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        openCalendarModal();
      });
    });
  }

  function init() {
    // Khởi tạo trước modal khi rảnh để mở tức thì
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(() => {
        ensureCalendarModal();
      }, { timeout: 1500 });
    } else {
      setTimeout(ensureCalendarModal, 600);
    }

    bindAppbarDatetimeTriggers();
    // Quan sát DOM nếu appbar-datetime được tạo muộn
    let observer = new MutationObserver(() => {
      bindAppbarDatetimeTriggers();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
