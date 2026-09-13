import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('frontend/consumer/travel-status.js','utf8');
function setup(){
 const calls=[],options={available:true,sources:[{authority_id:'auth',provider_id:'test provider',label:'已授权',carriers:['MU']}],policy:{delay_protection_free_wait_minutes:30,max_free_wait_minutes:90}};
 const context={window:{},URL,renderFlightOrder(){},renderMobilityOrder(){},toast(){},GOBooking:{dialog:async()=>null},
   api:async(path,opts)=>{calls.push({path,opts});return options},document:{},state:{}};
 vm.runInNewContext(source,context);return {ctx:context,ui:context.window.GOTravelStatus,calls,options};
}
const order={order_id:'f1',itinerary:[{origin:'PVG',destination:'NRT',departure_date:'2026-09-08'}],passengers:[{full_name:'ONE <script>'}]};
test('unverified check-in never exposes links or boarding passes',()=>{
 const s=setup(),html=s.ui.flightHTML(order,{items:[{leg_index:0,passenger_index:0,state:'CHECK_IN_UNVERIFIED',official_check_in_url:'https://airline.example',boarding_pass_reference:'https://airline.example/pass'}]});
 assert.match(html,/等待航空公司信息/);assert.doesNotMatch(html,/<a /);assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
});
test('per-traveler boarding pass appears only for the verified pass state',()=>{
 const s=setup();for(const state of ['CHECKED_IN','CHECK_IN_OPEN','UNKNOWN'])assert.doesNotMatch(s.ui.flightHTML(order,{items:[{leg_index:0,passenger_index:0,state,boarding_pass_reference:'https://airline.example/pass'}]}),/href=/);
 const html=s.ui.flightHTML(order,{items:[{leg_index:0,passenger_index:0,state:'BOARDING_PASS_AVAILABLE',boarding_pass_reference:'https://airline.example/pass'}]});
 assert.match(html,/referrerpolicy="no-referrer"/);assert.match(html,/查看这位乘机人的登机牌/);
});
test('invalid URL schemes and credentials do not become customer links',()=>{
 const s=setup();for(const url of ['javascript:alert(1)','http://airline.example','https://user@airline.example','https://airline.example:8080'])assert.doesNotMatch(s.ui.flightHTML(order,{items:[{leg_index:0,passenger_index:0,state:'BOARDING_PASS_AVAILABLE',boarding_pass_reference:url}]}),/href=/);
});
test('unknown fleet outcome clearly separates confirmed and proposed times',()=>{
 const html=setup().ui.rideHTML({confirmed_pickup_at:'10:00',events:[{status:'UNKNOWN',proposed_pickup_at:'12:00'}]});
 assert.match(html,/已确认接车时间 <strong>10:00/);assert.match(html,/建议接车时间 12:00/);assert.match(html,/正在核对车队结果/);assert.doesNotMatch(html,/车队已确认/);
});
test('cancelled tracking confirmation sends no binding mutation',async()=>{
 const s=setup();await s.ui.configure({order_id:'r1'},{binding:null});assert.equal(s.calls.length,1);assert.equal(s.calls[0].opts,undefined);
});
test('checked consent sends exact displayed revision and server authority, never wait overrides',async()=>{
 const s=setup();s.ctx.GOBooking.dialog=async(title,html,label,accept)=>accept({querySelector(sel){return {checked:true,value:{'[data-source]':'auth','[data-carrier]':'MU','[data-flight]':'MU523','[data-day]':'2026-09-08','[data-airport]':'NRT'}[sel]||''}}});
 await s.ui.configure({order_id:'r1'},{binding:{revision:8,flight_identity:{}}});
 const body=JSON.parse(s.calls[1].opts.body);assert.equal(body.expected_revision,8);assert.equal(body.authority_id,'auth');assert.equal(body.flight_identity.arrival_airport,'NRT');assert.equal(body.delay_protection_enabled,true);
 assert.equal('max_free_wait_minutes' in body,false);assert.equal('supplier_rule_snapshot' in body,false);
});
test('missing consent prevents any tracking write',async()=>{
 const s=setup();s.ctx.GOBooking.dialog=async(a,b,c,accept)=>accept({querySelector(){return {checked:false}}});
 await assert.rejects(()=>s.ui.configure({order_id:'r1'},{binding:null}),/核对并确认/);assert.equal(s.calls.length,1);
});
test('no authorized source does not open an unusable confirmation dialog',async()=>{
 const s=setup();s.options.available=false;let dialogs=0;s.ctx.GOBooking.dialog=async()=>dialogs++;
 assert.equal(await s.ui.configure({order_id:'r1'},{binding:null}),null);assert.equal(dialogs,0);
});
test('waiting protection is conditional and shows the actual event allowance',()=>{
 const html=setup().ui.rideHTML({confirmed_pickup_at:'10:00',binding:{flight_identity:{},tracking_enabled:true,source_current:false,included_wait_minutes:60,delay_protection_enabled:true,delay_protection_max_wait_minutes:90},events:[{status:'CONFIRMED',proposed_pickup_at:'12:00',free_wait_minutes:60}]});
 assert.match(html,/航班来源暂不可用/);assert.match(html,/已验证延误时，保护上限 90 分钟/);assert.match(html,/本次规则内免费等待 60 分钟/);assert.match(html,/该次确认接车时间 12:00/);
});
test('late check-in response cannot populate a detached screen',async()=>{
 const s=setup();let finish;const host={isConnected:true,innerHTML:'',setAttribute(){},append(){}};let created=0;
 s.ctx.document={createElement(){return created++===0?host:{}},querySelector(){return {append(){}}}};
 s.ctx.state.flightOrder=order;s.ctx.api=()=>new Promise(r=>{finish=r});s.ctx.renderFlightOrder();host.isConnected=false;
 finish({items:[{leg_index:0,passenger_index:0,state:'BOARDING_PASS_AVAILABLE',boarding_pass_reference:'https://airline.example/pass'}]});
 await new Promise(r=>setImmediate(r));assert.doesNotMatch(host.innerHTML,/href=/);
});
