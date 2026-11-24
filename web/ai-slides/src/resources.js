import catalog from '../../../app/static/ai-slides/resources.json' with { type: 'json' };
import policy from '../../../app/static/ai-slides/link-policy.json' with { type: 'json' };

export function manualResource(title, value) {
  if (!value) return null;
  if (!title.trim() || title.trim().length > 120 || value.length > 1000 || /[\x00-\x20\x7f\\]/.test(value)) throw new Error('Nhập tên và liên kết học liệu HTTPS hợp lệ.');
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.port) throw new Error('Học liệu cần HTTPS, không có tài khoản hoặc cổng riêng trong URL.');
  let href, kind;
  if (policy.youtube_hosts.includes(url.hostname)) {
    const id = url.hostname === 'youtu.be' ? url.pathname.slice(1) : url.pathname === '/watch' ? url.searchParams.get('v') : /^\/(shorts|embed)\//.test(url.pathname) ? url.pathname.split('/').at(-1) : '';
    if (!/^[A-Za-z0-9_-]{11}$/.test(id || '')) throw new Error('Liên kết YouTube cần đúng mã video.');
    href = 'https://www.youtube.com/watch?v=' + id; kind = 'video';
  } else if (policy.vimeo_hosts.includes(url.hostname) && /^\/[0-9]{1,12}$/.test(url.pathname)) {
    href = 'https://vimeo.com' + url.pathname; kind = 'video';
  } else if (policy.web_hosts.includes(url.hostname)) {
    href = 'https://' + url.hostname + url.pathname; kind = 'web';
  } else throw new Error('Tên miền chưa được hỗ trợ. Hãy chọn YouTube, Vimeo, PhET, NASA, Wikipedia tiếng Việt, Khan Academy hoặc Bộ GDĐT.');
  return { title: title.trim(), url: href, kind, verification: 'user_provided' };
}

export const resources = catalog;
const byId = new Map(catalog.map(item => [item.id, item]));
export function resourceInfo(id) { return byId.get(id) || null; }
export function resourceHref(id, origin) {
  const item = resourceInfo(id);
  if (!item) return null;
  if (item.url) return item.url;
  try {
    const base = new URL(origin);
    if (!['https:', 'http:'].includes(base.protocol) || base.username || base.password) return null;
    return new URL(item.path, base.origin).href;
  } catch { return null; }
}
