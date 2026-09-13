import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const app=fs.readFileSync('frontend/consumer/app.js','utf8');
test('GO Trip shows all states, searches owned rows, opens the filtered order and restores all', async()=>{
  const rows=['PAYMENT_PENDING','CANCELLED','REFUND_PENDING','COMPLETED','REFUNDED','CONFIRMED'].map((status,i)=>({
    order_id:'order_'+i,title:'行程 '+i,vertical:['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION'][i],native_status:status}));
  const nodes={'#app':{},'#tripListLoading':{isConnected:true},'#tripQuery':{value:''},'#allTripOrders':{}};
  let visible=[],buttons=[],opened;
  const context={setVerticalVIMode:()=>{},$:key=>nodes[key],shell:x=>x,bindNav:()=>{},
    api:async path=>{assert.equal(path,'/v1/consumer/unified-trips');return {items:rows}},
    consumerLabel:x=>x,money:x=>x,consumerEmpty:()=>'',openUnifiedTrip:x=>{opened=x},
    window:{GOTrips:{cards:items=>{visible=items;buttons=items.map((_,i)=>({dataset:{goTripIndex:String(i)}}));return 'cards'}}},
    document:{querySelectorAll:()=>buttons}};
  vm.createContext(context);
  vm.runInContext(app.slice(app.indexOf('async function showUnifiedTrips(){'),app.indexOf('async function openUnifiedTrip(')),context);
  await context.showUnifiedTrips();assert.equal(visible.length,6);
  nodes['#tripQuery'].value='order_4';nodes['#tripQuery'].oninput();assert.equal(visible.length,1);
  buttons[0].onclick();assert.equal(opened.order_id,'order_4');
  nodes['#tripQuery'].value='missing';nodes['#tripQuery'].oninput();assert.equal(visible.length,0);
  nodes['#tripQuery'].value='';nodes['#tripQuery'].oninput();assert.equal(visible.length,6);
});
test('legacy hotel return opens the same all-order GO Trip', async()=>{
  let calls=0;const context={showUnifiedTrips:async()=>{calls++}};vm.createContext(context);
  vm.runInContext(app.slice(app.indexOf('async function showTrips(){'),app.indexOf('async function showTrip(')),context);
  await context.showTrips();assert.equal(calls,1);
});
