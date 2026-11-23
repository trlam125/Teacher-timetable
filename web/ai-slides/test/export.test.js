import test from 'node:test';
import assert from 'node:assert/strict';
import JSZip from 'jszip';
import { buildDeck, resourceUrl } from '../src/pptx/export.js';
import { getSlides, getSlideAnimations, loadPresentation, validatePresentation } from '@office-kit/pptx';
import { createScene, checkScene } from '../src/pptx/scene.js';

function fixture(motion = 'gentle') {
  return {
    title: 'Bài kiểm thử tiếng Việt', profile: { theme: 'science', motion, subject: 'Vật lí', grade: 'Lớp 9', sources: [
      { id: 'source-01', name: 'Nguồn kiểm thử', page: 7 },
    ] },
    manifest: { slides: [
      { id: 's001', kind: 'concept', title: 'Định luật Ôm', bullets: ['I = U/R', 'R > 0'], source_ids: ['source-01'], speaker_notes: 'Nhiệt độ không đổi', teacher_action: 'Đặt câu hỏi', student_action: 'Trả lời', duration_seconds: 180 },
      { id: 's002', kind: 'quiz', title: 'Luyện tập', question: '6 / 3 bằng bao nhiêu?', options: ['2 A', '18 A'], correct_option: 0, explanation: 'I = 2 A', bullets: [], source_ids: [], resource_id: 'ohm' },
    ] },
  };
}

test('browser export retains editable text, Vietnamese notes and quiz targets', async () => {
  const bytes = await buildDeck(fixture(), { origin: 'https://example.test' });
  const zip = await JSZip.loadAsync(bytes);
  const slides = Object.keys(zip.files).filter(path => /^ppt\/slides\/slide\d+\.xml$/.test(path));
  assert.equal(slides.length, 4);
  const first = await zip.file('ppt/slides/slide1.xml').async('string');
  assert.ok(first.includes('Định luật Ôm'));
  assert.ok(first.includes('s001-bullet-0'));
  assert.ok(first.includes('trang PDF 7'));
  assert.ok(!first.includes('<p:timing'));
  const notes = await zip.file('ppt/notesSlides/notesSlide1.xml').async('string');
  assert.ok(notes.includes('Nhiệt độ không đổi'));
  const quizRels = await zip.file('ppt/slides/_rels/slide2.xml.rels').async('string');
  assert.ok(quizRels.includes('slide3.xml'));
  assert.ok(quizRels.includes('slide4.xml'));
  assert.ok(quizRels.includes('https://example.test/ai-studio/simulations/ohm'));
});

test('strict excerpts do not acquire an automatic physics formula from the lesson title', () => {
  const deck = fixture();
  deck.title = 'Định luật Ôm'; deck.profile.grounding = 'strict';
  for (const kind of ['cover', 'concept']) {
    const item = { ...deck.manifest.slides[0], kind, bullets: ['Nguồn chỉ mô tả cách ghi số đo.'], resource_id: null };
    assert.equal(createScene(item, deck, 0).objects.some(object => object.text === 'I = U / R'), false);
    deck.profile.grounding = 'balanced';
    assert.equal(createScene(item, deck, 0).objects.some(object => object.text === 'I = U / R'), true);
    deck.profile.grounding = 'strict';
  }
});

test('native motion changes timing while preserving package relationships', async () => {
  const staticBytes = await buildDeck(fixture(), { origin: 'https://example.test' });
  const animatedBytes = await buildDeck(fixture(), { origin: 'https://example.test', nativeMotion: true });
  const before = await JSZip.loadAsync(staticBytes);
  const after = await JSZip.loadAsync(animatedBytes);
  for (const path of Object.keys(before.files).filter(path => path.endsWith('.rels'))) {
    const beforeXml = await before.file(path).async('string');
    const afterXml = await after.file(path).async('string');
    const targets = xml => [...xml.matchAll(/Target="([^"]+)"/g)].map(match => match[1]).sort();
    assert.deepEqual(targets(afterXml), targets(beforeXml), path);
  }
  const presentation = await loadPresentation(animatedBytes);
  assert.equal(getSlideAnimations(getSlides(presentation)[0]).length, 2);
  assert.deepEqual(validatePresentation(presentation), []);
});

test('none disables timing and slide transitions even when native mode is enabled', async () => {
  const zip = await JSZip.loadAsync(await buildDeck(fixture('none'), { nativeMotion: true }));
  const xml = await zip.file('ppt/slides/slide1.xml').async('string');
  assert.ok(!xml.includes('<p:timing'));
  assert.ok(!xml.includes('<p:transition'));
});

test('resource IDs cannot generate arbitrary outgoing links', () => {
  assert.equal(resourceUrl('javascript:alert(1)', 'https://example.test'), null);
  assert.equal(resourceUrl('unknown', 'https://example.test'), null);
});

test('only quiz slides add feedback pages and source slides use supplied references', async () => {
  const deck = fixture();
  deck.profile.sources = [];
  deck.manifest.slides = [
    { ...deck.manifest.slides[0], options: ['A', 'B'] },
    { ...deck.manifest.slides[0], id: 's002', kind: 'sources', bullets: ['Tên sách AI bịa'] },
  ];
  const zip = await JSZip.loadAsync(await buildDeck(deck));
  assert.equal(Object.keys(zip.files).filter(path => /^ppt\/slides\/slide\d+\.xml$/.test(path)).length, 2);
  const sourceSlide = await zip.file('ppt/slides/slide2.xml').async('string');
  assert.ok(!sourceSlide.includes('Tên sách AI bịa'));
  assert.ok(sourceSlide.includes('Chưa có tài liệu tham chiếu'));
});

test('all fifteen lesson layouts stay within bounds and export with native content', async () => {
  const deck = fixture();
  deck.title = 'Học liệu đa môn';
  const kinds = ['cover', 'objectives', 'hook', 'section', 'concept', 'process', 'compare', 'map', 'experiment', 'example', 'chart', 'quiz', 'video', 'summary', 'sources'];
  deck.manifest.slides = kinds.map((kind, index) => ({
    ...fixture().manifest.slides[0], id: `s${String(index + 1).padStart(3, '0')}`,
    kind, title: 'Mục tiêu và nội dung bài học', question: 'Bạn sẽ giải thích thế nào?',
    options: kind === 'quiz' ? ['Phương án A', 'Phương án B'] : [],
    correct_option: 0, explanation: 'Giải thích đáp án.',
    resource_id: kind === 'experiment' ? 'pendulum' : null,
    chart_data: kind === 'chart' ? { labels: ['3 V', '6 V'], values: [1, 2], series_name: 'I (A)', data_origin: 'example' } : null,
  }));
  for (const [index, item] of deck.manifest.slides.entries()) {
    assert.deepEqual(checkScene(createScene(item, deck, index)), [], item.kind);
  }
  const bytes = await buildDeck(deck, { origin: 'https://example.test', nativeMotion: true });
  const zip = await JSZip.loadAsync(bytes);
  assert.ok(Object.keys(zip.files).some(path => path.startsWith('ppt/charts/chart')));
  assert.ok(Object.keys(zip.files).some(path => path.endsWith('.svg')));
  assert.equal(getSlides(await loadPresentation(bytes)).length, 17);
});
