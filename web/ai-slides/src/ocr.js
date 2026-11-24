let current;
const terminate = token => {
  if (!token?.worker || token.terminated) return;
  token.terminated = true;
  return token.worker.terminate();
};

export function cancelOCR() {
  if (!current) return;
  current.cancelled = true; terminate(current);
  current.reject(new Error('Đã dừng OCR. Chưa thêm văn bản vào nguồn.'));
}

export async function recognizeImage(image, onProgress) {
  if (current) throw new Error('OCR đang chạy. Hãy dừng hoặc chờ kết quả.');
  const token = { worker: null, cancelled: false };
  current = token;
  let timer;
  const stopped = new Promise((_, reject) => { token.reject = reject; timer = setTimeout(() => {
    token.cancelled = true; terminate(token); reject(new Error('OCR vượt 120 giây. Thử ảnh rõ hơn hoặc một vùng nhỏ hơn.'));
  }, 120000); });
  const job = async () => {
    const { createWorker } = await import('tesseract.js');
    if (token.cancelled) throw new Error('Đã dừng OCR.');
    const base = location.origin + '/static/ai-slides/dist/ocr/';
    const worker = await createWorker('vie', 1, {
      workerPath: base + 'worker.min.js', corePath: base + 'tesseract-core-lstm.js',
      langPath: base, workerBlobURL: false, gzip: true,
      logger: event => { if (!token.cancelled) onProgress?.(event.status, Math.round((event.progress || 0) * 100)); },
    });
    token.worker = worker;
    if (token.cancelled) { await terminate(token); throw new Error('Đã dừng OCR.'); }
    const { data } = await worker.recognize(image);
    if (!data.text.trim()) throw new Error('Chưa nhận được chữ. Thử ảnh rõ hơn hoặc nhập văn bản.');
    if (data.text.length > 40000) throw new Error('Kết quả vượt 40.000 ký tự. Chọn một vùng hoặc một trang nhỏ hơn.');
    return { text: data.text.trim(), confidence: Number.isFinite(data.confidence) ? data.confidence : null };
  };
  try { return await Promise.race([job(), stopped]); }
  finally { clearTimeout(timer); token.cancelled = true; await terminate(token); if (current === token) current = null; }
}

export async function imageCanvas(file) {
  if (!file || file.size > 10 * 1024 * 1024 || !/\.(png|jpe?g|webp)$/i.test(file.name)) throw new Error('Chọn ảnh PNG/JPEG/WebP nhỏ hơn 10 MB.');
  const head = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  const png = [137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => head[index] === byte);
  const jpeg = head[0] === 255 && head[1] === 216 && head[2] === 255;
  const webp = new TextDecoder().decode(head.slice(0, 4)) === 'RIFF' && new TextDecoder().decode(head.slice(8, 12)) === 'WEBP';
  if (!png && !jpeg && !webp) throw new Error('Nội dung ảnh không đúng PNG/JPEG/WebP. Không nhận SVG hoặc tệp đổi đuôi.');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image(); image.src = url; await image.decode();
    if (image.naturalWidth * image.naturalHeight > 16000000) throw new Error('Ảnh vượt 16 triệu pixel. Cắt vùng bài học trước khi OCR.');
    const scale = Math.min(1, 2400 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement('canvas'); canvas.width = Math.round(image.naturalWidth * scale); canvas.height = Math.round(image.naturalHeight * scale);
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas;
  } finally { URL.revokeObjectURL(url); }
}
