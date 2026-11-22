import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import pptxgen from 'pptxgenjs';
import {
  getShapeName, getShapeText, getSlideAnimations, getSlideNotes,
  getSlideShapes, getSlides, loadPresentation, validatePresentation,
} from '@office-kit/pptx';
import { addMotion } from '../src/pptx/motion.js';

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
const names = [];
for (let index = 0; index < 5; index += 1) {
  const slide = pptx.addSlide();
  slide.addText('Định luật Ôm — tiếng Việt', { x: 0.7, y: 0.5, w: 11, h: 0.8, fontFace: 'Arial', fontSize: 30 });
  const targets = ['pin', 'dien-tro', 'dong-dien'].map(name => `s${index}-${name}`);
  names.push(targets);
  targets.forEach((name, step) => slide.addText(['Nguồn điện', 'Điện trở', 'I = U / R'][step], {
    objectName: name, x: 1 + step * 4, y: 2, w: 3.5, h: 1, fontFace: 'Arial', fontSize: 25,
  }));
  slide.addText('Mở mô phỏng', { x: 1, y: 5.5, w: 4, h: 0.6, hyperlink: { url: 'https://example.org/sim' } });
  slide.addText('Xem đáp án', { x: 6, y: 5.5, w: 4, h: 0.6, hyperlink: { slide: 5 } });
  slide.addNotes('Ghi chú giáo viên. Kiểm tra điều kiện nhiệt độ không đổi.');
  if (index === 2) slide.addChart(pptx.ChartType.bar, [{ name: 'I', labels: ['3 V', '6 V'], values: [1, 2] }], { x: 1, y: 3.3, w: 5, h: 2 });
}
const baseBytes = new Uint8Array(await pptx.write({ outputType: 'arraybuffer' }));
const animatedBytes = await addMotion(baseBytes, names);
const before = await loadPresentation(baseBytes);
const after = await loadPresentation(animatedBytes);
const beforeSlides = getSlides(before);
const afterSlides = getSlides(after);
assert.equal(afterSlides.length, 5);
for (let index = 0; index < 5; index += 1) {
  const oldShapes = getSlideShapes(beforeSlides[index]);
  const newShapes = getSlideShapes(afterSlides[index]);
  assert.deepEqual(newShapes.map(getShapeName), oldShapes.map(getShapeName));
  assert.deepEqual(newShapes.map(getShapeText), oldShapes.map(getShapeText));
  assert.deepEqual(getSlideNotes(afterSlides[index]), getSlideNotes(beforeSlides[index]));
  assert.equal(getSlideAnimations(afterSlides[index]).length, 3);
}
await fs.mkdir('artifacts', { recursive: true });
await fs.writeFile('artifacts/base.pptx', baseBytes);
await fs.writeFile('artifacts/animated.pptx', animatedBytes);
const report = { slides: 5, animated_objects: 15, text_names_notes_preserved: true, validation: validatePresentation(after), desktop_slide_show: 'pending' };
await fs.writeFile('artifacts/motion-spike.json', JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
