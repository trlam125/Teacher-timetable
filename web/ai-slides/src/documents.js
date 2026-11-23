import JSZip from 'jszip';
import { lessonHeadings } from './lesson-headings.js';

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

export async function openDocument(file) {
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
      if (depth > 8) return;
      for (const item of (items || []).slice(0, 150)) {
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
  } else if (file.name.toLowerCase().endsWith('.txt')) {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } else {
    throw new Error('Chọn tệp PDF, DOCX hoặc TXT.');
  }
  if (!text.trim()) throw new Error('Tệp chưa có văn bản đọc được.');
  if (text.length > 40000) throw new Error('Văn bản vượt 40.000 ký tự. Hãy dán phần bài học cần dùng.');
  return { type: 'text', pages: 1, text, name: file.name, fingerprint };
}

export async function extractPages(first, last, onProgress) {
  if (!pdfDocument || !Number.isInteger(first) || !Number.isInteger(last) || first < 1 || last > pdfDocument.numPages || last < first) throw new Error('Khoảng trang PDF chưa hợp lệ.');
  if (last - first > 49) throw new Error('Mỗi bài chọn tối đa 50 trang. Sách vẫn được giữ để chọn bài khác.');
  const sources = [];
  let length = 0;
  for (let number = first; number <= last; number += 1) {
    const page = await pdfDocument.getPage(number);
    const content = await page.getTextContent();
    const text = content.items.map(item => item.str + (item.hasEOL ? '\n' : ' ')).join('').trim();
    length += text.length;
    if (length > 40000) throw new Error('Phần đã chọn vượt 40.000 ký tự. Hãy chọn ít trang hơn.');
    if (text) sources.push({ id: `pdf-${fingerprint.slice(0, 12)}-${number}`, name: selectedFile.name, fingerprint, role: 'primary', page: number, text });
    page.cleanup();
    onProgress?.(number, last);
  }
  if (sources.reduce((sum, source) => sum + source.text.length, 0) < 80) throw new Error('Các trang này có thể là bản scan. Hãy chọn PDF có lớp chữ hoặc nhập văn bản để kiểm tra.');
  return sources;
}

const searchText = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLocaleLowerCase('vi').replace(/\s+/g, ' ').trim();

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
    for (const title of lessonHeadings(text)) lessons.push({ title, page, depth: 0 });
    if (page % 10 === 0 || page === document.numPages) onProgress?.(page, document.numPages);
    if (lessons.length >= 200) break;
  }
  return lessons.slice(0, 200);
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
      if (action === 'save') result = store.put({ key, owner, fingerprint, name: selectedFile.name, file: selectedFile });
      if (action === 'delete') result = store.delete(key);
      if (action === 'list') result = store.getAll();
      transaction.oncomplete = () => resolve(action === 'list' ? result.result.filter(book => book.owner === owner) : true);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
