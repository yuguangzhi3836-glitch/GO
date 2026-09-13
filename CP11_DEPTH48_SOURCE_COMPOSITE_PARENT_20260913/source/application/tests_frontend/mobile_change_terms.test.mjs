import test from 'node:test';
import assert from 'node:assert/strict';
import {changeTerms} from '../mobile/go-app/src/domain/changeTerms.ts';
const hotel={currency:'CNY',old_value_minor:10000,new_value_minor:8000,fare_difference_minor:0,change_fee_minor:0,amount_due_minor:0,change_policy:'GO_HOTEL_FREE_CHANGE_365D_V1',change_validity_days:365,change_valid_until:'2027-09-12T00:00:00Z',lower_price_difference_minor:2000,lower_price_no_refund:true,lower_price_rule:'FORFEIT_NO_REFUND_NO_FUTURE_OFFSET'};
test('hotel lower price discloses loss, no fee and original fixed deadline',()=>{
 const rows=changeTerms('HOTEL',hotel);assert.equal(rows.find(x=>x.label==='降价差额（不退还）').minor,2000);assert.match(rows.find(x=>x.label==='改期规则').value,/改期免手续费/);assert.match(rows.find(x=>x.label==='有效期').value,/不顺延/);assert.ok(!rows.some(x=>x.label==='改签手续费'));
});
test('missing or inconsistent hotel financial terms are not confirmable',()=>{
 for(const patch of [{lower_price_rule:undefined},{lower_price_no_refund:false},{lower_price_difference_minor:0},{amount_due_minor:100},{change_fee_minor:'100'},{change_fee_minor:100},{change_validity_days:366},{change_policy:undefined},{change_valid_until:'invalid'},{currency:'USD'},{new_value_minor:NaN}])assert.throws(()=>changeTerms('HOTEL',{...hotel,...patch}),/UNVERIFIED/);
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
