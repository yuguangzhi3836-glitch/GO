import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';

const text=p=>readFileSync(p,'utf8');
const sha=p=>createHash('sha256').update(readFileSync(p)).digest('hex');

test('consumer uses locked V14 main and compact artwork with responsive selection',()=>{
  const app=text('frontend/consumer/app.js');
  assert.match(app,/go-main-lockup-v14\.svg/);
  assert.match(app,/\?v=20260909-depth28/);
  assert.match(app,/go-compact-lockup-v14\.svg\?v=20260909-depth28/);
  assert.match(app,/max-width:479px/);
  assert.equal(sha('frontend/consumer/assets/go-main-lockup-v14.svg'),'ad492e6e4bd8c29ff541b155f02e061ae0cb4f2cc971126047e3589c267c513d');
  assert.equal(sha('frontend/consumer/assets/go-compact-lockup-v14.svg'),'2d1fad1032acadcb9ff03e19c35c6dc249586942381546893292220156bd114b');
});

test('supplier and admin share the locked reverse V14 compact lockup',()=>{
  const app=text('frontend/shared/app.js');
  assert.match(app,/go-compact-v14-reverse\.svg\?v=20260909-depth28/);
  assert.match(app,/go-symbol-v14\.svg\?v=20260909-depth28/);
  assert.equal(sha('frontend/shared/go-compact-v14-reverse.svg'),'5bea6572eb39e96e34384d0076dd81662a8e9d23f549dfc7ecb1bfd24f2aac99');
});

test('all three entry documents advance cache tokens together',()=>{
  for(const path of ['frontend/consumer/index.html','frontend/supplier/index.html','frontend/admin/index.html']){
    assert.match(text(path),/app\.js\?v=20260925-integration1/);
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

test('legacy runtime asset names also resolve to locked V14 geometry',()=>{
  assert.equal(sha('frontend/consumer/assets/go-main-lockup.svg'),'ad492e6e4bd8c29ff541b155f02e061ae0cb4f2cc971126047e3589c267c513d');
  for(const path of ['frontend/consumer/assets/go-mark.svg','frontend/consumer/assets/go-symbol.svg','frontend/shared/go-mark.svg']){
    assert.equal(sha(path),'5066c0796c25a5ef7200bed22368660fb2f567e2f2bfd491f125cda66f7d2c2e');
  }
});
