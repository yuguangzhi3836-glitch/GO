import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {flightCells} from '../../mobile/go-app/src/domain/tripFacts.ts';
const sandbox={window:{},renderFlightOrder(){},renderMobilityOrder(){},URL,Date};
vm.runInNewContext(fs.readFileSync(new URL('../../frontend/consumer/travel-status.js',import.meta.url),'utf8'),sandbox);
const now=Date.now();
const order={order_id:'isolated-checkin',status:'TICKETED',itinerary:[{origin:'SHA',destination:'PEK',departure_date:'2026-10-01'}],passengers:[{full_name:'A'},{full_name:'B'}],coupons:[
 {coupon_id:'A-1',leg_index:0,passenger_index:0,state:'REFUNDED',usable:false,leg:{origin:'SHA',destination:'PEK',departure_date:'2026-10-02'}},
 {coupon_id:'B-1',leg_index:0,passenger_index:1,state:'ISSUED',usable:true,leg:{origin:'SHA',destination:'PEK',departure_date:'2026-10-01'}}]};
const facts={flight_order_id:order.order_id,items:[0,1].map(i=>({leg_index:0,passenger_index:i,fact_id:'isolated-'+i,state:'BOARDING_PASS_AVAILABLE',observed_ms:now-1000,expires_ms:now+100000,official_check_in_url:'https://example.test/checkin',boarding_pass_reference:'https://example.test/pass'}))};
const html=sandbox.window.GOTravelStatus.flightHTML(order,facts);
assert.ok(html.includes('2026-10-02 · A'));assert.ok(html.includes('该票券已退票，不可值机'));
assert.equal((html.match(/查看这位乘机人的登机牌/g)||[]).length,1);
const cells=flightCells(order,facts,now);assert.equal(cells[0].state,'COUPON_REFUNDED');assert.equal(cells[0].officialUrl,null);assert.equal(cells[0].passUrl,null);assert.equal(cells[0].leg.departure_date,'2026-10-02');assert.ok(cells[1].passUrl);
assert.ok(!sandbox.window.GOTravelStatus.flightHTML(order,{...facts,flight_order_id:'foreign'}).includes('<a '));
const expired={...facts,items:facts.items.map(x=>({...x,expires_ms:now-1}))};
assert.ok(!sandbox.window.GOTravelStatus.flightHTML(order,expired).includes('<a '));
assert.ok(flightCells(order,expired,now).every(x=>x.passUrl===null));
console.log('PASS: web/native coupon date, refunded entitlement, foreign and expired check-in facts');
