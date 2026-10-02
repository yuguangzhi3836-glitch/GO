import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const wrapper=fs.readFileSync('frontend/consumer/rental-operations.js','utf8');
function setup(){
 const calls=[];let mounted,previous=0;
 const context={window:{addEventListener(){},GORentalOperations:{render:x=>{mounted=x;}}},state:{rentalOrder:{order_id:'rental-1'}},renderMobilityOrder:()=>{previous++},document:{createElement:()=>({dataset:{}}),querySelector:()=>({append(){}})},api:async(...args)=>{calls.push(args);return {state:'ok'};}};
 vm.runInNewContext(wrapper,context);context.renderMobilityOrder('RENTAL');
 return {context,calls,mounted,previous};
}
test('consumer adapter serializes shared object exactly once and keeps headers',async()=>{
 const s=setup();const body={expected_version:2,statement:'核对证据',award_minor:0};
 await s.mounted.request('/action',{method:'POST',headers:{'Idempotency-Key':'fixed'},body});
 assert.equal(typeof s.calls[0][1].body,'string');assert.deepEqual(JSON.parse(s.calls[0][1].body),body);
 assert.equal(s.calls[0][1].headers['Idempotency-Key'],'fixed');
});
test('consumer adapter leaves reads bodyless and does not replace other vertical views',async()=>{
 const s=setup();await s.mounted.request('/read');assert.equal(s.calls[0][1],undefined);
 assert.equal(s.mounted.orderId,'rental-1');s.context.renderMobilityOrder('RIDE');
 assert.equal(s.calls.length,1);
});
test('shared widget follows admin ApiClient object-body contract',()=>{
 const source=fs.readFileSync('frontend/shared/rental-operations.js','utf8');
 assert.match(source,/body:op\.body/);assert.doesNotMatch(source,/body:JSON\.stringify\(op\.body\)/);
});
