export const SLIDE_WIDTH = 13.333333;
export const SLIDE_HEIGHT = 7.5;
export const THEMES = {
  science: { ink: '17394B', accent: '007F86', tint: 'E8F5F4', paper: 'F7FAFC', secondary: 'F1AD57' },
  primary: { ink: '3D3159', accent: '7951AE', tint: 'F0EAF8', paper: 'FCFAFF', secondary: 'E7A33B' },
  geography: { ink: '224B3F', accent: '327957', tint: 'EAF2E9', paper: 'F8FBF7', secondary: 'C98D45' },
  history: { ink: '483A37', accent: '925D49', tint: 'F3EBE5', paper: 'FCFAF8', secondary: 'BD8B3E' },
};

export function createScene(item, deck, index) {
  const theme = THEMES[deck.profile.theme] || THEMES.science;
  const scene = { background: theme.paper, objects: [], theme, kind: item.kind };
  let sequence = 0;
  function add(type, box, props = {}) {
    const object = { id: `${item.id}-object-${sequence++}`, type, ...box, ...props };
    scene.objects.push(object);
    return object;
  }
  function box(x, y, w, h, fill, props = {}) {
    return add('rect', { x, y, w, h }, { fill, ...props });
  }
  function text(value, x, y, w, h, props = {}) {
    if (!value) return;
    return add('text', { x, y, w, h }, {
      text: String(value), fontSize: 22, color: theme.ink, ...props,
    });
  }
  function line(x1, y1, x2, y2, props = {}) {
    return add('line', { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) },
      { stroke: theme.accent, flipV: y2 < y1, ...props });
  }
  function circle(x, y, size, fill, props = {}) {
    return add('ellipse', { x, y, w: size, h: size }, { fill, ...props });
  }
  function bullet(value, position, x, y, w, h = 0.72, fontSize = 22) {
    return text(value, x, y, w, h, {
      id: `${item.id}-bullet-${position}`, animate: true, fontSize,
    });
  }
  function list(x, y, w, spacing = 0.74, fontSize = 21) {
    (item.bullets || []).forEach((value, position) => {
      circle(x, y + position * spacing + 0.19, 0.07, theme.accent);
      bullet(value, position, x + 0.25, y + position * spacing, w - 0.25, spacing - 0.12, fontSize);
    });
  }
  function circuit(x, y, w = 4.3) {
    const circuitColor = item.kind === 'cover' ? 'FFFFFF' : theme.accent;
    const wire = (x1, y1, x2, y2, props = {}) => line(x1, y1, x2, y2, { stroke: circuitColor, ...props });
    const right = x + w;
    const bottom = y + 2.25;
    wire(x, y, right, y);
    wire(right, y, right, bottom);
    wire(x, bottom, right, bottom);
    wire(x, y, x, y + 0.8);
    wire(x, y + 1.4, x, bottom);
    wire(x - 0.25, y + 0.8, x + 0.25, y + 0.8, { width: 3 });
    wire(x - 0.13, y + 1.05, x + 0.13, y + 1.05, { width: 3 });
    wire(x, y + 1.05, x, y + 1.4);
    box(x + w * 0.4, y - 0.16, w * 0.3, 0.32, 'FFFFFF', { stroke: circuitColor, width: 2 });
    text('R', x + w * 0.5, y - 0.7, 0.6, 0.45, { fontSize: 23, bold: true, color: circuitColor });
    text('U', x - 0.8, y + 0.65, 0.5, 0.45, { fontSize: 23, color: circuitColor });
    text('I', right + 0.18, y + 0.9, 0.5, 0.45, { fontSize: 23, color: circuitColor });
    text('I = U / R', x + 0.35, y + 0.75, w - 0.7, 0.7, { fontSize: 31, bold: true, align: 'center', color: item.kind === 'cover' ? 'FFFFFF' : theme.ink });
  }
  function pendulum(x, y) {
    line(x - 1.5, y, x + 1.5, y, { width: 4 });
    line(x, y, x + 0.9, y + 2.35);
    circle(x + 0.66, y + 2.1, 0.5, theme.accent);
    text('L', x + 0.8, y + 0.9, 0.6, 0.5, { color: theme.accent, fontSize: 25 });
    text('T ≈ 2π√(L/g)', x - 1.9, y + 2.75, 4, 0.6, { fontSize: 27, bold: true, align: 'center' });
  }
  const bullets = item.bullets || [];
  if (item.kind === 'cover') {
    scene.background = theme.ink;
    box(8.6, 0, 4.75, 7.5, theme.accent);
    text(deck.profile.subject, 0.8, 0.65, 6.7, 0.45, { color: 'B9DAD9', fontSize: 17 });
    text(item.title, 0.8, 1.7, 7.2, 2.45, { color: 'FFFFFF', fontSize: 39, bold: true });
    text(bullets.slice(0, 2).join('\n'), 0.85, 4.75, 6.7, 1.3, { color: 'E6F0F4', fontSize: 22, animate: true });
    text(`${deck.profile.grade} · ${deck.profile.duration_minutes || 45} phút`, 0.85, 6.55, 6.7, 0.4, { color: 'B9DAD9', fontSize: 16 });
    if (/ôm|điện/i.test(deck.title)) circuit(9.05, 2.5, 3.2);
    else {
      circle(9.5, 1.5, 2.2, theme.secondary);
      circle(9.35, 4.4, 0.45, 'FFFFFF');
      box(10.2, 4.4, 2, 0.45, 'FFFFFF');
      box(9.35, 5.35, 2.85, 0.16, 'B9DAD9');
    }
    return scene;
  }
  text(deck.profile.subject, 0.75, 0.35, 9.5, 0.3, { fontSize: 13, color: theme.accent });
  box(0.75, 0.94, 0.48, 0.065, theme.accent);
  text(item.title, 0.75, 1.25, 11.85, 0.95, { fontSize: 30, bold: true });
  switch (item.kind) {
    case 'objectives':
      bullets.forEach((value, position) => {
        box(0.8, 2.55 + position * 0.72, 0.26, 0.26, theme.tint, { stroke: theme.accent });
        bullet(value, position, 1.35, 2.4 + position * 0.72, 10.8, 0.68);
      });
      break;
    case 'hook':
      box(0.75, 2.55, 11.8, 2.35, theme.ink);
      text(item.question || bullets[0], 1.2, 2.85, 10.9, 1.65, { fontSize: 31, bold: true, color: 'FFFFFF', animate: true });
      text(bullets.slice(1, 3).join('\n'), 1, 5.2, 11.2, 1, { fontSize: 21 });
      break;
    case 'section':
      box(0, 0, 0.45, 7.5, theme.accent);
      text(item.title, 1, 2.6, 10.8, 1.8, { fontSize: 39, bold: true });
      text(bullets.slice(0, 2).join('\n'), 1.05, 4.65, 10.6, 1.3, { fontSize: 23, animate: true });
      scene.objects = scene.objects.filter(object => object.y !== 1.25);
      break;
    case 'concept': {
      const illustrated = /ôm|điện/i.test(deck.title) || item.resource_id === 'ohm' || item.resource_id === 'pendulum';
      if (illustrated) {
        list(0.85, 2.55, 6.3, 0.72, 21);
        box(7.7, 2.45, 4.7, 3.75, theme.tint);
        if (item.resource_id === 'pendulum') pendulum(10, 2.85);
        else circuit(8.2, 3.25, 3.5);
      } else {
        bullets.forEach((value, position) => {
          const y = 2.45 + position * 0.8;
          box(0.8, y, 0.08, 0.62, theme.accent);
          bullet(value, position, 1.15, y, 10.8, 0.72);
        });
      }
      break;
    }
    case 'process':
      bullets.forEach((value, position) => {
        const y = 2.45 + position * 0.77;
        if (position < bullets.length - 1) line(1.12, y + 0.35, 1.12, y + 0.95, { stroke: 'BDCFD3' });
        circle(0.85, y, 0.55, theme.accent);
        text(String(position + 1), 0.85, y + 0.04, 0.55, 0.4, { color: 'FFFFFF', fontSize: 18, align: 'center' });
        bullet(value, position, 1.75, y - 0.02, 10.2, 0.65);
      });
      break;
    case 'compare':
      box(0.8, 2.45, 5.65, 3.8, 'FFFFFF');
      box(6.85, 2.45, 5.65, 3.8, theme.tint);
      bullets.forEach((value, position) => bullet(value, position, position % 2 ? 7.2 : 1.15, 2.8 + Math.floor(position / 2) * 1.1, 4.95, 0.95, 21));
      break;
    case 'map':
      box(0.8, 2.4, 6.9, 3.8, 'E7F0F5');
      add('map', { x: 1.9, y: 2.5, w: 4.4, h: 3.55 });
      bullets.slice(0, 4).forEach((value, position) => bullet(value, position, 8.15, 2.45 + position * 0.9, 4.1, 0.82, 20));
      break;
    case 'experiment':
      list(0.85, 2.45, 6.15, 0.72, 21);
      box(7.7, 2.45, 4.7, 3.75, theme.tint);
      if (item.resource_id === 'pendulum') pendulum(10, 2.75);
      else if (/ôm|điện/i.test(deck.title) || item.resource_id === 'ohm') circuit(8.2, 3.3, 3.5);
      else text('Dự đoán\nQuan sát\nGiải thích', 8.1, 2.95, 3.8, 2.5, { fontSize: 27, bold: true, color: theme.accent, align: 'center' });
      break;
    case 'example':
      bullets.forEach((value, position) => {
        const y = 2.45 + position * 0.76;
        box(0.8, y, 11.65, 0.67, position % 2 ? 'FFFFFF' : theme.tint);
        bullet(value, position, 1.1, y + 0.02, 11, 0.62, 22);
      });
      break;
    case 'chart':
      if (item.chart_data) {
        add('chart', { x: 0.9, y: 2.45, w: 7.3, h: 3.55 }, { data: item.chart_data });
        bullets.slice(0, 3).forEach((value, position) => bullet(value, position, 8.7, 2.65 + position * 1.05, 3.6, 0.95, 20));
        if (item.chart_data.data_origin === 'example') text('Số liệu ví dụ minh họa', 0.9, 6.08, 7.3, 0.28, { fontSize: 11, color: theme.accent });
      } else list(1, 2.5, 11, 0.85);
      break;
    case 'quiz':
      text(item.question || item.title, 0.9, 2.35, 11.4, 1.1, { fontSize: 26, bold: true });
      (item.options || []).forEach((option, choice) => {
        const x = choice % 2 ? 6.95 : 0.9;
        const y = 3.8 + Math.floor(choice / 2) * 1.08;
        box(x, y, 5.4, 0.9, 'FFFFFF', { stroke: 'D6E1E6' });
        text(String.fromCharCode(65 + choice), x + 0.18, y + 0.2, 0.45, 0.4, { fontSize: 20, bold: true, color: theme.accent });
        text(option, x + 0.8, y + 0.1, 4.3, 0.7, { fontSize: 20, quizChoice: choice });
      });
      break;
    case 'video':
      box(0.8, 2.45, 6.95, 3.65, theme.ink);
      circle(3.3, 3.45, 1.15, theme.accent);
      text('▶', 3.52, 3.69, 0.75, 0.55, { color: 'FFFFFF', fontSize: 29, align: 'center' });
      text('Xem và thảo luận', 1.2, 5.25, 6.15, 0.55, { color: 'FFFFFF', fontSize: 23, align: 'center' });
      bullets.slice(0, 3).forEach((value, position) => bullet(value, position, 8.25, 2.6 + position * 1.05, 4.05, 0.95, 20));
      break;
    case 'summary':
      bullets.forEach((value, position) => {
        const y = 2.5 + position * 0.76;
        text('✓', 0.85, y, 0.5, 0.6, { fontSize: 25, bold: true, color: theme.accent });
        bullet(value, position, 1.55, y, 10.65, 0.65);
      });
      break;
    case 'sources': {
      const refs = deck.profile.sources || [];
      const names = [...new Set(refs.map(source => source.name))];
      (names.length ? names : ['Chưa có tài liệu tham chiếu được cung cấp.', 'Nội dung AI tạo cần được giáo viên rà soát trước khi dạy.']).slice(0, 5).forEach((name, position) => bullet(name, position, 1, 2.5 + position * 0.72, 11, 0.65, 20));
      break;
    }
    default:
      list(1, 2.5, 11);
  }
  box(0.75, 6.94, 11.85, 0.012, 'D5E1E6');
  text(String(index + 1).padStart(2, '0'), 12.1, 7.12, 0.45, 0.22, { fontSize: 10, color: '5D737E', align: 'right' });
  return scene;
}

export function checkScene(scene) {
  return scene.objects.filter(object =>
    object.x < -0.01 || object.y < -0.01 ||
    object.x + object.w > SLIDE_WIDTH + 0.02 ||
    object.y + object.h > SLIDE_HEIGHT + 0.02
  ).map(object => object.id);
}
