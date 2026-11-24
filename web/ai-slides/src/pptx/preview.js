import { createScene, checkScene, SLIDE_HEIGHT, SLIDE_WIDTH } from './scene.js';
import { mapSvg } from './visuals.js';

export function renderScene(container, item, deck, index) {
  const scene = createScene(item, deck, index);
  container.replaceChildren();
  container.classList.add('scene-preview');
  container.style.background = '#' + scene.background;
  for (const object of scene.objects) {
    if (object.type === 'chart') {
      const figure = document.createElement('div');
      position(figure, object);
      figure.className = 'scene-chart';
      if (object.data.chart_type === 'line') {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', '0 0 600 290');
        svg.style.cssText = 'width:100%;height:100%';
        const min = Math.min(0, ...object.data.values);
        const max = Math.max(1, ...object.data.values);
        const points = object.data.values.map((value, i) => `${65 + i * 490 / (object.data.values.length - 1)},${235 - (value - min) / (max - min) * 180}`);
        const path = document.createElementNS(ns, 'polyline');
        path.setAttribute('points', points.join(' '));
        path.setAttribute('fill', 'none'); path.setAttribute('stroke', '#' + scene.theme.accent); path.setAttribute('stroke-width', '4');
        svg.append(path);
        object.data.labels.forEach((label, i) => {
          const text = document.createElementNS(ns, 'text');
          text.setAttribute('x', String(65 + i * 490 / (object.data.labels.length - 1)));
          text.setAttribute('y', '265'); text.setAttribute('text-anchor', 'middle');
          text.setAttribute('font-size', '16'); text.textContent = label;
          svg.append(text);
          const value = document.createElementNS(ns, 'text');
          const [x, y] = points[i].split(',');
          value.setAttribute('x', x); value.setAttribute('y', String(Number(y) - 10));
          value.setAttribute('text-anchor', 'middle'); value.setAttribute('font-size', '17');
          value.textContent = String(object.data.values[i]); svg.append(value);
        });
        const title = document.createElementNS(ns, 'text');
        title.setAttribute('x', '300'); title.setAttribute('y', '23'); title.setAttribute('text-anchor', 'middle');
        title.setAttribute('font-size', '18'); title.textContent = object.data.series_name; svg.append(title);
        figure.append(svg); container.append(figure); continue;
      }
      const maximum = Math.max(1, ...object.data.values.map(Math.abs));
      for (let i = 0; i < object.data.values.length; i += 1) {
        const row = document.createElement('div');
        row.className = 'scene-chart-row';
        const label = document.createElement('span');
        label.textContent = object.data.labels[i];
        const bar = document.createElement('span');
        bar.style.width = Math.abs(object.data.values[i]) / maximum * 65 + '%';
        bar.style.background = '#' + scene.theme.accent;
        const value = document.createElement('span');
        value.textContent = String(object.data.values[i]);
        row.append(label, bar, value);
        figure.append(row);
      }
      container.append(figure);
      continue;
    }
    if (object.type === 'map') {
      const image = document.createElement('img');
      image.alt = 'Đường bao đất liền Việt Nam khái quát, Natural Earth';
      image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(mapSvg());
      position(image, object);
      container.append(image);
      continue;
    }
    const node = document.createElement('div');
    position(node, object);
    node.dataset.objectId = object.id;
    if (object.type === 'text') {
      node.className = 'scene-text';
      node.textContent = object.text;
      node.style.fontSize = object.fontSize / 72 / SLIDE_WIDTH * 100 + 'cqw';
      node.style.color = '#' + object.color;
      node.style.fontWeight = object.bold ? '700' : '400';
      node.style.textAlign = object.align || 'left';
      node.style.justifyContent = ({ center: 'center', right: 'flex-end' })[object.align] || 'flex-start';
    } else if (object.type === 'line') {
      node.className = 'scene-line';
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 100 100');
      svg.setAttribute('preserveAspectRatio', 'none');
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', '0');
      line.setAttribute('y1', object.flipV ? '100' : '0');
      line.setAttribute('x2', object.w > 0 ? '100' : '0');
      line.setAttribute('y2', object.h > 0 ? (object.flipV ? '0' : '100') : '0');
      line.setAttribute('stroke', '#' + object.stroke);
      line.setAttribute('stroke-width', '2');
      line.setAttribute('vector-effect', 'non-scaling-stroke');
      svg.append(line); node.append(svg);
    } else {
      node.style.background = '#' + object.fill;
      if (object.stroke) node.style.border = '1px solid #' + object.stroke;
      if (object.type === 'ellipse') node.style.borderRadius = '50%';
    }
    container.append(node);
  }
  fitPreviewText(container);
}

function fitPreviewText(container) {
  const scale = container.getBoundingClientRect().width / (SLIDE_WIDTH * 72);
  if (!scale) return;
  for (const node of container.querySelectorAll('.scene-text')) {
    const minimum = Math.min(parseFloat(getComputedStyle(node).fontSize), 14 * scale);
    let size = parseFloat(getComputedStyle(node).fontSize);
    for (let attempt = 0; attempt < 30 && (node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1) && size > minimum; attempt += 1) {
      size = Math.max(minimum, size * 0.94); node.style.fontSize = size + 'px';
    }
  }
}

export async function preflightDeck(deck) {
  await document.fonts?.ready;
  const canvas = document.createElement('div');
  canvas.style.cssText = 'position:fixed;left:-15000px;top:0;width:1280px;height:720px;container-type:inline-size;pointer-events:none;font-family:Arial,sans-serif';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.append(canvas);
  try {
    const issues = [];
    for (const [index, item] of deck.manifest.slides.entries()) {
      if (checkScene(createScene(item, deck, index)).length) issues.push({ slide: index + 1, reason: 'đối tượng vượt khung' });
      renderScene(canvas, item, deck, index);
      if ([...canvas.querySelectorAll('.scene-text')].some(node => node.scrollHeight > node.clientHeight + 2 || node.scrollWidth > node.clientWidth + 2)) issues.push({ slide: index + 1, reason: 'chữ quá dài ở cỡ tối thiểu' });
    }
    return issues;
  } finally { canvas.remove(); }
}

function position(node, object) {
  Object.assign(node.style, {
    position: 'absolute', left: object.x / SLIDE_WIDTH * 100 + '%',
    top: object.y / SLIDE_HEIGHT * 100 + '%',
    width: object.w / SLIDE_WIDTH * 100 + '%',
    height: object.h / SLIDE_HEIGHT * 100 + '%',
  });
}
