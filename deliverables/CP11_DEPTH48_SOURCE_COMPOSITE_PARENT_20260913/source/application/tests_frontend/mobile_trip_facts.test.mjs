import test from 'node:test';
import assert from 'node:assert/strict';
import {tripRoute,httpsLink,flightCells,loadMobility} from '../mobile/go-app/src/domain/tripFacts.ts';

test('native navigation binds all six verticals to an owned canonical identity',()=>{
  const expected={HOTEL_CATALOG:'OrderDetail',FLIGHT:'FlightTripDetail',RAIL:'RailTripDetail',RIDE:'MobilityTripDetail',RENTAL:'MobilityTripDetail',ATTRACTION:'AttractionTripDetail'};
  for(const [kind,screen] of Object.entries(expected)) {
    assert.deepEqual(tripRoute({order_id:'owned29',vertical:kind==='HOTEL_CATALOG'?'HOTEL':kind,navigation:{kind,order_id:'owned29'}}),
      {screen,params:{orderId:'owned29',vertical:kind==='HOTEL_CATALOG'?'HOTEL':kind}});
  }
  for(const kind of ['__proto__','constructor','UNKNOWN'])assert.equal(tripRoute({order_id:'owned29',vertical:'HOTEL',navigation:{kind,order_id:'owned29'}}),null);
  assert.equal(tripRoute({order_id:'other',vertical:'FLIGHT',navigation:{kind:'FLIGHT',order_id:'owned29'}}),null);
  assert.equal(tripRoute({order_id:'owned29',vertical:'RAIL',navigation:{kind:'FLIGHT',order_id:'owned29'}}),null);
});
const order={order_id:'flight29',itinerary:[{origin:'PVG'},{origin:'NRT'}],passengers:[{full_name:'TEST A'},{full_name:'TEST B'}]};
const fact=(leg,passenger)=>({leg_index:leg,passenger_index:passenger,state:'BOARDING_PASS_AVAILABLE',fact_id:`f${leg}${passenger}`,observed_ms:900,expires_ms:2000,
  official_check_in_url:'https://airline.example/checkin',boarding_pass_reference:`https://airline.example/pass/${leg}/${passenger}`});
test('native check-in renders each passenger and leg independently',()=>{
  const result={flight_order_id:'flight29',items:[fact(0,0),fact(0,1),fact(1,0),{...fact(1,1),state:'CHECK_IN_NOT_OPEN'}]};
  const cells=flightCells(order,result,1000);
  assert.equal(cells.length,4);assert.equal(new Set(cells.slice(0,3).map(x=>x.passUrl)).size,3);
  assert.equal(cells[3].state,'CHECK_IN_NOT_OPEN');assert.equal(cells[3].passUrl,null);
});
test('missing, stale, duplicate, future or wrong-order check-in evidence is unverified',()=>{
  for(const result of [null,{flight_order_id:'wrong',items:[fact(0,0)]},
    {flight_order_id:'flight29',items:[fact(0,0),fact(0,0)]},
    {flight_order_id:'flight29',items:[{...fact(0,0),expires_ms:1000}]},
    {flight_order_id:'flight29',items:[{...fact(0,0),observed_ms:1500}]},
    {flight_order_id:'flight29',items:[{...fact(0,0),fact_id:null}]}]) {
    const cells=flightCells(order,result,1000);
    assert.ok(cells.every(x=>x.state==='CHECK_IN_UNVERIFIED'&&!x.officialUrl&&!x.passUrl));
  }
});
test('only safe HTTPS links are offered by native travel facts',()=>{
  for(const url of ['javascript:alert(1)','http://airline.example','https://u:p@airline.example','https://airline.example:8443/p','https://airline.example/ space','https://airline.example\\@evil.example'])assert.equal(httpsLink(url),null);
  assert.equal(httpsLink('https://airline.example/checkin'),'https://airline.example/checkin');
});
test('native rental details never request ride tracking',async()=>{
  const calls=[];const o={order_id:'rental29',vertical:'RENTAL',pickup_location:'NRT'};
  assert.deepEqual(await loadMobility('rental29',async path=>{calls.push(path);return {data:o}}),{order:o,tracking:null,trackingError:''});
  assert.deepEqual(calls,['/v1/mobility/orders/rental29']);
});
test('ride tracking failure cannot hide the existing ride order',async()=>{
  const o={order_id:'ride29',vertical:'RIDE',pickup_at:'2026-09-23T10:00:00'};
  const result=await loadMobility('ride29',async path=>{if(path.endsWith('flight-tracking'))throw Error('unavailable');return {data:o}});
  assert.equal(result.order,o);assert.equal(result.tracking,null);assert.ok(result.trackingError);
});
test('tracking and order identity mismatches cannot render another order',async()=>{
  await assert.rejects(loadMobility('ride29',async()=>({data:{order_id:'wrong',vertical:'RIDE'}})),/IDENTITY_MISMATCH/);
  const result=await loadMobility('ride29',async path=>({data:path.endsWith('flight-tracking')?{order_id:'wrong'}:{order_id:'ride29',vertical:'RIDE'}}));
  assert.equal(result.tracking,null);assert.ok(result.trackingError);
});
