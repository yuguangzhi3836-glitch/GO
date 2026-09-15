import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('frontend/consumer/rental-after-sales.js','utf8');
function setup(){
 const calls=[],dialogs=[];let previous=0,reloads=0;
 const order={order_id:'rental-1',pickup_at:'2026-10-01T10:00:00',return_at:'2026-10-04T10:00:00',currency:'CNY'};
 const ctx={state:{rentalOrder:order},GOBooking:{dialog:async(...args)=>{dialogs.push(args);return null}},
   api:async(path,opts)=>{calls.push({path,body:JSON.parse(opts.body)});return {status:'EXECUTED'}},
   mobilityModify:()=>{previous++},renderMobilityOrder:()=>{},mobilityReload:async()=>{reloads++},
   money:(n,c)=>`${c} ${n/100}`,toast:()=>{},document:{}};
 vm.runInNewContext(source,ctx);return {ctx,calls,dialogs,get previous(){return previous},get reloads(){return reloads}};
}
test('cancelling date selection never requests a quote or payment',async()=>{
 const s=setup();await s.ctx.mobilityModify('RENTAL');assert.equal(s.calls.length,0);assert.equal(s.dialogs.length,1);
});
test('ride changes continue to use their separate workflow',async()=>{
 const s=setup();await s.ctx.mobilityModify('RIDE');assert.equal(s.previous,1);assert.equal(s.dialogs.length,0);
});
test('viewing a rental quote does not execute the change',async()=>{
 const s=setup();s.ctx.GOBooking.dialog=async(title,html,label,accept)=>{
   s.dialogs.push(title);if(s.dialogs.length===1)return {quote_id:'q1',difference_minor:-42000,currency:'CNY',new_amount_minor:84000};return null;
 };await s.ctx.mobilityModify('RENTAL');assert.equal(s.calls.length,0);assert.equal(s.dialogs.length,2);
});
test('confirmed refund difference retains its sign and server quote identity',async()=>{
 const s=setup();let count=0;s.ctx.GOBooking.dialog=async(title,html,label,accept)=>{
   if(++count===1)return {quote_id:'q1',difference_minor:-42000,currency:'CNY',new_amount_minor:84000};
   assert.match(html,/原支付退回/);return accept({querySelector:()=>({checked:true})});
 };await s.ctx.mobilityModify('RENTAL');assert.equal(s.calls[0].path,'/v1/mobility/rentals/orders/rental-1/changes/q1');
 assert.deepEqual(s.calls[0].body,{expected_difference_minor:-42000,currency:'CNY',mode:'CONTRACT_SIMULATOR'});assert.equal(s.reloads,1);
});
test('unchecked amount consent blocks executing a displayed quote',async()=>{
 const s=setup();let count=0;s.ctx.GOBooking.dialog=async(title,html,label,accept)=>{
   if(++count===1)return {quote_id:'q1',difference_minor:42000,currency:'CNY'};
   await assert.rejects(()=>accept({querySelector:()=>({checked:false})}),/核对/);return null;
 };await s.ctx.mobilityModify('RENTAL');assert.equal(s.calls.length,0);
});
test('the shared amount formatter preserves cents on confirmation screens',()=>{
 const line=fs.readFileSync('frontend/consumer/app.js','utf8').split('\n').find(x=>x.startsWith('const $='));
 const ctx={document:{querySelector(){}},Intl};vm.runInNewContext(line+'; result=money(101,"CNY");',ctx);
 assert.match(ctx.result,/1\.01/);
});
