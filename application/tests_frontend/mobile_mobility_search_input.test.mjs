import test from 'node:test';
import assert from 'node:assert/strict';
import {mobilityDefaults,mobilityInstant,rideSearchInput,rentalSearchInput} from '../mobile/go-app/src/domain/mobilitySearchInput.ts';
const now=Date.parse('2026-09-25T15:59:31Z');
const filled=()=>({...mobilityDefaults(now),pickup:'  新加坡樟宜机场 ',dropoff:' 市中心 '});
test('defaults move with now, cross midnight, and leave places editable',()=>{
  const d=mobilityDefaults(now);assert.equal(d.pickup,'');assert.equal(d.dropoff,'');
  assert.equal(d.pickupDate,'2026-09-27');assert.equal(d.pickupTime,'00:00');assert.equal(d.returnDate,'2026-09-30');
  assert.ok(mobilityInstant(d.pickupDate,d.pickupTime,d.pickupOffset)>now);
  assert.notEqual(mobilityDefaults(now+86400000).pickupDate,d.pickupDate);
});
test('ride sends selected trimmed places and UTC timestamp',()=>{
  assert.deepEqual(rideSearchInput(filled(),now),{pickup:'新加坡樟宜机场',dropoff:'市中心',pickup_at:'2026-09-26T16:00:00.000Z',currency:'CNY'});
});
test('editable +09 and -04 zones map the same wall time to different UTC instants',()=>{
  const d={...filled(),pickupDate:'2026-09-27',pickupTime:'10:30'};
  assert.equal(rideSearchInput({...d,pickupOffset:'+09:00'},now).pickup_at,'2026-09-27T01:30:00.000Z');
  assert.equal(rideSearchInput({...d,pickupOffset:'-04:00'},now).pickup_at,'2026-09-27T14:30:00.000Z');
});
for(const [date,time] of [['2026-02-29','10:00'],['2026-04-31','10:00'],['2026-13-01','10:00'],['2026-09-00','10:00'],['2026-09-26','24:00'],['2026-09-26','10:60'],['2026/09/26','10:00'],['2026-09-26','9:30']]){
  test(`reject invalid calendar/time ${date} ${time}`,()=>assert.throws(()=>mobilityInstant(date,time,'+08:00')));
}
test('leap date accepted and offset crosses UTC day',()=>assert.equal(new Date(mobilityInstant('2028-02-29','00:30','+08:00')).toISOString(),'2028-02-28T16:30:00.000Z'));
for(const offset of ['UTC+8','+8:00','+14:01','-12:01','+08:60','NaN']){
  test(`reject invalid offset ${offset}`,()=>assert.throws(()=>mobilityInstant('2026-09-26','10:00',offset)));
}
test('stale form rejects past or current pickup at submission',()=>{
  const d=filled(),at=mobilityInstant(d.pickupDate,d.pickupTime,d.pickupOffset);
  assert.throws(()=>rideSearchInput(d,at));assert.throws(()=>rentalSearchInput(d,at+1));
});
test('rental earlier local return date may be later in UTC',()=>{
  const result=rentalSearchInput({...filled(),pickupDate:'2026-09-27',pickupTime:'10:00',pickupOffset:'+14:00',returnDate:'2026-09-26',returnTime:'23:00',returnOffset:'-10:00'},now);
  assert.equal(result.pickup_at,'2026-09-26T20:00:00.000Z');assert.equal(result.return_at,'2026-09-27T09:00:00.000Z');
  assert.equal(result.pickup_location,'新加坡樟宜机场');assert.equal(result.return_location,'市中心');
});
test('later local clock rejected when earlier in UTC',()=>assert.throws(()=>rentalSearchInput({...filled(),pickupDate:'2026-09-27',pickupTime:'10:00',pickupOffset:'-05:00',returnDate:'2026-09-27',returnTime:'11:00',returnOffset:'+08:00'},now),/晚于取车时间/));
test('equal instants with different offsets rejected',()=>assert.throws(()=>rentalSearchInput({...filled(),pickupDate:'2026-09-27',pickupTime:'10:00',pickupOffset:'+08:00',returnDate:'2026-09-26',returnTime:'22:00',returnOffset:'-04:00'},now),/晚于取车时间/));
test('locations required and bounded without demo fallback',()=>{
  for(const fn of [rideSearchInput,rentalSearchInput]){
    assert.throws(()=>fn({...filled(),pickup:'  '},now));assert.throws(()=>fn({...filled(),dropoff:'x'.repeat(201)},now));
  }
});
