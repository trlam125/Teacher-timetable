import JSZip from 'jszip';
import { buildDeck } from './pptx/export.js';
import { resourceInfo, resourceHref, manualResource } from './resources.js';

const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

export async function buildOfflinePackage(deck, options) {
  const read = async path => {
    const response = await fetch(path, { credentials: 'same-origin', redirect: 'error' });
    if (!response.ok) throw new Error('Chưa tải đủ tài nguyên để đóng gói offline. Thử lại khi có mạng.');
    return response.text();
  };
  const [script, map, notices] = await Promise.all([
    read('/static/ai-slides/simulations.js'), read('/static/ai-slides/vietnam.geojson'),
    read('/static/ai-slides/dist/THIRD_PARTY_NOTICES.txt'),
  ]);
  const zip = new JSZip();
  zip.file('lesson.pptx', await buildDeck(deck, options));
  zip.file('lesson.json', JSON.stringify(deck, null, 2));
  zip.file('THIRD_PARTY_NOTICES.txt', notices);
  zip.file('assets/simulations.js', script);
  for (const slug of ['ohm', 'pendulum', 'vietnam-map']) {
    let html = await read('/ai-studio/simulations/' + slug);
    html = html.replaceAll('/static/ai-slides/simulations.js?v=1', '../assets/simulations.js');
    if (slug === 'vietnam-map') html = html.replace('</main>', `<script id="offline-map-data" type="application/json">${map.replaceAll('<', '\\u003c')}</script></main>`);
    zip.file('simulations/' + slug + '.html', html);
  }
  const links = [];
  const notes = deck.manifest.slides.map((slide, index) => {
    const resource = resourceInfo(slide.resource_id);
    const own = slide.manual_resource ? manualResource(slide.manual_resource.title, slide.manual_resource.url) : null;
    const url = own?.url || resourceHref(slide.resource_id, options.origin);
    if (url) links.push(`<li>${escape(slide.title)}: <a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(own?.title || resource.label)}</a> — cần Internet${own ? ', chưa xác minh nội dung' : ''}</li>`);
    const sources = slide.source_ids.map(id => deck.profile.sources.find(source => source.id === id)).filter(Boolean);
    return `${index + 1}. ${slide.title}\n${slide.speaker_notes}\nGiáo viên: ${slide.teacher_action}\nHọc sinh: ${slide.student_action}\nNguồn: ${sources.map(source => source.name + (source.page ? ' · trang PDF ' + source.page : '')).join('; ') || 'Chưa có nguồn'}${url ? '\nHọc liệu: ' + url + '\n' + (own ? 'Do giáo viên cung cấp; chưa xác minh nội dung/quyền sử dụng.' : resource.credit) : ''}`;
  }).join('\n\n');
  zip.file('notes.txt', notes);
  zip.file('README.txt', 'Giải nén toàn bộ gói rồi mở index.html hoặc lesson.pptx.\nHai mô phỏng Vật lí và bản đồ khái quát chạy từ các trang HTML trong gói.\nCác nút trong PowerPoint vẫn mở website; mở mô phỏng offline từ index.html nếu không có mạng.\nPhET, NASA và link ngoài không được nhúng: cần Internet, tuân thủ quyền sử dụng của nguồn.\nGói có JSON và các đoạn nguồn đã lưu; chỉ chia sẻ khi có quyền.\nĐường bao Natural Earth public domain; bản đồ không thể hiện đầy đủ biển đảo/địa giới.');
  zip.file('index.html', `<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(deck.title)}</title><style>body{font:18px/1.65 Arial,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#172d4a;background:#f3f6fc}a{color:#245bb5}li{margin:12px 0}</style><h1>${escape(deck.title)}</h1><p>Giải nén cả gói trước khi dùng. Giáo viên cần xem lại nội dung trước khi dạy.</p><ul><li><a href="lesson.pptx">Mở PowerPoint</a></li><li><a href="notes.txt">Ghi chú và nguồn</a></li><li><a href="simulations/ohm.html">Mô phỏng định luật Ôm offline</a></li><li><a href="simulations/pendulum.html">Mô phỏng con lắc offline</a></li><li><a href="simulations/vietnam-map.html">Bản đồ khái quát offline</a></li></ul><p>Các nút trong PowerPoint vẫn mở website. Khi không có mạng, dùng các trang mô phỏng ở trên. PhET/video/web bên ngoài cần Internet; không được sao chép vào gói.</p>${links.length ? '<h2>Liên kết cần Internet</h2><ul>' + links.join('') + '</ul>' : ''}<p>Gói chứa các đoạn nguồn trong lesson.json. Chỉ chia sẻ khi có quyền sử dụng. Dữ liệu bản đồ Natural Earth public domain, phạm vi biển đảo/địa giới chưa đầy đủ.</p></html>`);
  return zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' });
}
