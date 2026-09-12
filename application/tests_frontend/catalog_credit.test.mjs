import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function fixture(){
 const posts=[],dialogs=[],buttons=new Map();let html='',checked=true,traveler='actual-traveler',fail=false;
 const c={stay_credit_id:'credit-one',status:'REDEEMED',credit_value_minor:10000,available_minor:0,currency:'CNY',expires_at:'2027-09-07T00:00:00Z',latest_redemption:null};
 const q={quote_id:'quote-one',quote_hash:'a'.repeat(64),check_in:'2026-10-01',check_out:'2026-10-03',new_value_minor:12000,credit_value_minor:10000,applied_minor:10000,amount_due_minor:2000,forfeited_difference_minor:0,validity_days:365,currency:'CNY'};
 const dialog={querySelector:()=>({checked})};
 const window={GOBooking:{traveler:async()=>traveler,dialog:async(...args)=>{dialogs.push(args);return null}}};
 vm.runInNewContext(fs.readFileSync('frontend/consumer/catalog-credit.js','utf8'),{window,crypto:{randomUUID:()=> 'stable-key'},Date,Map,Error});
 const ctx={api:async(path,options)=>{if(!options)return c;posts.push({path,options,body:JSON.parse(options.body)});if(path.endsWith('redemption-quote')||path.endsWith('stay-credit-quote'))return q;if(path.endsWith('/consents'))return {consent_id:'selected-guest-consent'};if(fail)throw Error('网络中断');return {stay_credit_id:c.stay_credit_id}},
   money:(amount,currency)=>currency+' '+(amount/100).toFixed(2),toast:()=>{},render:v=>html=v,onBack:()=>{},onOrder:()=>{},
   container:{querySelector(selector){if(!html.includes('id="'+selector.slice(1)+'"'))return null;if(!buttons.has(selector))buttons.set(selector,{disabled:false});return buttons.get(selector)},querySelectorAll(){return []}}};
 return {ui:window.GOCatalogCredit,window,ctx,c,q,posts,dialogs,dialog,buttons,set checked(v){checked=v},set traveler(v){traveler=v},set fail(v){fail=v},get html(){return html}};
}

test('credit conversion waits for explicit quoted consent and does not claim an unknown cancellation succeeded',async()=>{
 const f=fixture();await f.ui.convert(f.ctx,{order_id:'order-one'});
 assert.equal(f.posts.length,1);assert.match(f.dialogs[0][1],/取消确认后/);
 f.checked=false;await assert.rejects(async()=>f.dialogs[0][3](f.dialog),/请先确认/);assert.equal(f.posts.length,1);
 const html=f.ui.phaseActions({status:'UNKNOWN_CANCEL'},null);assert.match(html,/额度暂不可用/);assert.equal(html.includes('已激活'),false);
});

test('canceling traveler selection sends no redemption or automatic identity',async()=>{
 const f=fixture();f.traveler=null;
 assert.equal(await f.ui.quoteRedemption(f.ctx,f.c,'2026-10-01','2026-10-03'),null);
 assert.equal(f.posts.length,1);assert.equal(f.dialogs.length,0);
});

test('redemption network retry binds the same quote and explicitly selected traveler',async()=>{
 const f=fixture();await f.ui.quoteRedemption(f.ctx,f.c,'2026-10-01','2026-10-03');
 const accept=f.dialogs[0][3];f.fail=true;await assert.rejects(()=>accept(f.dialog),/网络/);
 f.fail=false;await accept(f.dialog);
 const requests=f.posts.filter(x=>x.path.endsWith('/redeem'));assert.equal(requests.length,2);
 assert.equal(requests[0].options.headers['Idempotency-Key'],requests[1].options.headers['Idempotency-Key']);
 assert.deepEqual(requests[0].body,{redemption_quote_id:'quote-one',quote_hash:'a'.repeat(64),confirmed:true,traveler_id:'actual-traveler',consent_id:'selected-guest-consent',payment_method_token:'pm_success'});
});

test('unknown booking and pending refund remain distinct from completed credit restoration',()=>{
 const f=fixture();const unknown=f.ui.phaseActions(f.c,{status:'UNKNOWN_BOOK'});
 assert.match(unknown,/核对预订结果/);assert.equal(unknown.includes('确认兑换'),false);
 const pending=f.ui.phaseActions(f.c,{status:'CANCEL_REFUND_PENDING',customer_cancellation:{}});
 assert.match(pending,/退款处理中/);assert.equal(pending.includes('已分别处理'),false);
});

test('canceling a supplementary payment dialog re-enables the action',async()=>{
 const f=fixture();f.c.latest_redemption={order_id:'redemption-one',status:'CAPTURE_PENDING',amount_due_minor:2000,quote_hash:'a'.repeat(64)};
 await f.ui.open(f.ctx,'credit-one');const button=f.buttons.get('#ccRetryPayment');
 await button.onclick();assert.equal(button.disabled,false);assert.equal(f.posts.length,0);
});

test('conversion separates prior cash refunds and forfeiture from retained credit',async()=>{
 const f=fixture();f.q.credit_value_minor=1410000;
 f.q.cash_change_forfeiture={gross_paid_minor:1453200,prior_refund_minor:0,excluded_minor:43200,retained_minor:1410000,
   accepted_changes:[{operation_id:'private-audit-reference'}],evidence_hash:'private-hash'};
 await f.ui.convert(f.ctx,{order_id:'order-one'});
 const html=f.dialogs[0][1];
 for(const text of ['CNY 14532.00','CNY 432.00','CNY 14100.00','已作废差额未计入住宿额度','以后兑换、取消或退款都不会恢复'])assert.ok(html.includes(text),text);
 assert.ok(!html.includes('private-audit-reference'));assert.ok(!html.includes('private-hash'));
});

test('forfeiture conversion confirmation stays bound to the displayed quote after source object changes',async()=>{
 const f=fixture();await f.ui.convert(f.ctx,{order_id:'order-one'});
 f.q.quote_hash='b'.repeat(64);f.q.credit_value_minor=999999;
 await f.dialogs[0][3](f.dialog);
 const sent=f.posts.find(x=>x.path.endsWith('convert-to-stay-credit'));
 assert.equal(sent.body.quote_hash,'a'.repeat(64));assert.equal(sent.body.confirmed,true);
});

test('credit detail keeps original excluded value visible after redemption changes',async()=>{
 const f=fixture();f.c.cash_change_forfeiture={gross_paid_minor:1453200,prior_refund_minor:0,excluded_minor:43200,retained_minor:1410000};
 await f.ui.open(f.ctx,'credit-one');
 assert.ok(f.html.includes('原订单价值如何保留'));assert.ok(f.html.includes('CNY 432.00'));
});

test('historical credit without a forfeiture breakdown never renders invalid amounts',async()=>{
 const f=fixture();
 for(const absent of [null,{},undefined]){
  f.c.cash_change_forfeiture=absent;await f.ui.open(f.ctx,'credit-one');
  assert.ok(!f.html.includes('NaN'));assert.ok(!f.html.includes('原订单价值如何保留'));
 }
});
