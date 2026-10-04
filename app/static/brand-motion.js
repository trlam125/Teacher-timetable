/**
 * Smart TKB - Brand Motion Engine
 * Tự động đồng bộ hoá hoạt ảnh Logo và Dòng chữ "Smart TKB" trên cùng 1 trục thời gian (Chu kỳ 5.6s)
 * - Từng chữ hạ xuống (Drop-in) đồng bộ với việc dựng khung Logo (0% - 34%)
 * - Vệt sáng lướt qua Logo rồi tiếp nối quét ngang qua dòng chữ (36% - 62%)
 * - Lắng đọng hào quang dịu êm & hiển thị tĩnh cho người dùng dễ đọc (64% - 86%)
 * - Cả Logo và dòng chữ cùng kết thúc nhịp nhàng (86% - 96%) và nghỉ trước chu kỳ mới
 */
(function (window, document) {
  'use strict';

  var BRAND_SVG_HTML =
    '<svg class="brand-motion-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-labelledby="brandLogoTitle brandLogoDesc">' +
    '<title id="brandLogoTitle">Smart TKB</title>' +
    '<desc id="brandLogoDesc">Biểu tượng lịch học thông minh có hiệu ứng động</desc>' +
    '<defs>' +
      '<linearGradient id="brandMotionBg" x1="8" y1="8" x2="56" y2="58" gradientUnits="userSpaceOnUse">' +
        '<stop stop-color="#2F80ED"/>' +
        '<stop offset="0.55" stop-color="#4F6BF6"/>' +
        '<stop offset="1" stop-color="#7C3AED"/>' +
      '</linearGradient>' +
      '<linearGradient id="brandMotionAccent" x1="21" y1="35" x2="44" y2="48" gradientUnits="userSpaceOnUse">' +
        '<stop stop-color="#7DE8FF"/>' +
        '<stop offset="1" stop-color="#C4B5FD"/>' +
      '</linearGradient>' +
      '<linearGradient id="brandMotionShine" x1="0%" y1="0%" x2="100%" y2="100%">' +
        '<stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/>' +
        '<stop offset="45%" stop-color="#FFFFFF" stop-opacity="0"/>' +
        '<stop offset="50%" stop-color="#FFFFFF" stop-opacity="0.32"/>' +
        '<stop offset="55%" stop-color="#FFFFFF" stop-opacity="0"/>' +
        '<stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/>' +
      '</linearGradient>' +
      '<clipPath id="brandMotionClip">' +
        '<rect x="5" y="5" width="54" height="54" rx="17"/>' +
      '</clipPath>' +
    '</defs>' +
    '<rect class="logo-outline" x="5" y="5" width="54" height="54" rx="17" stroke="url(#brandMotionBg)"/>' +
    '<rect class="logo-base" x="5" y="5" width="54" height="54" rx="17" fill="url(#brandMotionBg)"/>' +
    '<g clip-path="url(#brandMotionClip)">' +
      '<rect class="shine" x="-30" y="-30" width="120" height="120" fill="url(#brandMotionShine)"/>' +
    '</g>' +
    '<rect class="draw-stroke calendar-box" x="14.5" y="17.5" width="35" height="32" rx="7" stroke="#FFFFFF" stroke-width="3"/>' +
    '<path class="draw-stroke calendar-divider" d="M15 27h34" stroke="#FFFFFF" stroke-width="3"/>' +
    '<path class="draw-stroke calendar-rings" d="M23 14v7M41 14v7" stroke="#FFFFFF" stroke-width="3"/>' +
    '<path class="draw-stroke calendar-slots" d="M22 35h7M35 35h7M22 42h7" stroke="#FFFFFF" stroke-width="3"/>' +
    '<path class="draw-stroke checkmark" d="m34.5 42 3.8 3.6 7.2-8.4" stroke="url(#brandMotionAccent)" stroke-width="3.4"/>' +
    '<circle class="badge-halo" cx="51" cy="13" r="4.2" fill="#7DE8FF"/>' +
    '<circle class="badge" cx="51" cy="13" r="4.2" fill="#7DE8FF" stroke="#FFFFFF" stroke-width="2"/>' +
  '</svg>';

  var BrandMotion = {
    /**
     * Chuyển đổi thẻ <img> logo bên cạnh chữ thành inline SVG
     * để cả logo và chữ cùng nằm trong cùng một DOM context và chạy trên cùng 1 clock CSS duy nhất.
     */
    syncLogo: function (el) {
      if (!el) return;
      var container = el.closest('a, .brand-with-logo, .landing-brand, .auth-brand, header, .appbar');
      if (!container) return;
      var img = container.querySelector('img[src*="brand-logo"]');
      if (!img || img.dataset.brandLogoInlined) return;

      var temp = document.createElement('div');
      temp.innerHTML = BRAND_SVG_HTML.trim();
      var svg = temp.firstElementChild;
      if (!svg) return;

      var extraClasses = (img.className || '').trim();
      if (extraClasses) {
        svg.className.baseVal = (svg.className.baseVal + ' ' + extraClasses).trim();
      }
      svg.dataset.brandLogoInlined = 'true';
      img.parentNode.replaceChild(svg, img);
    },

    /**
     * Biến đổi phần tử chứa chữ thương hiệu thành cấu trúc từng chữ hạ xuống và quét sáng đồng bộ
     */
    applySweepEffect: function (el) {
      if (!el || el.dataset.brandMotionReady) return;
      var text = el.textContent.trim().replace(/\s+/g, ' ');
      if (!text) return;

      // Đồng bộ hoá logo bên cạnh cùng thời điểm
      this.syncLogo(el);

      // Giữ nguyên accessibility cho screen readers
      el.setAttribute('aria-label', text);
      el.dataset.brandMotionReady = 'true';
      el.dataset.originalText = text;

      // Làm sạch và thêm class hiệu ứng
      el.innerHTML = '';
      el.classList.add('brand-motion-sweep');

      var textWrap = document.createElement('span');
      textWrap.className = 'brand-sweep-text';
      textWrap.dataset.brandText = text;

      var charIndex = 0;
      var words = text.split(' ');

      words.forEach(function (word, wIdx) {
        var wordSpan = document.createElement('span');
        wordSpan.className = 'brand-word';

        for (var i = 0; i < word.length; i++) {
          var charSpan = document.createElement('span');
          charSpan.className = 'brand-char brand-char-' + charIndex;
          charSpan.textContent = word[i];
          wordSpan.appendChild(charSpan);
          charIndex++;
        }

        textWrap.appendChild(wordSpan);

        if (wIdx < words.length - 1) {
          var spaceSpan = document.createElement('span');
          spaceSpan.className = 'brand-char-space';
          spaceSpan.innerHTML = '&nbsp;';
          textWrap.appendChild(spaceSpan);
        }
      });

      // Tia sáng quét ngang (Light beam)
      var flareBeam = document.createElement('span');
      flareBeam.className = 'brand-flare-beam';
      flareBeam.setAttribute('aria-hidden', 'true');

      // Hào quang lắng đọng dịu êm (Settle glow)
      var settleGlow = document.createElement('span');
      settleGlow.className = 'brand-settle-glow';
      settleGlow.setAttribute('aria-hidden', 'true');

      el.appendChild(textWrap);
      el.appendChild(flareBeam);
      el.appendChild(settleGlow);
    },

    /**
     * Tự động dò tìm tất cả vị trí tên thương hiệu "Smart TKB" trên trang
     */
    autoInit: function (selector) {
      selector = selector || '.landing-brand > span, .appbar-brand-copy > span:first-child, .appbar-brand > span:not(.appbar-brand-copy), .workspace-appbar-brand > span, .auth-brand > span, .brand-with-logo > span, a.brand > span';
      var self = this;
      var elements = document.querySelectorAll(selector);
      elements.forEach(function (el) {
        if (!el || el.dataset.brandMotionReady) return;
        var text = (el.textContent || '').replace(/\s+/g, ' ').trim();
        if (text.indexOf('Smart TKB') !== -1) {
          self.applySweepEffect(el);
        }
      });
    }
  };

  window.BrandMotion = BrandMotion;

  // Tự động kích hoạt khi DOM sẵn sàng
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        BrandMotion.autoInit();
      });
    } else {
      BrandMotion.autoInit();
    }
    // Fallback đảm bảo chạy ngay cả khi có script load sau
    window.addEventListener('load', function () {
      BrandMotion.autoInit();
    });
  }
})(window, document);
