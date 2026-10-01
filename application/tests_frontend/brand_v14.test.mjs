import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';

const text=p=>readFileSync(p,'utf8');
const sha=p=>createHash('sha256').update(readFileSync(p)).digest('hex');

test('consumer uses approved SI artwork for both responsive asset aliases',()=>{
  const app=text('frontend/consumer/app.js');
  assert.match(app,/go-main-lockup-v14\.svg/);
  assert.match(app,/\?v=20261001-si-direct/);
  assert.match(app,/go-compact-lockup-v14\.svg\?v=20261001-si-direct/);
  assert.match(app,/max-width:479px/);
  assert.equal(sha('frontend/consumer/assets/go-main-lockup-v14.svg'),'26b68e4df4fb017fa7d54ab508eb4db4b08f79733e5263ffe29f0430c633f961');
  assert.equal(sha('frontend/consumer/assets/go-compact-lockup-v14.svg'),'26b68e4df4fb017fa7d54ab508eb4db4b08f79733e5263ffe29f0430c633f961');
});

test('supplier and admin share the reverse SI lockup',()=>{
  const app=text('frontend/shared/app.js');
  assert.match(app,/go-compact-v14-reverse\.svg\?v=20261001-si-direct/);
  assert.match(app,/go-symbol-v14\.svg\?v=20260909-depth28/);
  assert.equal(sha('frontend/shared/go-compact-v14-reverse.svg'),'a5f55a24c180debe56711b6b4338f34ae1b7c5fefcb4035d65d95ff5ad16e911');
});

test('all three entry documents load the SI update without stale script caches',()=>{
  for(const path of ['frontend/consumer/index.html','frontend/supplier/index.html','frontend/admin/index.html']){
    assert.match(text(path),/app\.js\?v=20261001-si-direct/);
  }
});

test('GO subbrands use V14 geometry with a deliberately recessive GO tier',()=>{
  for(const path of ['frontend/consumer/assets/go-ai.svg','frontend/consumer/assets/go-offer.svg']){
    const svg=text(path);
    assert.match(svg,/equal-circles-lighter-v7/);
    assert.match(svg,/L835 500 A335 335/);
    assert.match(svg,/data-brand-tier="subbrand"/);
    assert.match(svg,/data-subbrand-go="recessive" opacity="\.78"/);
    assert.match(svg,/translate\(18 30\) scale\(\.20\)/);
    assert.doesNotMatch(svg,/equal-circles-v26/);
  }
});

test('legacy main lockup resolves to SI while standalone GO symbols stay unchanged',()=>{
  assert.equal(sha('frontend/consumer/assets/go-main-lockup.svg'),'26b68e4df4fb017fa7d54ab508eb4db4b08f79733e5263ffe29f0430c633f961');
  for(const path of ['frontend/consumer/assets/go-mark.svg','frontend/consumer/assets/go-symbol.svg','frontend/shared/go-mark.svg']){
    assert.equal(sha(path),'5066c0796c25a5ef7200bed22368660fb2f567e2f2bfd491f125cda66f7d2c2e');
  }
});
