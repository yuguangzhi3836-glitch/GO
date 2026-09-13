import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {cashTripLines} from '../mobile/go-app/src/domain/tripFacts.ts';

const cash={action:'CHANGE',state:'CAPTURE_PENDING',check_in:'2026-10-01',check_out:'2026-10-05',
  requested_check_in:'2026-11-01',requested_check_out:'2026-11-05',amount_paid_minor:0,
  gross_paid_minor:1443200,refunded_minor:0,net_paid_minor:1443200,currency:'CNY'};
const item={vertical:'HOTEL',title:'订单',order_id:'hotel_43',total_amount_minor:1443200,
  navigation:{kind:'HOTEL_CATALOG',order_id:'hotel_43'},cash_after_sales:cash};
test('web trip keeps original and requested dates separate while supplement is pending',()=>{
  const context={window:{}};vm.runInNewContext(fs.readFileSync('frontend/consumer/trip-navigation.js','utf8'),context);
  const html=context.window.GOTrips.cards([item],x=>x,n=>String(n));
  assert.match(html,/原始下单金额/);assert.match(html,/补款待完成/);assert.match(html,/申请入住日期/);
  assert.match(html,/入住日期<\/span><b>2026-10-01/);assert.match(html,/本次改期已补款<\/span><b>0/);
  const changed={...cash,state:'COMPLETED',check_in:cash.requested_check_in,amount_paid_minor:90000,gross_paid_minor:1533200};
  const after=context.window.GOTrips.cards([{...item,cash_after_sales:changed}],x=>x,n=>String(n));
  assert.doesNotMatch(after,/申请入住日期/);assert.match(after,/累计实付（含补款）<\/span><b>1533200/);
  const hostile=context.window.GOTrips.cards([{...item,cash_after_sales:{...changed,check_in:'<img src=x>'}}],x=>x,n=>String(n));
  assert.doesNotMatch(hostile,/<img/);assert.match(hostile,/&lt;img/);
});
test('native trip shows pending money honestly and completed refund total',()=>{
  assert.deepEqual(cashTripLines(null),[]);
  const pending=cashTripLines(cash).join('\n');
  assert.match(pending,/2026-10-01 → 2026-10-05/);assert.match(pending,/申请日期：2026-11-01/);
  assert.match(pending,/本次改期已补款：CNY 0.00/);
  const refunded=cashTripLines({...cash,action:'CANCEL',state:'COMPLETED',gross_paid_minor:1583200,refunded_minor:1583200,net_paid_minor:0}).join('\n');
  assert.match(refunded,/累计已退：CNY 15832.00/);assert.doesNotMatch(refunded,/申请日期|本次改期已补款/);
});
test('supplier workbench displays the same cumulative payment summary',()=>{
  const app=fs.readFileSync('frontend/shared/app.js','utf8');
  const context={money:(n,c)=>`${c} ${n}`,supplierObjectCard:(title,facts)=>({title,facts})};
  vm.createContext(context);
  vm.runInContext(app.slice(app.indexOf('function cashAfterSalesCard('),app.indexOf('async function orderWorkbench(')),context);
  assert.equal(context.cashAfterSalesCard(null),'');
  const card=context.cashAfterSalesCard(cash);
  assert.equal(card.facts['累计实付（含补款）'],'CNY 1443200');
  assert.equal(card.facts['申请入住日期'],'2026-11-01');
  assert.match(card.facts['进度'],/补款待完成/);
});
