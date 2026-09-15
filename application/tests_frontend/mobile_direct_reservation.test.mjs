import test from 'node:test';
import assert from 'node:assert/strict';
import {tripRoute,loadDirectReservation} from '../mobile/go-app/src/domain/tripFacts.ts';
test('Direct navigation preserves the owned reservation identity',()=>{
 assert.deepEqual(tripRoute({vertical:'HOTEL',order_id:'hdr31',navigation:{kind:'HOTEL_DIRECT',order_id:'hdr31'}}),{screen:'DirectReservationDetail',params:{orderId:'hdr31',vertical:'HOTEL'}});
 assert.equal(tripRoute({vertical:'HOTEL',order_id:'hdr31',navigation:{kind:'HOTEL_DIRECT',order_id:'other'}}),null);
});
test('Direct details read only the canonical reservation and matching events',async()=>{
 const calls=[];
 const d=await loadDirectReservation('hdr31',async path=>{calls.push(path);return {data:{reservation:{hosted_reservation_id:'hdr31',reservation_state:'PENDING_HOTEL_CONFIRMATION',payment_state:'NO_CHARGE',amount_minor:10000,currency:'CNY',guest_contact:'PRIVATE'},events:[{hosted_reservation_id:'other',event_type:'LEAK'},{hosted_reservation_id:'hdr31',event_type:'REQUESTED',payload_json:{secret:'PRIVATE'}}]}};});
 assert.deepEqual(calls,['/v1/direct/reservations/hdr31']);assert.equal(d.state,'PENDING_HOTEL_CONFIRMATION');assert.equal(d.events.length,1);assert.ok(!JSON.stringify(d).includes('PRIVATE'));assert.ok(!JSON.stringify(d).includes('LEAK'));
});
test('Direct mismatched or missing records cannot display confirmation',async()=>{
 for(const data of [null,{reservation:{hosted_reservation_id:'other'}}])await assert.rejects(loadDirectReservation('hdr31',async()=>({data})),/IDENTITY/);
 await assert.rejects(loadDirectReservation('../other',async()=>{throw Error('must not request');}),/ID_REQUIRED/);
});
