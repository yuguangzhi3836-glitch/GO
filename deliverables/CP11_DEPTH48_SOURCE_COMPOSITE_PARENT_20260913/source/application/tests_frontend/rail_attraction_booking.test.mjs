import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context={window:{},Date};
vm.runInNewContext(fs.readFileSync('frontend/consumer/rail-attraction-booking.js','utf8'),context);
const {createFlow,validateQuote}=context.window.GOPartyBooking;
const rail={offer_id:'rail-1',travel_date:'2026-09-12',train_no:'G7315',seat_class:'SECOND_CLASS',origin_station:'SHA',destination_station:'HZH',inventory_left:18};
const attraction={offer_id:'attr-1',product_name:'ISOLATED EXPERIENCE',available_sessions:['16:00','17:00'],session_time:'16:00',inventory_units:8,ticket_type:'成人票',eligibility:{age:'12+ adult',id_required:true}};
function setup(vertical='RAIL', options={}) {
  const calls=[],texts=[];let time=1000,dialogs=0;
  const offer=vertical==='RAIL'?rail:attraction;
  const q={offer_id:offer.offer_id,prebook_id:'quote-20',terms_hash:'contract-hash',quantity:2,unit_amount_minor:7350,total_amount_minor:14700,currency:'CNY',expires_ms:2000,
    journey:rail,visit_date:'2026-09-12',session_time:'17:00',product_name:attraction.product_name,eligibility:attraction.eligibility,changeable:true,refundable:false,
    change_policy:{allowed:true,fee_minor:500},refund_policy:{allowed:true,fee_minor:800}};
  const deps={now:()=>time,uuid:()=>`key-${calls.length}`,money:a=>`CNY ${a/100}`,
    dialog:async(title,html,button,accept)=>{
      dialogs++;texts.push({title,html,button});if(options.cancel===dialogs)return null;
      return accept({querySelector:selector=>selector==='[data-quote-consent]'?{checked:options.consent!==false}:{value:selector==='#goPartyCount'?'2':'17:00'}});
    },
    travelers:async(v,n)=>{calls.push({step:'travelers',vertical:v,count:n});if(options.expire)time=2500;return options.cancelParty?null:options.ids||['a','b'];},
    post:async(path,body,key)=>{calls.push({step:'post',path,body,key});if(path.endsWith('prebook'))return structuredClone(q);return {order_id:'order-20',total_amount_minor:14700,currency:'CNY',status:'PAYMENT_PENDING'};},
    pay:async(v,o)=>{calls.push({step:'pay',vertical:v,order:o});if(options.payError)throw Error('payment connection unavailable');return null;},
    show:async(v,id)=>{calls.push({step:'show',vertical:v,id});}
  };
  return {flow:createFlow(deps),deps,q,calls,texts,offer,criteria:{visit_date:'2026-09-12'}};
}

test('rail order preserves party, immutable prebook and original total through payment cancellation',async()=>{
  const s=setup();await s.flow('RAIL',s.offer,s.criteria);
  assert.equal(s.calls[0].body.quantity,2);
  const order=s.calls.find(c=>c.path==='/v1/rail/orders');
  assert.deepEqual(JSON.parse(JSON.stringify(order.body)),{prebook_id:'quote-20',traveler_ids:['a','b']});
  assert.match(order.key,/quote-20:a:b/);
  assert.equal(s.calls.find(c=>c.step==='pay').order.total_amount_minor,14700);
  assert.equal(s.calls.at(-1).step,'show');
  assert.match(s.texts[1].html,/CNY 147/);assert.match(s.texts[1].html,/改签手续费 CNY 10/);assert.doesNotMatch(s.texts[1].html,/\[object Object\]/);
});

test('attraction order uses the quoted slot, quantity and prebook and shows eligibility',async()=>{
  const s=setup('ATTRACTION');await s.flow('ATTRACTION',s.offer,s.criteria);
  const order=s.calls.find(c=>c.path==='/v1/attractions/orders');
  assert.equal(order.body.session_time,'17:00');assert.equal(order.body.quantity,2);assert.equal(order.body.prebook_id,'quote-20');
  assert.match(s.texts[1].html,/不可退款/);assert.match(s.texts[1].html,/有效身份证件/);assert.doesNotMatch(s.texts[1].html,/\[object Object\]/);
});

for(const cancel of [1,2])test(`cancelling confirmation step ${cancel} never creates an order or payment`,async()=>{
  const s=setup('ATTRACTION',{cancel});assert.equal(await s.flow('ATTRACTION',s.offer,s.criteria),null);
  assert.equal(s.calls.filter(c=>c.path==='/v1/attractions/orders'||c.step==='pay').length,0);
});

test('cancelled party selection cannot reach order creation',async()=>{
  const s=setup('RAIL',{cancelParty:true});assert.equal(await s.flow('RAIL',s.offer,s.criteria),null);
  assert.equal(s.calls.filter(c=>c.step==='post').length,1);
});

test('quote that expires during traveler selection cannot create or pay an order',async()=>{
  const s=setup('RAIL',{expire:true});await assert.rejects(s.flow('RAIL',s.offer,s.criteria),/过期/);
  assert.equal(s.calls.filter(c=>c.path==='/v1/rail/orders'||c.step==='pay').length,0);
});

test('missing final consent never creates an order',async()=>{
  const s=setup('RAIL',{consent:false});await assert.rejects(s.flow('RAIL',s.offer,s.criteria),/确认预订/);
  assert.equal(s.calls.filter(c=>c.path==='/v1/rail/orders').length,0);
});

test('different people are required for every quoted place',async()=>{
  const s=setup('ATTRACTION',{ids:['a','a']});await assert.rejects(s.flow('ATTRACTION',s.offer,s.criteria),/人数/);
  assert.equal(s.calls.filter(c=>c.path==='/v1/attractions/orders').length,0);
});

test('an uncertain payment still opens the existing order for recovery',async()=>{
  const s=setup('RAIL',{payError:true});await assert.rejects(s.flow('RAIL',s.offer,s.criteria),/connection/);
  assert.equal(s.calls.at(-1).step,'show');assert.equal(s.calls.at(-1).id,'order-20');
});

test('repeated clicks cannot start a second booking while confirmation is open',async()=>{
  const s=setup();let release;const deps={...s.deps,dialog:()=>new Promise(resolve=>{release=resolve;})};
  const flow=createFlow(deps),first=flow('RAIL',s.offer,s.criteria);
  assert.equal(await flow('ATTRACTION',attraction,s.criteria),null);release(null);assert.equal(await first,null);assert.equal(s.calls.length,0);
});

test('mismatched total, journey or slot is refused before any traveler consent',()=>{
  const s=setup();const selection={quantity:2};
  assert.throws(()=>validateQuote({...s.q,total_amount_minor:7350},'RAIL',rail,selection,1000),/变化/);
  assert.throws(()=>validateQuote({...s.q,journey:{...rail,train_no:'OTHER'}},'RAIL',rail,selection,1000),/车次/);
  assert.throws(()=>validateQuote({...s.q,offer_id:'attr-1'},'ATTRACTION',attraction,{quantity:2,visit_date:'2026-09-12',session_time:'03:17'},1000),/场次/);
});
