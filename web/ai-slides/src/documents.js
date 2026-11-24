import JSZip from 'jszip';
import { lessonRanges } from './lesson-headings.js';
import { THEMES } from './pptx/scene.js';

let pdfLibrary;
let pdfDocument;
let pdfTask;
let selectedFile;
let fingerprint;
let pageTextCache = new Map();

async function pdfjs() {
  if (!pdfLibrary) {
    pdfLibrary = await import('pdfjs-dist');
    const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url');
    pdfLibrary.GlobalWorkerOptions.workerSrc = worker.default;
  }
  return pdfLibrary;
}

export async function openDocument(file, { styleOnly = false } = {}) {
  pageTextCache = new Map();
  if (file.size > 100 * 1024 * 1024) throw new Error('Tệp lớn hơn 100 MB. Hãy chọn bản nhẹ hơn hoặc tách phần cần dùng.');
  selectedFile = file;
  const bytes = await file.arrayBuffer();
  fingerprint = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(byte => byte.toString(16).padStart(2, '0')).join('');
  if (file.name.toLowerCase().endsWith('.pdf')) {
    if (pdfTask) await pdfTask.destroy();
    pdfDocument = null;
    const library = await pdfjs();
    pdfTask = library.getDocument({ data: bytes, isEvalSupported: false, enableXfa: false });
    pdfDocument = await pdfTask.promise;
    if (pdfDocument.numPages > 400) throw new Error('Bản thử nghiệm hỗ trợ tối đa 400 trang. Hãy tách phần cần dùng.');
    const toc = [];
    async function walk(items, depth = 0) {
      if (depth > 8 || toc.length >= 200) return;
      for (const item of (items || []).slice(0, 150)) {
        if (toc.length >= 200) break;
        let dest = item.dest;
        if (typeof dest === 'string') dest = await pdfDocument.getDestination(dest);
        if (Array.isArray(dest)) {
          const page = typeof dest[0] === 'number' ? dest[0] + 1 : await pdfDocument.getPageIndex(dest[0]) + 1;
          toc.push({ title: item.title, page, depth });
        }
        await walk(item.items, depth + 1);
      }
    }
    await walk(await pdfDocument.getOutline());
    return { type: 'pdf', pages: pdfDocument.numPages, toc, name: file.name, fingerprint };
  }
  if (pdfTask) await pdfTask.destroy();
  pdfTask = null;
  pdfDocument = null;
  let text;
  if (file.name.toLowerCase().endsWith('.docx')) {
    if (file.size > 12 * 1024 * 1024) throw new Error('Tệp Word cần nhỏ hơn 12 MB.');
    const zip = await JSZip.loadAsync(bytes);
    const entries = Object.values(zip.files);
    const expanded = entries.reduce((sum, entry) => sum + (entry._data?.uncompressedSize || 0), 0);
    if (expanded > 30 * 1024 * 1024 || entries.length > 1000) throw new Error('Tệp Word giải nén quá lớn.');
    if (!zip.file('word/document.xml')) throw new Error('Tệp Word không hợp lệ.');
    const mammoth = await import('mammoth/mammoth.browser');
    text = (await mammoth.extractRawText({ arrayBuffer: bytes })).value;
  } else if (file.name.toLowerCase().endsWith('.pptx')) {
    if (file.size > 20 * 1024 * 1024) throw new Error('PowerPoint cần nhỏ hơn 20 MB.');
    const zip = await JSZip.loadAsync(bytes);
    const entries = Object.values(zip.files);
    if (entries.length > 1500 || entries.reduce((sum, entry) => sum + (entry._data?.uncompressedSize || 0), 0) > 40 * 1024 * 1024) throw new Error('PowerPoint giải nén quá lớn.');
    if (entries.some(entry => /vbaProject|activeX/i.test(entry.name))) throw new Error('Tệp có macro hoặc ActiveX. Hãy xuất bản không có thành phần này trước khi nhập.');
    const parse = xml => {
      if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error('XML PowerPoint có khai báo không được hỗ trợ.');
      const document = new DOMParser().parseFromString(xml, 'application/xml');
      if (document.querySelector('parsererror')) throw new Error('XML PowerPoint không hợp lệ.');
      return document;
    };
    if (!zip.file('ppt/presentation.xml') || !zip.file('ppt/_rels/presentation.xml.rels')) throw new Error('Thiếu cấu trúc trình chiếu PowerPoint.');
    const presentation = parse(await zip.file('ppt/presentation.xml').async('string'));
    const relationships = parse(await zip.file('ppt/_rels/presentation.xml.rels').async('string'));
    const links = new Map([...relationships.getElementsByTagName('Relationship')].map(node => [node.getAttribute('Id'), node]));
    const names = [...presentation.getElementsByTagNameNS('http://schemas.openxmlformats.org/presentationml/2006/main', 'sldId')].map(node => {
      const link = links.get(node.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id'));
      const target = link?.getAttribute('Target');
      if (!target || link.getAttribute('TargetMode') === 'External' || !/^(?:slides\/|\/ppt\/slides\/)slide\d+\.xml$/.test(target)) throw new Error('Tham chiếu slide không được hỗ trợ.');
      const name = target.startsWith('/') ? target.slice(1) : 'ppt/' + target;
      if (!zip.file(name)) throw new Error('Thiếu tệp slide được tham chiếu.');
      return name;
    });
    if (!names.length || names.length > 100) throw new Error('Chỉ nhập PowerPoint có 1–100 slide.');
    if (styleOnly) {
      const themeFile = zip.file('ppt/theme/theme1.xml');
      if (!themeFile) throw new Error('PPTX chưa có bảng màu theme đọc được. Bạn có thể chọn theme bằng tay.');
      const theme = parse(await themeFile.async('string'));
      const ns = 'http://schemas.openxmlformats.org/drawingml/2006/main';
      const colors = [...new Set([...theme.getElementsByTagNameNS(ns, 'clrScheme')].flatMap(node => [...node.getElementsByTagNameNS(ns, 'srgbClr')].map(color => color.getAttribute('val'))).filter(value => /^[0-9a-f]{6}$/i.test(value)))];
      if (!colors.length) throw new Error('Không tìm thấy mã màu RGB trong theme.');
      const rgb = hex => [0, 2, 4].map(start => parseInt(hex.slice(start, start + 2), 16));
      const accent = theme.getElementsByTagNameNS(ns, 'accent1')[0]?.getElementsByTagNameNS(ns, 'srgbClr')[0]?.getAttribute('val') || colors[0];
      const target = rgb(accent);
      const recommended = Object.entries(THEMES).sort((a, b) => {
        const distance = theme => rgb(theme.accent).reduce((sum, value, index) => sum + (value - target[index]) ** 2, 0);
        return distance(a[1]) - distance(b[1]);
      })[0][0];
      return { type: 'style', name: file.name, fingerprint, colors: colors.slice(0, 12), recommended };
    }
    const parts = [];
    for (const [index, name] of names.entries()) {
      const xml = await zip.file(name).async('string');
      const document = parse(xml);
      const lines = [...document.getElementsByTagNameNS('http://schemas.openxmlformats.org/drawingml/2006/main', 't')].map(node => node.textContent.trim()).filter(Boolean);
      if (lines.length) parts.push(`Slide gốc ${index + 1}\n${lines.join('\n')}`);
      if (parts.join('\n\n').length > 40000) throw new Error('Chữ trong PPTX vượt 40.000 ký tự. Hãy tách bài trước khi nhập.');
    }
    text = parts.join('\n\n');
  } else if (file.name.toLowerCase().endsWith('.txt')) {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } else {
    throw new Error('Chọn tệp PDF, DOCX, TXT hoặc PPTX chỉ có nội dung được hỗ trợ.');
  }
  if (!text.trim()) throw new Error('Tệp chưa có văn bản đọc được.');
  if (text.length > 40000) throw new Error('Văn bản vượt 40.000 ký tự. Hãy dán phần bài học cần dùng.');
  return { type: 'text', pages: 1, text, name: file.name, fingerprint,
    warning: file.name.toLowerCase().endsWith('.pptx') ? 'Chỉ nhập chữ từ slide theo thứ tự trình chiếu để soạn lại. Không giữ ảnh, biểu đồ, OLE, SmartArt, Notes, template hoặc hiệu ứng gốc. Không thực thi nội dung trong tệp.' : null };
}

export async function extractPages(first, last, onProgress, scope = null) {
  if (!pdfDocument || !Number.isInteger(first) || !Number.isInteger(last) || first < 1 || last > pdfDocument.numPages || last < first) throw new Error('Khoảng trang PDF chưa hợp lệ.');
  if (last - first > 49) throw new Error('Mỗi bài chọn tối đa 50 trang. Sách vẫn được giữ để chọn bài khác.');
  const sources = [];
  let length = 0;
  for (let number = first; number <= last; number += 1) {
    const page = await pdfDocument.getPage(number);
    const content = await page.getTextContent();
    const whole = content.items.map(item => item.str + (item.hasEOL ? '\n' : ' ')).join('').trim();
    const text = whole.slice(scope && number === first ? scope.startOffset || 0 : 0,
      scope && number === scope.endPage && Number.isInteger(scope.endOffset) ? scope.endOffset : undefined).trim();
    length += text.length;
    if (length > 40000) throw new Error('Phần đã chọn vượt 40.000 ký tự. Hãy chọn ít trang hơn.');
    if (text) sources.push({ id: `pdf-${fingerprint.slice(0, 12)}-${number}${scope ? '-' + scope.startOffset + '-' + (scope.endOffset ?? 'end') : ''}`, name: selectedFile.name, fingerprint, role: 'primary', page: number, text });
    page.cleanup();
    onProgress?.(number, last);
  }
  if (sources.reduce((sum, source) => sum + source.text.length, 0) < 80) throw new Error('Các trang này có thể là bản scan. Hãy chọn PDF có lớp chữ hoặc nhập văn bản để kiểm tra.');
  return sources;
}

const searchText = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLocaleLowerCase('vi').replace(/\s+/g, ' ').trim();

export async function pdfPageCanvas(number) {
  if (!pdfDocument || !Number.isInteger(number) || number < 1 || number > pdfDocument.numPages) throw new Error('Chọn một trang trong PDF đang mở để OCR.');
  const page = await pdfDocument.getPage(number);
  let viewport = page.getViewport({ scale: 2 });
  if (viewport.width * viewport.height > 6000000) viewport = page.getViewport({ scale: 2 * Math.sqrt(6000000 / (viewport.width * viewport.height)) });
  const canvas = document.createElement('canvas'); canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
  try { await page.render({ canvas, canvasContext: canvas.getContext('2d'), viewport }).promise; return canvas; }
  finally { page.cleanup(); }
}

async function cachedPageText(document, number) {
  if (!pageTextCache.has(number)) {
    const page = await document.getPage(number);
    const content = await page.getTextContent();
    const text = content.items.map(item => item.str + (item.hasEOL ? '\n' : ' ')).join('').trim();
    pageTextCache.set(number, text.slice(0, 40000)); page.cleanup();
  }
  return pageTextCache.get(number);
}

export async function discoverPdfLessons(onProgress) {
  if (!pdfDocument) throw new Error('Hãy chọn sách PDF trước.');
  const document = pdfDocument;
  const lessons = [];
  for (let page = 1; page <= document.numPages; page += 1) {
    const text = await cachedPageText(document, page);
    for (const item of lessonRanges(text)) lessons.push({ title: item.title, page, startOffset: item.startOffset, depth: 0 });
    if (page % 10 === 0 || page === document.numPages) onProgress?.(page, document.numPages);
    if (lessons.length >= 200) break;
  }
  return lessons.slice(0, 200).map((item, index) => ({ ...item, endPage: lessons[index + 1]?.page ?? document.numPages, endOffset: lessons[index + 1]?.startOffset ?? null }));
}

export async function searchPdf(query, onProgress) {
  if (!pdfDocument) throw new Error('Hãy chọn sách PDF trước khi tìm.');
  const needle = searchText(query);
  if (needle.length < 3) throw new Error('Nhập ít nhất 3 ký tự để tìm trong sách.');
  const document = pdfDocument;
  const results = [];
  for (let number = 1; number <= document.numPages; number += 1) {
    const text = await cachedPageText(document, number);
    const index = searchText(text).indexOf(needle);
    if (index >= 0) results.push({ page: number, snippet: text.slice(Math.max(0, index - 45), index + needle.length + 100) });
    if (number % 10 === 0 || number === document.numPages) onProgress?.(number, document.numPages);
    if (results.length >= 40) break;
  }
  return results;
}

function libraryDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('smart-tkb-studio-books', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('books', { keyPath: 'key' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function bookAction(owner, action, item) {
  const db = await libraryDb();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction('books', action === 'list' ? 'readonly' : 'readwrite');
      const store = transaction.objectStore('books');
      const key = `${owner}:${item?.fingerprint}`;
      let result;
      if (action === 'save') result = store.put({ key, owner, fingerprint, name: selectedFile.name, file: selectedFile,
        toc: item?.toc || [], scope: item?.scope || null, first: item?.first || 1, last: item?.last || 1 });
      if (action === 'update') {
        result = store.get(key);
        result.onsuccess = () => { if (result.result?.owner === owner) store.put({ ...result.result, toc: item.toc, scope: item.scope, first: item.first, last: item.last }); };
      }
      if (action === 'delete') result = store.delete(key);
      if (action === 'list') result = store.getAll();
      transaction.oncomplete = () => resolve(action === 'list' ? result.result.filter(book => book.owner === owner) : true);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
