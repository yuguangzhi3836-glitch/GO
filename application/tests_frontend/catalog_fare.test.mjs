import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const code=fs.readFileSync('frontend/consumer/catalog-fare.js','utf8');
const supplierCode=fs.readFileSync('frontend/supplier/catalog-fare.js','utf8');
const rules={fare_family:'GO_STANDARD',timezone:'Asia/Tokyo',check_in_hour:15,cooling_off_minutes:30,
  cancellation_tiers:[{min_hours:168,fee_basis_points:0},{min_hours:0,fee_basis_points:125}],
  change_allowed:true,change_fee_minor:10000,stay_credit_enabled:true,stay_credit_days:365,
  no_show_grace_hours:1,no_show_fee_basis_points:5000};
const quote=()=>({prebook_id:'prebook-1',total_amount_minor:1443200,currency:'CNY',fare_rule:{rules,offer_rule_hash:'a'.repeat(64)}});
function setup(){const c={window:{},document:{},JSON};vm.runInNewContext(code,c);vm.runInNewContext(supplierCode,c);return c.window}
const money=n=>'¥'+(n/100).toFixed(2);

test('fare confirmation separates fee tiers, cooling, change and property credit terms',()=>{
  const w=setup(),html=w.GOCatalogFare.terms(quote(),money);
  for(const text of ['1.25%','30 分钟','¥100.00','365 天','仅限原酒店','包括','Asia/Tokyo']){
    if(text==='包括')assert.ok(html.includes('包含已付改期费'));
    else assert.ok(html.includes(text),text);
  }
  assert.ok(!html.includes('a'.repeat(64)));
});

test('cancelling fare confirmation has no accepted contract',async()=>{
  const w=setup();
  const result=await w.GOCatalogFare.accept(quote(),{money,dialog:async()=>null});
  assert.equal(result,null);
});

test('accepted hash remains bound to the rules displayed before asynchronous state changes',async()=>{
  const w=setup(),p=quote();
  const accepted=await w.GOCatalogFare.accept(p,{money,dialog:async(title,html,label,submit)=>{
    p.fare_rule.offer_rule_hash='b'.repeat(64);return submit();
  }});
  assert.equal(accepted.expected_fare_rule_hash,'a'.repeat(64));assert.equal(accepted.fare_confirmed,true);
});

test('declining hotel rules never selects or authorizes a traveler or creates an order',async()=>{
  const line=fs.readFileSync('frontend/consumer/booking-travelers.js','utf8').split('\n').find(l=>l.trim().startsWith('createOrder='));
  const calls=[],c={run:f=>f(),window:{GOCatalogFare:{accept:async()=>null}},state:{prebook:quote()},dialog(){},money,
    traveler:async()=>{calls.push('traveler');return 'trav-1'},post:async()=>calls.push('order'),renderPay(){}};
  vm.runInNewContext(line,c);await c.createOrder();assert.deepEqual(calls,[]);
});

test('accepted hotel contract is included with selected traveler and stable booking request identity',async()=>{
  const line=fs.readFileSync('frontend/consumer/booking-travelers.js','utf8').split('\n').find(l=>l.trim().startsWith('createOrder='));
  const calls=[],c={run:f=>f(),window:{GOCatalogFare:{accept:async()=>({expected_fare_rule_hash:'a'.repeat(64),fare_confirmed:true})}},state:{prebook:quote()},dialog(){},money,
    traveler:async()=>'trav-1',post:async(path,body,key)=>{calls.push({path,body,key});return {order_id:'one'}},renderPay(){}};
  vm.runInNewContext(line,c);await c.createOrder();await c.createOrder();
  assert.equal(calls[0].body.expected_fare_rule_hash,'a'.repeat(64));assert.equal(calls[0].body.traveler_id,'trav-1');
  assert.equal(calls[0].key,calls[1].key);
});

test('supplier money and percentage inputs use exact minor units',()=>{
  const w=setup();assert.equal(w.GOCatalogFareSupplier.minor('100.01'),10001);assert.equal(w.GOCatalogFareSupplier.minor('1.25'),125);
  for(const value of ['-1','1.005','1e3','Infinity'])assert.throws(()=>w.GOCatalogFareSupplier.minor(value));
});
