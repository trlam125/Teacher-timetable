import pptxgen from 'pptxgenjs';
import { checkScene, createScene } from './scene.js';
import { mapSvg } from './visuals.js';
import { resourceHref, resourceInfo } from '../resources.js';

export function resourceUrl(id, origin) {
  return resourceHref(id, origin);
}

function drawScene(pptx, slide, scene, quizTargets) {
  slide.background = { color: scene.background };
  for (const object of scene.objects) {
    const box = { x: object.x, y: object.y, w: object.w, h: object.h, objectName: object.id };
    if (object.type === 'text') {
      slide.addText(object.text, {
        ...box, fontFace: 'Arial', fontSize: object.fontSize, color: object.color,
        bold: object.bold || false, align: object.align || 'left', margin: 0,
        valign: 'mid', breakLine: false, fit: 'shrink',
        hyperlink: object.quizChoice === undefined ? undefined : { slide: quizTargets[object.quizChoice] },
      });
    } else if (object.type === 'map') {
      slide.addImage({ ...box, data: 'data:image/svg+xml;base64,' + btoa(mapSvg()) });
    } else if (object.type === 'chart') {
      slide.addChart(object.data.chart_type === 'line' ? pptx.ChartType.line : pptx.ChartType.bar, [{
        name: object.data.series_name, labels: object.data.labels, values: object.data.values,
      }], {
        ...box, catAxisLabelFontFace: 'Arial', valAxisLabelFontFace: 'Arial',
        catAxisLabelFontSize: 14, valAxisLabelFontSize: 14, showLegend: false,
        showTitle: true, title: object.data.series_name, titleFontSize: 17,
        chartColors: [scene.theme.accent], showValue: true, showCatName: false,
        showBorder: false, valGridLine: { color: 'D9E4EA', width: 0.5 },
      });
    } else {
      slide.addShape(pptx.ShapeType[object.type], {
        ...box, flipV: object.flipV,
        fill: object.fill ? { color: object.fill } : { color: 'FFFFFF', transparency: 100 },
        line: object.stroke ? { color: object.stroke, width: object.width || 1.5 } : { color: 'FFFFFF', transparency: 100 },
      });
    }
  }
}

export async function buildDeck(deck, { nativeMotion = false, origin = '' } = {}) {
  const pptx = new pptxgen();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'Smart TKB AI Studio';
  pptx.subject = deck.profile.subject;
  pptx.title = deck.title;
  pptx.lang = 'vi-VN';
  const targets = [];
  const slides = deck.manifest.slides;
  const feedbackSlides = [];
  slides.forEach((item, index) => {
    const slide = pptx.addSlide();
    const scene = createScene(item, deck, index);
    if (checkScene(scene).length) throw new Error(`Bố cục slide ${index + 1} vượt khung. Hãy kiểm tra nội dung trước khi tải.`);
    const quizTargets = (item.kind === 'quiz' ? item.options || [] : []).map((option, choice) => {
      const number = slides.length + feedbackSlides.length + 1;
      feedbackSlides.push({ item, original: index + 1, correct: choice === item.correct_option });
      return number;
    });
    drawScene(pptx, slide, scene, quizTargets);
    targets.push(scene.objects.filter(object => object.animate).map(object => object.id));
    const references = (item.source_ids || []).map(id => deck.profile.sources.find(source => source.id === id)).filter(Boolean);
    const sourceText = references.map(source => source.name + (source.page ? ` (trang PDF ${source.page})` : '')).join(' · ');
    slide.addText(sourceText || 'Giáo viên rà soát nội dung trước khi dạy', {
      x: 0.75, y: 7.12, w: 10.9, h: 0.21, fontFace: 'Arial', fontSize: 9,
      color: item.kind === 'cover' ? 'B9DAD9' : '5D737E', margin: 0, fit: 'shrink',
    });
    const url = resourceUrl(item.resource_id, origin);
    const resource = resourceInfo(item.resource_id);
    if (url && /^https?:\/\//.test(url)) slide.addText(
      resource.group === 'PhET' ? `Mở ${resource.label} (Internet)` : item.resource_id === 'water-cycle-video' ? 'Mở video NASA' : 'Mở học liệu tương tác',
      { x: 0.9, y: 6.38, w: 8.4, h: 0.35, fontFace: 'Arial', fontSize: 16,
        color: scene.theme.accent, hyperlink: { url }, margin: 0 },
    );
    slide.addNotes([
      item.speaker_notes, `Hoạt động giáo viên\n${item.teacher_action || ''}`,
      `Hoạt động học sinh\n${item.student_action || ''}`,
      `Thời lượng ${item.duration_seconds} giây`,
      `Nguồn\n${sourceText || 'Không có tài liệu tham chiếu'}`,
      resource && url ? `Học liệu: ${resource.label}\nNguồn: ${resource.credit}\n${url}\n${resource.internet ? 'Cần Internet; không nhúng trong tệp.' : 'Cần truy cập được website Smart TKB.'}` : '',
      item.kind === 'map' ? 'Đường bao khái quát Natural Earth 1:110m, public domain. Phạm vi biển đảo chưa được thể hiện đầy đủ.' : '',
      item.chart_data?.data_origin === 'example' ? 'Biểu đồ dùng số liệu ví dụ minh họa.' : '',
    ].filter(Boolean).join('\n\n'));
  });
  for (const feedback of feedbackSlides) {
    const slide = pptx.addSlide();
    const theme = createScene(feedback.item, deck, 0).theme;
    slide.background = { color: theme.paper };
    targets.push([]);
    slide.addText(feedback.correct ? 'Chính xác' : 'Hãy thử lại', {
      x: 1, y: 1.3, w: 11, h: 1, fontFace: 'Arial', fontSize: 38, bold: true, color: theme.accent,
    });
    slide.addText(feedback.correct ? feedback.item.explanation : 'Đối chiếu dữ kiện và quay lại câu hỏi để chọn phương án khác.', {
      x: 1, y: 2.8, w: 11, h: 1.8, fontFace: 'Arial', fontSize: 24, color: theme.ink,
    });
    slide.addText('Quay lại câu hỏi', { x: 1, y: 5.6, w: 5, h: 0.6, fontSize: 21, hyperlink: { slide: feedback.original } });
    slide.addText('Tiếp tục bài học', { x: 7, y: 5.6, w: 5, h: 0.6, fontSize: 21, hyperlink: { slide: Math.min(feedback.original + 1, slides.length) } });
  }
  const bytes = new Uint8Array(await pptx.write({ outputType: 'arraybuffer', compression: true }));
  if (!nativeMotion || deck.profile.motion === 'none') return bytes;
  const { addMotion } = await import('./motion.js');
  return addMotion(bytes, deck.profile.motion === 'minimal' ? targets.map(names => names.slice(0, 1)) : targets.map(names => names.slice(0, 4)));
}

export function download(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename.replace(/[<>:"/\\|?*]/g, '-');
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
