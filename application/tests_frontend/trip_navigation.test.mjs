import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code = fs.readFileSync('frontend/consumer/trip-navigation.js','utf8');
function setup() {
  const context = {window:{}};
  vm.runInNewContext(code,context);
  return context.window.GOTrips;
}
function item(kind) {
  return {vertical:kind.startsWith('HOTEL')?'HOTEL':kind,order_id:'owned_29',
    navigation:{kind,order_id:'owned_29'},title:'<img src=x onerror=alert(1)>'};
}
for (const kind of ['HOTEL_CATALOG','HOTEL_DIRECT','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']) {
  test(`${kind}: reopen the existing order without a new order or payment`, async()=>{
    const ui=setup(),calls=[];
    await ui.open(item(kind),{
      current:()=>true,
      api:async(path,options)=>{assert.equal(options,undefined);calls.push(path);return kind==='HOTEL_CATALOG'?{order:{order_id:'owned_29'}}:{order_id:'owned_29'};},
      navigate:href=>calls.push(href), render:(k,v)=>calls.push(k)
    });
    if(kind==='HOTEL_DIRECT') assert.deepEqual(calls,['/go-app/direct.html?reservation=owned_29']);
    else {assert.equal(calls.length,2);assert.equal(calls[1],kind);assert.match(calls[0],/\/owned_29(?:\/detail)?$/);}
  });
}
test('untrusted evidence URLs and unsupported identities never select an endpoint',()=>{
  const ui=setup();
  for(const ref of [null,{kind:'__proto__',order_id:'owned_29'}, {kind:'FLIGHT',order_id:'../other'},
    {kind:'FLIGHT',order_id:'another_order'},{kind:'HOTEL_DIRECT',order_id:'owned_29'}]) {
    assert.equal(ui.target({...item('FLIGHT'),navigation:ref,facts_json:{detail_url:'https://evil.test'}}),null);
  }
  assert.doesNotMatch(ui.cards([{...item('FLIGHT'),navigation:null}],x=>x,()=>''),/href=|data-go-trip-index/);
});
test('card output escapes content and uses current canonical status',()=>{
  const ui=setup();
  const html=ui.cards([{...item('FLIGHT'),lifecycle_state:'CONFIRMED',native_status:'UNKNOWN_EXTERNAL_STATE'}],x=>x,()=>'<script>');
  assert.match(html,/UNKNOWN_EXTERNAL_STATE/);assert.doesNotMatch(html,/>CONFIRMED</);
  assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img|<script/);
});
test('an order response cannot populate a different order or vertical',async()=>{
  const ui=setup();
  for(const value of [{order_id:'other'},{order_id:'owned_29',vertical:'RENTAL'}]) {
    await assert.rejects(ui.open(item('RIDE'),{api:async()=>value,current:()=>true,
      render:()=>assert.fail('wrong order rendered')}),/IDENTITY_MISMATCH/);
  }
});
test('late order response cannot overwrite a new screen',async()=>{
  await setup().open(item('RAIL'),{api:async()=>({order_id:'owned_29'}),current:()=>false,
    render:()=>assert.fail('detached screen rendered')});
});
test('continuing payment re-reads amount and uses the original order only',async()=>{
  const calls=[],ui=setup();
  const context={current:()=>true,api:async(path)=>{calls.push(['get',path]);return {order_id:'owned_29',status:'PAYMENT_PENDING',total_amount_minor:4321,currency:'CNY'};},
    pay:async(v,o)=>calls.push(['confirm',v,o.order_id,o.total_amount_minor]),render:k=>calls.push(['render',k])};
  await ui.resumePayment(item('FLIGHT'),context);
  assert.deepEqual(calls.map(x=>x[0]),['get','confirm','get','render']);
  assert.deepEqual(calls[1],['confirm','FLIGHT','owned_29',4321]);
});
test('already paid or expired orders cannot invoke payment from a stale card',async()=>{
  for(const status of ['TICKETED','CANCELLED','UNKNOWN_EXTERNAL_STATE']){
    let reads=0,rendered=0;
    await setup().resumePayment(item('RAIL'),{current:()=>true,
      api:async()=>{reads++;return {order_id:'owned_29',status};},
      pay:()=>assert.fail('unexpected payment'),render:()=>rendered++});
    assert.equal(reads,1);assert.equal(rendered,1);
  }
});
test('payment timeout reads the same order and never silently resends',async()=>{
  let payments=0,reads=0;
  await assert.rejects(setup().resumePayment(item('ATTRACTION'),{current:()=>true,
    api:async()=>{reads++;return {order_id:'owned_29',status:'PAYMENT_PENDING'};},
    pay:async()=>{payments++;throw Error('unknown outcome');},render:()=>{}}),/unknown outcome/);
  assert.equal(payments,1);assert.equal(reads,2);
});
test('leaving before the fresh order read prevents a payment dialog',async()=>{
  await setup().resumePayment(item('FLIGHT'),{current:()=>false,
    api:async()=>({order_id:'owned_29',status:'PAYMENT_PENDING'}),pay:()=>assert.fail('detached payment')});
});
test('real app dispatch uses every existing enriched order renderer',()=>{
  const app=fs.readFileSync('frontend/consumer/app.js','utf8');
  const source=app.slice(app.indexOf('function renderUnifiedOrder('),app.indexOf('async function showTrips()'));
  for(const kind of ['HOTEL_CATALOG','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']) {
    const calls=[],state={};
    const c={state,renderTrip:()=>calls.push('HOTEL_CATALOG'),renderFlightOrder:()=>calls.push('FLIGHT'),
      renderRailOrder:()=>calls.push('RAIL'),renderAttractionOrder:()=>calls.push('ATTRACTION'),
      renderMobilityOrder:v=>calls.push(v)};
    vm.createContext(c);vm.runInContext(source,c);
    c.renderUnifiedOrder(kind,kind==='HOTEL_CATALOG'?{order:{status:'CONFIRMED'}}:{status:'CONFIRMED'});
    assert.deepEqual(calls,[kind]);
  }
});
