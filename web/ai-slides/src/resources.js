import catalog from '../../../app/static/ai-slides/resources.json' with { type: 'json' };

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
