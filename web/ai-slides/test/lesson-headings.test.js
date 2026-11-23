import test from 'node:test';
import assert from 'node:assert/strict';
import { lessonHeadings } from '../src/lesson-headings.js';

test('finds explicit lessons/chapters, keeps titles and ignores prose', () => {
  assert.deepEqual(lessonHeadings('Chương II: Điện học\nBài 12: Định luật Ôm\nTrong bài 12 ta học về dòng điện.'), ['Chương II: Điện học', 'Bài 12: Định luật Ôm']);
});
test('does not mistake printed TOC numbers for physical PDF pages', () => {
  assert.deepEqual(lessonHeadings('MỤC LỤC\nBài 12: Định luật Ôm\n35'), []);
  assert.deepEqual(lessonHeadings('Bài 12: Định luật Ôm ........ 35\nBài 13: Điện trở 40'), []);
});
