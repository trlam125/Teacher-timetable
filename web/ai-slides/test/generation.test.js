import test from 'node:test';
import assert from 'node:assert/strict';
import { driveGeneration } from '../src/generation.js';

function draft(mode = 'automatic', count = 15) {
  return { id: 'deck-1', version: 1, status: 'draft', profile: { generation_mode: mode, slide_count: count, consent: true },
    blueprint: null, manifest: null, source_analysis: { unresolved: false }, busy: false };
}
function fixture(calls) {
  return async (kind, current) => {
    calls.push(kind);
    if (kind === 'plan') return { ...current, version: current.version + 1, status: 'planned', blueprint: { warnings: [] } };
    const start = current.manifest?.slides?.length || 0;
    const length = Math.min(start + 5, current.profile.slide_count);
    return { ...current, version: current.version + 1, status: length === current.profile.slide_count ? 'ready' : 'authoring',
      manifest: { slides: Array.from({ length }, (_, index) => ({ id: `s${index + 1}` })) } };
  };
}

test('one automatic action plans and saves all three batches in order', async () => {
  const calls = [], saved = [];
  const result = await driveGeneration(draft(), { request: fixture(calls), onDeck: deck => saved.push(deck.version) });
  assert.deepEqual(calls, ['plan', 'author', 'author', 'author']);
  assert.deepEqual(saved, [2, 3, 4, 5]);
  assert.equal(result.state, 'ready');
  assert.equal(result.deck.manifest.slides.length, 15);
});
test('outline choice stops after planning', async () => {
  const calls = [];
  const result = await driveGeneration(draft('outline'), { request: fixture(calls) });
  assert.deepEqual(calls, ['plan']);
  assert.equal(result.state, 'outline');
});
test('planner warnings stop automation until a reviewed continuation', async () => {
  const calls = [];
  const result = await driveGeneration(draft(), { request: async (kind, current) => {
    calls.push(kind);
    return { ...current, version: 2, status: 'needs_review', blueprint: { warnings: ['Nguồn cần kiểm tra'] } };
  } });
  assert.deepEqual(calls, ['plan']);
  assert.equal(result.state, 'needs_review');
  const reviewed = { ...result.deck, status: 'planned', blueprint: { warnings: [] } };
  const resumed = await driveGeneration(reviewed, { request: fixture(calls) });
  assert.equal(resumed.state, 'ready');
  assert.equal(calls.filter(kind => kind === 'plan').length, 1);
});
test('source review, missing consent, busy and old strict outline make no AI call', async () => {
  const cases = [
    [deck => { deck.source_analysis.unresolved = true; }, 'needs_source_review'],
    [deck => { deck.profile.consent = false; }, 'needs_consent'],
    [deck => { deck.busy = true; }, 'busy'],
    [deck => { deck.profile.grounding = 'strict'; deck.blueprint = { warnings: [] }; }, 'needs_replan'],
  ];
  for (const [change, state] of cases) {
    const deck = draft(); change(deck);
    const result = await driveGeneration(deck, { request: () => assert.fail('No request should be made') });
    assert.equal(result.state, state);
  }
});
test('failed batch is not retried and explicit resume preserves completed slides', async () => {
  const calls = []; let saved;
  const request = fixture(calls);
  await assert.rejects(driveGeneration(draft(), { onDeck: deck => { saved = deck; }, request: async (kind, current) => {
    if (kind === 'author' && current.manifest?.slides?.length === 5) { calls.push('failed-author'); throw new Error('AI_TIMEOUT'); }
    return request(kind, current);
  } }), /AI_TIMEOUT/);
  assert.deepEqual(calls, ['plan', 'author', 'failed-author']);
  assert.equal(saved.manifest.slides.length, 5);
  const result = await driveGeneration(saved, { request });
  assert.equal(result.deck.manifest.slides.length, 15);
  assert.deepEqual(calls.slice(3), ['author', 'author']);
});
test('ready deck makes no request and stalled responses cannot spend another call', async () => {
  const complete = { ...draft(), status: 'ready', blueprint: { warnings: [] }, manifest: { slides: Array(15).fill({}) } };
  const ready = await driveGeneration(complete, { request: () => assert.fail('Already ready') });
  assert.equal(ready.state, 'ready');
  const calls = [];
  await assert.rejects(driveGeneration({ ...draft(), blueprint: { warnings: [] } }, { request: async (kind, current) => {
    calls.push(kind); return { ...current, version: current.version + 1, status: 'authoring', manifest: { slides: [] } };
  } }), /tiến độ/i);
  assert.deepEqual(calls, ['author']);
});
