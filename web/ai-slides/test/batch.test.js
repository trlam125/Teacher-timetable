import test from 'node:test';
import assert from 'node:assert/strict';
import { driveBatch } from '../src/batch.js';

const draft = id => ({ id, version: 1, status: 'draft', profile: { consent: true, slide_count: 5, grounding: 'balanced' }, source_analysis: {}, blueprint: null });

test('batch persists each deck, skips finished decks and stops on quota without retry', async () => {
  const queue = { items: [{ id: 'one' }, { id: 'two' }] };
  const saved = new Map([['one', draft('one')], ['two', draft('two')]]);
  const calls = [];
  let limited = true;
  const request = async (step, current) => {
    calls.push(current.id + ':' + step);
    if (current.id === 'two' && limited) throw new Error('quota');
    const updated = { ...current, version: current.version + 1, status: step === 'plan' ? 'planned' : 'ready',
      blueprint: { warnings: [] }, manifest: step === 'author' ? { slides: Array(5).fill({}) } : undefined };
    saved.set(current.id, updated); return updated;
  };
  let persistence = 0;
  const options = { load: async id => saved.get(id), request, persist: async () => { persistence++; } };
  await assert.rejects(driveBatch(queue, options), /quota/);
  assert.deepEqual(calls, ['one:plan', 'one:author', 'two:plan']);
  assert.equal(queue.items[0].completed, true);
  assert.equal(queue.paused, 'error');
  limited = false;
  assert.equal((await driveBatch(queue, options)).state, 'ready');
  assert.deepEqual(calls.slice(3), ['two:plan', 'two:author']);
  assert.ok(persistence >= 4);
});

test('batch pauses for outline review before any author call', async () => {
  const queue = { items: [{ id: 'one' }, { id: 'two' }] };
  const calls = [];
  const result = await driveBatch(queue, { load: async id => draft(id), persist: async () => {},
    request: async (step, current) => { calls.push(step); return { ...current, version: 2, status: 'needs_review', blueprint: { warnings: ['Kiểm tra'] } }; } });
  assert.equal(result.state, 'needs_review');
  assert.deepEqual(calls, ['plan']);
});
