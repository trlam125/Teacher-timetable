export function setupVoice({ start, consent, transcript, status, apply, target }) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    start.disabled = true; start.dataset.unavailable = 'true';
    status.textContent = 'Trình duyệt chưa hỗ trợ nhận giọng nói. Bạn vẫn có thể nhập văn bản bên dưới.';
  }
  let current;
  const reset = () => { current = null; start.textContent = 'Bắt đầu nói'; };
  start.onclick = () => {
    if (!Recognition) { status.textContent = 'Trình duyệt chưa hỗ trợ. Hãy nhập văn bản.'; return; }
    if (current) { current.stop(); return; }
    if (!consent.checked) { status.textContent = 'Cần đồng ý dùng dịch vụ nhận dạng của trình duyệt trước khi bật micro.'; return; }
    const recognition = new Recognition(); current = recognition;
    recognition.lang = 'vi-VN'; recognition.continuous = false; recognition.interimResults = false;
    recognition.onresult = event => {
      if (current !== recognition) return;
      const text = Array.from(event.results).filter(result => result.isFinal !== false).map(result => result[0].transcript).join(' ');
      transcript.value = text.slice(0, 2000);
      status.textContent = 'Đã nhận văn bản. Kiểm tra và sửa trước khi dùng; chưa gửi tới AI soạn bài.';
    };
    recognition.onerror = event => { if (current !== recognition) return; status.textContent = `Chưa nhận được giọng nói (${event.error || 'unknown'}). Kiểm tra quyền micro hoặc nhập văn bản.`; reset(); };
    recognition.onend = () => { if (current === recognition) reset(); };
    try { recognition.start(); start.textContent = 'Dừng nghe'; status.textContent = 'Đang nghe… Bấm Dừng nghe khi xong.'; }
    catch { reset(); status.textContent = 'Chưa mở được micro. Hãy kiểm tra quyền trình duyệt hoặc nhập văn bản.'; }
  };
  apply.onclick = () => {
    const text = transcript.value.trim();
    if (!text) { status.textContent = 'Nhập hoặc nhận một đoạn văn bản trước.'; return; }
    if (target.value.length + text.length + 1 > 3000) { status.textContent = 'Yêu cầu hiện tại quá dài. Rút gọn trước khi thêm.'; return; }
    target.value = [target.value.trim(), text].filter(Boolean).join('\n');
    status.textContent = 'Đã thêm vào Nội dung bắt buộc. Bạn có thể sửa trước khi tạo bài.';
  };
  window.addEventListener('pagehide', () => current?.abort());
  target.form?.addEventListener('reset', () => { current?.abort(); reset(); });
  consent.addEventListener('change', () => { if (!consent.checked) { current?.abort(); reset(); } });
  document.addEventListener('visibilitychange', () => { if (document.hidden) current?.abort(); });
}
