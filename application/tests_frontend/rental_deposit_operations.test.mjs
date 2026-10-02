import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code=fs.readFileSync('frontend/admin/rental-deposit-finance.js','utf8');
const clone=x=>JSON.parse(JSON.stringify(x));
function fixture(){
  let html='',snapshot={order_id:'r1',read_only:true,source:{obligation_id:'dep1',revision:2,source_hash:'a'.repeat(64),
    state:'ACTIVATED',amount_minor:200000,currency:'CNY',expires_at:'2026-10-01'},money:{state:'NOT_AUTHORIZED',
    authorized_minor:0,captured_minor:0,released_minor:0,remaining_minor:0},can_authorize:true,decisions:[],movements:[],blockers:[]};
  const calls=[],events=[],nodes=new Map();let post=async()=>({}),read=async()=>clone(snapshot);
  const form=()=>{const checkbox={checked:false};return {dataset:{},querySelector:()=>checkbox}};
  const container={isConnected:true,get innerHTML(){return html},set innerHTML(v){html=v;nodes.clear();nodes.set('[data-refresh]',{});
    const forms=[...v.matchAll(/data-action="(\d+)"/g)].map(match=>({...form(),dataset:{action:match[1]}}));nodes.set('forms',forms);
    if(v.includes('data-retry'))nodes.set('[data-retry]',form());if(v.includes('data-reset'))nodes.set('[data-reset]',{});},
    querySelector:key=>nodes.get(key),querySelectorAll:()=>nodes.get('forms')||[]};
  const window={dispatchEvent:e=>events.push(e),addEventListener(){},removeEventListener(){}};
  vm.runInNewContext(code,{window,Intl,CustomEvent:class{constructor(type,body){this.type=type;this.detail=body.detail}}});
  return {ui:window.GORentalDepositOperations,container,calls,events,
    request:async(url,options)=>{calls.push({url,options:options&&clone(options)});return options?post(url,options):read();},
    get snapshot(){return snapshot},set snapshot(v){snapshot=v},set post(fn){post=fn},set read(fn){read=fn},
    get forms(){return nodes.get('forms')||[]},get retry(){return nodes.get('[data-retry]')},get refresh(){return nodes.get('[data-refresh]')}};
}
const submit={preventDefault(){}};
async function start(f){await f.ui.render({container:f.container,orderId:'r1',request:f.request});}

test('administrator must explicitly confirm server-derived source; no editable amount or hash',async()=>{
  const f=fixture();await start(f);const form=f.forms[0];await form.onsubmit(submit);
  assert.equal(f.calls.filter(x=>x.options).length,0);form.querySelector().checked=true;await form.onsubmit(submit);
  const request=f.calls.find(x=>x.options);assert.deepEqual(request.options.body,{expected_revision:2,expected_source_hash:'a'.repeat(64)});
  assert.equal(f.container.innerHTML.includes('name="amount'),false);
});
test('lost response is read back; retry preserves exact source version and body',async()=>{
  const f=fixture();f.post=async()=>{throw Error('response lost')};await start(f);f.forms[0].querySelector().checked=true;
  await f.forms[0].onsubmit(submit);assert.ok(f.retry);assert.equal(f.calls.filter(x=>!x.options).length,2);
  f.retry.querySelector().checked=true;await f.retry.onsubmit(submit);
  const posts=f.calls.filter(x=>x.options);assert.equal(posts.length,2);assert.deepEqual(posts[0],posts[1]);
});
test('unknown readback prohibits retry and all new financial actions',async()=>{
  const f=fixture();await start(f);f.post=async()=>{f.snapshot.money={state:'RECONCILIATION_REQUIRED'};throw Error('timeout')};
  f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(submit);
  assert.equal(f.forms.length,0);assert.ok(f.container.innerHTML.includes('仅可核对'));
  f.retry.querySelector().checked=true;await f.retry.onsubmit(submit);assert.equal(f.calls.filter(x=>x.options).length,1);
});
test('changed source never silently upgrades a pending retry',async()=>{
  const f=fixture();await start(f);f.post=async()=>{f.snapshot.source.revision=3;f.snapshot.source.source_hash='b'.repeat(64);throw Error('conflict')};
  f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(submit);f.retry.querySelector().checked=true;
  await f.retry.onsubmit(submit);assert.equal(f.calls.filter(x=>x.options).length,1);
});
test('double submit while in flight cannot dispatch twice',async()=>{
  const f=fixture();let finish;f.post=()=>new Promise(resolve=>{finish=resolve});await start(f);
  const form=f.forms[0];form.querySelector().checked=true;const pending=form.onsubmit(submit);
  await form.onsubmit(submit);assert.equal(f.calls.filter(x=>x.options).length,1);finish({});await pending;
});
test('read failure removes mutation choices even if last snapshot was actionable',async()=>{
  const f=fixture();await start(f);f.read=async()=>{throw Error('read offline')};await f.refresh.onclick();
  assert.equal(f.forms.length,0);assert.ok(f.container.innerHTML.includes('读取失败'));
});
test('settlement sends server decision hash without caller money fields',async()=>{
  const f=fixture();f.snapshot.money.state='AUTHORIZED';f.snapshot.can_authorize=false;
  f.snapshot.decisions=[{case_id:'c1',case_version:3,can_settle:true,decision:{case_id:'c1',case_version:3,decision_hash:'d'.repeat(64),awarded_minor:4000}}];
  await start(f);f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(submit);
  const body=f.calls.find(x=>x.options).options.body;assert.equal(body.case_id,'c1');assert.equal(body.expected_decision_hash,'d'.repeat(64));assert.equal('awarded_minor' in body,false);
});
test('return release uses independent closure version and excludes claim and amount',async()=>{
  const f=fixture();f.snapshot.money={state:'AUTHORIZED',remaining_minor:200000};f.snapshot.can_authorize=false;
  f.snapshot.release={can_release:true,fact:{reason:'NO_DAMAGE_RETURN',release_revision:1,release_hash:'e'.repeat(64)}};
  await start(f);f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(submit);
  const request=f.calls.find(x=>x.options);assert.ok(request.url.endsWith('/release'));
  assert.deepEqual(request.options.body,{expected_revision:2,expected_source_hash:'a'.repeat(64),expected_release_revision:1,expected_release_hash:'e'.repeat(64)});
});
test('settled appeal is presented as separate review, never another capture button',async()=>{
  const f=fixture();f.snapshot.money.state='SETTLED';f.snapshot.can_authorize=false;
  f.snapshot.decisions=[{case_id:'c1',case_version:5,can_settle:false,blocker:'SETTLED_MONEY_REQUIRES_SEPARATE_COMPENSATION_REVIEW'}];
  await start(f);assert.equal(f.forms.length,0);assert.ok(f.container.innerHTML.includes('单独补偿审核'));
});

test('compensation posts bound version and reads confirmed net amount',async()=>{
  const f=fixture();f.snapshot.can_authorize=false;f.snapshot.money={state:'SETTLED',captured_minor:4000,compensated_minor:0,net_captured_minor:4000};
  f.snapshot.decisions=[{can_compensate:true,compensation:{case_id:'c1',case_version:5,decision_hash:'f'.repeat(64),amount_minor:3000,target_net_captured_minor:1000}}];
  f.post=async()=>{f.snapshot.money.compensated_minor=3000;f.snapshot.money.net_captured_minor=1000;f.snapshot.decisions[0].can_compensate=false;f.snapshot.decisions[0].compensation.already_applied=true;return {};};
  await start(f);assert.ok(f.container.innerHTML.includes('执行申诉减收补偿'));
  f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(submit);
  const req=f.calls.find(x=>x.options);assert.ok(req.url.endsWith('/compensate'));assert.equal(req.options.body.expected_case_version,5);assert.equal('amount_minor' in req.options.body,false);
  assert.equal(f.forms.length,0);assert.equal(f.retry,undefined);assert.ok(f.container.innerHTML.includes('已补偿'));assert.ok(f.container.innerHTML.includes('10.00'));
});
test('settled alone cannot confirm a lost compensation response',async()=>{
  const f=fixture();f.snapshot.can_authorize=false;f.snapshot.money.state='SETTLED';
  f.snapshot.decisions=[{can_compensate:true,compensation:{case_id:'c1',case_version:5,decision_hash:'f'.repeat(64),amount_minor:3000,target_net_captured_minor:1000}}];
  f.post=async()=>{throw Error('lost')};await start(f);f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(submit);
  assert.ok(f.retry);f.retry.querySelector().checked=true;await f.retry.onsubmit(submit);
  const calls=f.calls.filter(x=>x.options);assert.equal(calls.length,2);assert.deepEqual(calls[0],calls[1]);
});

async function consumerMoney(funds){
  let section;
  const element=()=>({dataset:{},isConnected:true,innerHTML:'',insertAdjacentHTML(_,html){this.innerHTML+=html},append(){}});
  const order={order_id:'r1'};
  const context={Intl,URLSearchParams,Date,Symbol,Map,crypto:{randomUUID:()=> 'id'},state:{rentalOrder:order},renderMobilityOrder(){},
    money:(n)=>String(n/100),api:async path=>path.includes('capabilities')?{simulation_available:true}:path.includes('damage-cases')?{items:[]}:path.includes('deposit-money')?funds:{
      obligation_id:'d1',state:'ACTIVATED',revision:2,source_hash:'a'.repeat(64),source:{amount_minor:200000,currency:'CNY',expires_at:'2027-01-01T00:00:00',contract_snapshot:{maximum_damage_award_minor:200000}}},
    document:{createElement:element,querySelector:()=>({append(s){section=s}})}};
  vm.runInNewContext(fs.readFileSync('frontend/consumer/rental-deposit.js','utf8'),context);
  context.renderMobilityOrder('RENTAL');await new Promise(resolve=>setImmediate(resolve));return section.innerHTML;
}
test('consumer sees compensation and net capture from verified money only',async()=>{
  const html=await consumerMoney({state:'SETTLED',currency:'CNY',authorized_minor:200000,captured_minor:4000,released_minor:196000,compensated_minor:3000,net_captured_minor:1000,remaining_minor:0});
  assert.ok(html.includes('data-deposit-compensated>30'));assert.ok(html.includes('data-deposit-net-captured>10'));
  const unknown=await consumerMoney({state:'RECONCILIATION_REQUIRED',compensated_minor:null,net_captured_minor:null});
  assert.ok(unknown.includes('资金状态待核验'));assert.equal(unknown.includes('data-deposit-compensated'),false);
});
