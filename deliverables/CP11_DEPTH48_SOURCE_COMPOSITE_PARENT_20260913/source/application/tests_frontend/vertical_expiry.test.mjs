import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('frontend/consumer/app.js','utf8');
const context={safe:x=>String(x).replaceAll('<','&lt;'),Date,Number};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function paymentDeadlineText(')),context);
test('new unpaid reservation displays its frozen UTC deadline',()=>{
 const o={status:'PAYMENT_PENDING',unpaid_reservation_state:'OPEN',payment_deadline_ms:Date.parse('2026-09-09T10:15:00Z')};
 assert.match(context.paymentDeadlineText(o),/2026-09-09 10:15:00 UTC/);
 assert.match(context.paymentDeadlineText(o),/未开始支付/);
 assert.match(context.paymentDeadlineHtml(o),/role="status"/);
});
test('legacy orders never receive a fabricated deadline',()=>{
 assert.equal(context.paymentDeadlineHtml({status:'PAYMENT_PENDING'}),'');
 for(const value of [null,'<img>',NaN,Infinity,-1,8640000000000001]){
  assert.equal(context.paymentDeadlineHtml({status:'PAYMENT_PENDING',unpaid_reservation_state:'OPEN',payment_deadline_ms:value}),'');
 }
});
test('expiry display relies on persisted server state instead of browser clock',()=>{
 assert.match(context.paymentDeadlineText({status:'PAYMENT_PENDING',unpaid_reservation_state:'OPEN',payment_deadline_ms:1}),/请在/);
 assert.match(context.paymentDeadlineText({status:'CANCELLED',unpaid_reservation_state:'EXPIRED'}),/占位已释放/);
});
test('started and uncertain payment keeps its reservation message',()=>{
 const message=context.paymentDeadlineText({status:'PAYMENT_PENDING',unpaid_reservation_state:'PAYMENT_STARTED',payment_deadline_ms:1});
 assert.match(message,/占位继续保留/);assert.doesNotMatch(message,/占位已释放/);
});
