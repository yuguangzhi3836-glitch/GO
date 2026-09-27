const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const sandbox = {module: {exports: {}}};
vm.runInNewContext(fs.readFileSync(require.resolve('../frontend/consumer/date-range.js'), 'utf8'), sandbox);
const {createSelection, bind} = sandbox.module.exports;

test('hotel stay is selected as one range across a month and year boundary', () => {
  const range = createSelection();
  assert.equal(range.select('2026-12-30').complete, false);
  assert.deepEqual(JSON.parse(JSON.stringify(range.select('2027-01-02'))), {
    start: '2026-12-30', end: '2027-01-02', status: 'COMPLETE', complete: true,
  });
});

test('hotel rejects a zero-night stay and accepts the next checkout', () => {
  const range = createSelection();
  range.select('2026-10-20');
  assert.equal(range.select('2026-10-20').complete, false);
  assert.equal(range.select('2026-10-21').complete, true);
});

test('editing a stay and selecting an earlier day starts a new valid range', () => {
  const range = createSelection({start: '2026-10-20', end: '2026-10-23'});
  assert.equal(range.select('2026-10-25').end, null);
  assert.equal(range.select('2026-10-19').start, '2026-10-19');
  assert.equal(range.select('2026-10-21').end, '2026-10-21');
});

test('mobile binding preserves both dates and avoids two native pickers', () => {
  const input = value => ({value, type: 'date', min: '', max: '',
    attrs: {}, handlers: {},
    setAttribute(key, value) { this.attrs[key] = value; },
    addEventListener(key, callback) { this.handlers[key] = callback; },
  });
  const start = input('2026-10-20'), end = input('2026-10-23');
  sandbox.document = {getElementById: id => ({start, end}[id])};
  try {
    const binding = bind({startId: 'start', endId: 'end'});
    assert.equal(bind({startId: 'start', endId: 'end'}), binding);
    assert.equal(start.value, '2026-10-20');
    assert.equal(end.value, '2026-10-23');
    for (const field of [start, end]) {
      assert.equal(field.type, 'text');
      assert.equal(field.readOnly, true);
      assert.equal(field.attrs['aria-haspopup'], 'dialog');
      assert.equal(typeof field.handlers.click, 'function');
    }
  } finally { delete sandbox.document; }
});
