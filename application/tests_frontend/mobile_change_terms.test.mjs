import test from 'node:test';
import assert from 'node:assert/strict';
import {changeTerms} from '../mobile/go-app/src/domain/changeTerms.ts';
const hotel={currency:'CNY',old_value_minor:10000,new_value_minor:8000,fare_difference_minor:0,change_fee_minor:100,amount_due_minor:100,lower_price_difference_minor:2000,lower_price_no_refund:true,lower_price_rule:'FORFEIT_NO_REFUND_NO_FUTURE_OFFSET'};
test('hotel lower price still discloses the nonrefundable loss and separate fee',()=>{
 const rows=changeTerms('HOTEL',hotel);assert.equal(rows.find(x=>x.label==='降价差额（不退还）').minor,2000);assert.match(rows.find(x=>x.label==='降价条款').value,/不能抵扣/);assert.equal(rows.at(-1).minor,100);
});
test('missing or inconsistent hotel financial terms are not confirmable',()=>{
 for(const patch of [{lower_price_rule:undefined},{lower_price_no_refund:false},{lower_price_difference_minor:0},{amount_due_minor:0},{change_fee_minor:'100'},{currency:'USD'},{new_value_minor:NaN}])assert.throws(()=>changeTerms('HOTEL',{...hotel,...patch}),/UNVERIFIED/);
});
test('flight and rail disclose transport identity and reject inconsistent fee sums',()=>{
 for(const v of ['FLIGHT','RAIL']){
  const q={currency:'CNY',new_flight_number:'GO720',new_train_no:'G7319',new_seat_class:'SECOND',fare_difference_minor:200,change_fee_minor:50,total_due_minor:250};
  assert.ok(changeTerms(v,q).some(x=>x.value===(v==='FLIGHT'?'GO720':'G7319')));
  assert.throws(()=>changeTerms(v,{...q,total_due_minor:200}),/UNVERIFIED/);
  assert.throws(()=>changeTerms(v,{...q,[v==='FLIGHT'?'new_flight_number':'new_seat_class']:''}),/UNVERIFIED/);
 }
});
test('rental lower cost specifies original payment and validates the rate calculation',()=>{
 const q={currency:'CNY',old_amount_minor:3000,new_amount_minor:2000,difference_minor:-1000,daily_rate_minor:1000,rental_days:2,change_fee_minor:0,refund_to:'ORIGINAL_PAYMENT_METHOD'};
 assert.match(changeTerms('RENTAL',q).find(x=>x.label==='差额结算').value,/原支付方式/);
 for(const patch of [{difference_minor:1000},{rental_days:3},{refund_to:'CREDIT'},{change_fee_minor:10}])assert.throws(()=>changeTerms('RENTAL',{...q,...patch}),/UNVERIFIED/);
});
test('attraction free change never silently accepts a newly introduced charge',()=>{
 assert.ok(changeTerms('ATTRACTION',{currency:'CNY',change_fee_minor:0,total_due_minor:0}));
 assert.throws(()=>changeTerms('ATTRACTION',{currency:'CNY',change_fee_minor:100,total_due_minor:100}),/UNVERIFIED/);
});
