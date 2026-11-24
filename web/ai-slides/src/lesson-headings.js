// Suggestions only: never interpret printed table-of-contents page numbers as PDF pages.
export function lessonHeadings(text) {
  const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.some(line => /^mục\s+lục\s*$/iu.test(line))) return [];
  const headings = lines.filter(line => /^(?:bài|chủ đề|chương|lesson|unit|chapter)\s+(?:\d+[a-z]?|[IVX]+)(?:\s*[.:：)\-–—]\s*|\s+)\S/iu.test(line)
    && line.length <= 240 && !/\.{3,}|…|\s\d+\s*$/u.test(line));
  return headings.length > 6 ? [] : [...new Set(headings)];
}

export function lessonRanges(text) {
  const allowed = new Set(lessonHeadings(text));
  const found = [];
  let offset = 0;
  for (const line of text.split(/\n/)) {
    const title = line.trim();
    if (allowed.has(title)) found.push({ title, startOffset: offset + line.indexOf(title) });
    offset += line.length + 1;
  }
  return found.map((item, index) => ({ ...item, endOffset: found[index + 1]?.startOffset ?? text.length }));
}
