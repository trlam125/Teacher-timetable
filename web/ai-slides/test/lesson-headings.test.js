import test from 'node:test';
import assert from 'node:assert/strict';
import { lessonHeadings, lessonRanges } from '../src/lesson-headings.js';

test('lessons on the same page have exact distinct text boundaries', () => {
  const text = 'Kết thúc bài trước.\nBài 1: Điện trở\nNội dung điện trở.\nBài 2: Công suất\nNội dung công suất.';
  const ranges = lessonRanges(text);
  assert.equal(ranges.length, 2);
  const first = text.slice(ranges[0].startOffset, ranges[0].endOffset);
  assert.ok(first.startsWith('Bài 1: Điện trở'));
  assert.ok(!first.includes('Công suất'));
  assert.ok(!first.includes('Kết thúc bài trước'));
});

test('finds explicit lessons/chapters, keeps titles and ignores prose', () => {
  assert.deepEqual(lessonHeadings('Chương II: Điện học\nBài 12: Định luật Ôm\nTrong bài 12 ta học về dòng điện.'), ['Chương II: Điện học', 'Bài 12: Định luật Ôm']);
});
test('does not mistake printed TOC numbers for physical PDF pages', () => {
  assert.deepEqual(lessonHeadings('MỤC LỤC\nBài 12: Định luật Ôm\n35'), []);
  assert.deepEqual(lessonHeadings('Bài 12: Định luật Ôm ........ 35\nBài 13: Điện trở 40'), []);
});
