import test from 'node:test';
import assert from 'node:assert/strict';
import {createStayCreditActions,validateCreditQuote} from '../mobile/go-app/src/domain/stayCreditActions.ts';
function fixture({lost=false,reject=false}={}){
 const calls=[];const t=Date.now();
 const q={order_id:'order47',quote_id:'quote47',quote_hash:'a'.repeat(64),credit_value_minor:12000,currency:'CNY',scope:'PROPERTY_ONLY',credit_validity_basis:'ORIGINAL_ORDER_365D_CAP',credit_original_created_at:new Date(t-86400000).toISOString(),credit_expires_at:new Date(t+7*86400000).toISOString(),expires_at:new Date(t+600000).toISOString()};
 const order={order_id:'order47',currency:'CNY',status:'CONFIRMED'};
 const request=async(path,init={})=>{calls.push({path,...init});if(path.endsWith('/stay-credit-quote'))return {data:q};if(path.endsWith('/convert-to-stay-credit')){if(reject)throw Object.assign(Error('STALE'),{status:409});order.status='CONVERTED_TO_CREDIT';if(lost)throw Error('response lost');return {data:{status:'UNKNOWN_CANCEL'}};}return {data:{order:{...order}}};};
 return {q,order,calls,request};
}
test('native conversion sends exactly the displayed quote and explicit consent',async()=>{
 const f=fixture(),a=createStayCreditActions(f.request),q=await a.quote('order47');f.q.quote_hash='b'.repeat(64);
 await assert.rejects(()=>a.convert('order47',q,false),/CONSENT/);
 const result=await a.convert('order47',q,true),sent=f.calls.filter(c=>c.path.endsWith('/convert-to-stay-credit'));
 assert.equal(sent.length,1);assert.deepEqual(JSON.parse(sent[0].body),{quote_id:'quote47',quote_hash:'a'.repeat(64),confirmed:true});
 assert.equal(result.order.status,'CONVERTED_TO_CREDIT');assert.equal(f.calls.filter(c=>c.path.endsWith('/stay-credit-quote')).length,1);
});
test('native lost conversion response reads original order without resending cancellation',async()=>{
 const f=fixture({lost:true}),a=createStayCreditActions(f.request),q=await a.quote('order47');
 const result=await a.convert('order47',q,true);assert.equal(result.notice,'CREDIT_RESULT_UNKNOWN');assert.equal(result.order.status,'CONVERTED_TO_CREDIT');
 assert.equal(f.calls.filter(c=>c.path.endsWith('/convert-to-stay-credit')).length,1);
});
test('native stale quote remains rejected and is never silently replaced',async()=>{
 const f=fixture({reject:true}),a=createStayCreditActions(f.request),q=await a.quote('order47');
 await assert.rejects(()=>a.convert('order47',q,true),/STALE/);assert.equal(f.calls.filter(c=>c.path.endsWith('/stay-credit-quote')).length,1);
});
test('native expired, cross-order, wrong-currency or renewed-year quote cannot submit',async()=>{
 const f=fixture();
 for(const patch of [{order_id:'other'},{currency:'USD'},{credit_value_minor:true},{expires_at:'2000-01-01'},{credit_expires_at:'2099-01-01'}])assert.throws(()=>validateCreditQuote('order47','CNY',{...f.q,...patch}));
 const a=createStayCreditActions(f.request,()=>false);await assert.rejects(()=>a.convert('order47',f.q,true),/SESSION/);
 assert.equal(f.calls.length,0);
});
