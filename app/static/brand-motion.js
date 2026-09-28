/**
 * Smart TKB - Brand Motion Engine
 * Tự động tạo hiệu ứng: Từng chữ hạ xuống (Drop-in) -> Quét tia sáng (Sweep Light & Lens Flare)
 * Đồng bộ với hoạt ảnh của biểu tượng brand-logo.svg (Chu kỳ 5.6s)
 */
(function (window, document) {
  'use strict';

  var BrandMotion = {
    /**
     * Biến đổi phần tử chứa chữ thương hiệu thành cấu trúc từng chữ hạ xuống và quét sáng
     */
    applySweepEffect: function (el) {
      if (!el || el.dataset.brandMotionReady) return;
      var text = el.textContent.trim().replace(/\s+/g, ' ');
      if (!text) return;

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
