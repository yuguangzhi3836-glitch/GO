import test from 'node:test';
import assert from 'node:assert/strict';
import {mobilityInstant,mobilityDefaults,rideSearchInput,rentalSearchInput} from '../../../go/application/mobile/go-app/src/domain/mobilitySearchInput.ts';
test('maximum supported offsets are explicit epoch conversions',()=>{
 assert.equal(new Date(mobilityInstant('2032-02-29','00:00','+14:00')).toISOString(),'2032-02-28T10:00:00.000Z');
 assert.equal(new Date(mobilityInstant('2032-02-29','00:00','-12:00')).toISOString(),'2032-02-29T12:00:00.000Z');
});
test('same-day pickup and return compare absolute time, not lexical clock',()=>{
 const now=Date.parse('2032-02-28T00:00:00Z');
 const d={...mobilityDefaults(now),pickup:'A',dropoff:'B',pickupDate:'2032-02-29',pickupTime:'00:00',pickupOffset:'+14:00',returnDate:'2032-02-29',returnTime:'00:00',returnOffset:'-12:00'};
 const result=rentalSearchInput(d,now);assert.equal(Date.parse(result.return_at)-Date.parse(result.pickup_at),26*3600000);
 assert.throws(()=>rentalSearchInput({...d,pickupOffset:'-12:00',returnOffset:'+14:00'},now));
});
test('clock unavailable cannot create payload',()=>assert.throws(()=>rideSearchInput({...mobilityDefaults(),pickup:'A',dropoff:'B'},NaN)));
test('out-of-range UTC year rejected even with valid local date',()=>assert.throws(()=>mobilityInstant('9999-12-31','23:59','-12:00')));
