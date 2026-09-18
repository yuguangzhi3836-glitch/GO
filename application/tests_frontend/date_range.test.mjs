import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const module={exports:{}};
vm.runInNewContext(fs.readFileSync('frontend/consumer/date-range.js','utf8'),{module,exports:module.exports});
const picker=module.exports;

test('cross-month range stays in one two-step selection',()=>{
  const model=picker.createSelection();
  assert.equal(model.select('2026-01-31').complete,false);
  const result=model.select('2026-02-02');
  assert.equal(JSON.stringify(result),JSON.stringify({start:'2026-01-31',end:'2026-02-02',status:'COMPLETE',complete:true}));
});

test('reverse second choice becomes the new start and still requires an end',()=>{
  const model=picker.createSelection();
  model.select('2026-09-18');
  const result=model.select('2026-09-15');
  assert.equal(result.start,'2026-09-15');
  assert.equal(result.end,null);
  assert.equal(result.complete,false);
  assert.equal(result.status,'RESTARTED');
});

test('hotel same-day is incomplete while rental same-day is allowed',()=>{
  const hotel=picker.createSelection({allowSameDay:false});
  hotel.select('2026-10-03');
  assert.equal(hotel.select('2026-10-03').complete,false);
  assert.equal(hotel.snapshot().status,'SAME_DAY_BLOCKED');

  const rental=picker.createSelection({allowSameDay:true});
  rental.select('2026-10-03');
  assert.equal(rental.select('2026-10-03').complete,true);
});

test('single-date verticals remain native business exceptions',()=>{
  const app=fs.readFileSync('frontend/consumer/app.js','utf8');
  assert.match(app,/id="fdate" type="date"/);
  assert.match(app,/id="rdate" type="date"/);
  assert.match(app,/id="adate" type="date"/);
  assert.doesNotMatch(app,/GODateRange\.bind\(\{startId:'fdate'/);
  assert.doesNotMatch(app,/GODateRange\.bind\(\{startId:'rdate'/);
});

test('mobile picker is a full-width bottom sheet with touch-size controls',()=>{
  const css=fs.readFileSync('frontend/consumer/styles.css','utf8');
  assert.match(css,/\.go-date-range-backdrop/);
  assert.match(css,/\.go-calendar-grid button\{[^}]*min-height:44px/);
  assert.match(css,/@media\(max-width:600px\)\{\.go-date-range\{[^}]*width:100%/);
});

test('range day clicks never close the dialog and confirmation starts disabled',()=>{
  const source=fs.readFileSync('frontend/consumer/date-range.js','utf8');
  assert.match(source,/data-confirm disabled/);
  assert.match(source,/grid\.querySelectorAll\('\[data-day\]'\).*model\.select/);
  assert.doesNotMatch(source,/data-day[^\n]*wrap\.remove/);
});
