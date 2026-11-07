// Run manually with Node. No server, browser, or external packages required.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../app/static/workspace/change-impact.js'), 'utf8');
async function settle() { for (let i = 0; i < 20; i++) await Promise.resolve(); }

function fixture() {
  const elements = new Map();
  const checks = [
    {checked: false, disabled: false, dataset: {changeRemove: '1', lessonIds: '1'}},
    {checked: true, disabled: false, dataset: {changeRemove: '1', lessonIds: '3'}},
    {checked: true, disabled: true, dataset: {changeRemove: '1', lessonIds: '5'}},
  ];
  const resolutions = [{value: '', disabled: false, dataset: {changeResolution: '9'}}];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      disabled: false, textContent: '', innerHTML: '', checked: false, dataset: {}, open: false,
      addEventListener(type, handler) { this[type + 'Handler'] = handler; },
      showModal() { this.open = true; }, close() { this.open = false; },
      querySelectorAll(selector) {
        if (selector === '[data-change-resolution]') return resolutions;
        if (selector === '[data-change-remove]') return checks;
        return [...resolutions, ...checks, element('changeEnableEditing')];
      },
    });
    return elements.get(id);
  }
  const report = {
    can_apply: true, changed: true, requires_edit_mode: true,
    changes: [], assignments: [], lesson_actions: [], warnings: [], blockers: [],
    totals: {kept: 2, surplus: 1, tray_after: 0, blocks: {}},
    removal_candidates: [], impact_token: 'initial-selection',
  };
  const requests = [];
  let nextPreview = async () => ({ok: true, payload: structuredClone(report)});
  let nextApply = async () => ({ok: true, payload: {ok: true}});
  const context = vm.createContext({
    document: {getElementById: element},
    data: {project: {periods: 5, sessions: 2}, lessons: [{id: 1}]},
    PROJECT_ID: 1, esc: String,
    operationHeaders: value => value, readApiResponse: async response => response.payload,
    apiErrorMessage: () => 'Preview failed', requestFailureMessage: () => 'Network failed',
    fetch: async (url, options) => {
      const payload = JSON.parse(options.body);
      requests.push({url, payload});
      return url.endsWith('/apply') ? nextApply(payload) : nextPreview(payload);
    },
  });
  vm.runInContext(source, context);
  return {
    element, checks, resolutions, requests, report,
    preview: fn => {nextPreview = fn;}, apply: fn => {nextApply = fn;},
    editMode: () => vm.runInContext('setPostScheduleEditing(true)', context),
    start: () => vm.runInContext('runProjectChange({kind:"assignment",entity_type:"assignment",entity_id:1,values:{periods_per_week:2},resolutions:{9:"delete"}})', context),
    dirty: () => element('changeImpactDialog').onchange({target: {matches: () => true}}),
    toggle: checked => element('changeEnableEditing').changeHandler({target: {checked}}),
    cancel: () => element('changeImpactCancel').onclick(),
  };
}

test('changing selections then enabling editing cannot apply the old preview', async () => {
  const f = fixture(), done = f.start();
  await settle();
  f.dirty(); f.toggle(true);
  assert.equal(f.element('changeImpactApply').disabled, true);
  await f.element('changeImpactApply').onclick();
  assert.equal(f.requests.filter(row => row.url.endsWith('/apply')).length, 0);
  f.cancel(); assert.equal((await done).cancelled, true);
});

for (const failure of ['network', 'HTTP']) {
  test(`failed recalculation (${failure}) keeps Apply disabled even after edit mode toggles`, async () => {
    const f = fixture(); f.editMode(); const done = f.start(); await settle();
    f.dirty();
    f.preview(async () => {
      if (failure === 'network') throw new Error('offline');
      return {ok: false, payload: {message: 'Failed'}};
    });
    await f.element('changeImpactRecalculate').onclick();
    f.toggle(false); f.toggle(true);
    assert.equal(f.element('changeImpactApply').disabled, true);
    assert.equal(f.checks[0].disabled, false);
    assert.equal(f.checks[2].disabled, true);
    f.cancel(); await done;
  });
}

test('successful recalculation applies the current selections and matching token', async () => {
  const f = fixture(), done = f.start(); await settle();
  f.checks[0].checked = true; f.checks[1].checked = false;
  f.dirty(); f.toggle(true);
  f.preview(async () => ({ok: true, payload: {...f.report, impact_token: 'new-selection'}}));
  await f.element('changeImpactRecalculate').onclick();
  assert.equal(f.element('changeImpactApply').disabled, false);
  await f.element('changeImpactApply').onclick();
  const applied = f.requests.find(row => row.url.endsWith('/apply')).payload;
  assert.deepEqual(applied.request.remove_lesson_ids, {'1': [1]});
  assert.deepEqual(applied.request.resolutions, {}); // Clearing a choice clears its stale request value.
  assert.equal(applied.impact_token, 'new-selection');
  assert.equal((await done).cancelled, false);
});

test('selection changes while a recalculation is pending invalidate its response', async () => {
  const f = fixture(); f.editMode(); const done = f.start(); await settle();
  let respond;
  f.preview(() => new Promise(resolve => {respond = resolve;}));
  const pending = f.element('changeImpactRecalculate').onclick();
  await settle();
  assert.equal(f.checks[0].disabled, true);
  assert.equal(f.element('changeEnableEditing').disabled, true);
  // Even a programmatic change while inputs are disabled cannot validate an old response.
  f.dirty();
  respond({ok: true, payload: f.report}); await pending;
  assert.equal(f.element('changeImpactApply').disabled, true);
  assert.equal(f.checks[0].disabled, false);
  assert.equal(f.checks[2].disabled, true);
  f.cancel(); await done;
});

test('busy apply prevents duplicate submissions and freezes choices', async () => {
  const f = fixture(); f.editMode(); const done = f.start(); await settle();
  let respond;
  f.apply(() => new Promise(resolve => {respond = resolve;}));
  const pending = f.element('changeImpactApply').onclick(); await settle();
  await f.element('changeImpactApply').onclick();
  assert.equal(f.requests.filter(row => row.url.endsWith('/apply')).length, 1);
  assert.equal(f.checks[0].disabled, true);
  respond({ok: true, payload: {ok: true}}); await pending; await done;
});

test('an interrupted apply remains retryable with the same token', async () => {
  const f = fixture(); f.editMode(); const done = f.start(); await settle();
  f.apply(async () => {throw new Error('offline');});
  await f.element('changeImpactApply').onclick();
  assert.equal(f.element('changeImpactApply').disabled, false);
  f.apply(async () => ({ok: true, payload: {ok: true, already_applied: true}}));
  await f.element('changeImpactApply').onclick();
  const applied = f.requests.filter(row => row.url.endsWith('/apply'));
  assert.equal(applied.length, 2);
  assert.deepEqual(applied[0].payload, applied[1].payload);
  await done;
});
