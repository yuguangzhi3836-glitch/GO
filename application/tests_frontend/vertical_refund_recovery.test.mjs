import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const code=fs.readFileSync('frontend/consumer/app.js','utf8');
const helpers=code.slice(code.indexOf('async function submitVerticalRefund('),code.indexOf('async function railRefund('));
function setup(vertical='RAIL',error=null){
 const calls=[],order={order_id:'owned-order',status:'REFUND_PENDING'};
 const c={state:{railOrder:order,attractionOrder:order},crypto:{randomUUID:()=> 'request-21'},Error,
  api:async(path,options)=>{calls.push({path,options});if(options&&error)throw Error(error);return options?{status:'REFUND_COMPLETED'}:{...order,status:'REFUNDED'}},
  renderRailOrder:()=>calls.push({render:'RAIL'}),renderAttractionOrder:()=>calls.push({render:'ATTRACTION'}),
  uxConfirm:options=>options};
 vm.createContext(c);vm.runInContext(helpers,c);return {c,calls,order};
}
for(const vertical of ['RAIL','ATTRACTION']){
 test(`${vertical}: opening recovery does not send a refund until confirmed`,async()=>{
  const s=setup(vertical),dialog=s.c.resumeVerticalRefund(vertical);assert.equal(s.calls.length,0);
  await dialog.onConfirm();assert.equal(s.calls.filter(x=>x.options?.method==='POST').length,1);
  assert.equal(s.calls[0].options.headers['Idempotency-Key'],'request-21');
  assert.match(s.calls[0].path,/owned-order\/refund$/);assert.equal(s.calls.at(-1).render,vertical);
 });
 test(`${vertical}: failed response still reloads persisted order state`,async()=>{
  const s=setup(vertical,'connection lost');await assert.rejects(s.c.submitVerticalRefund(vertical,'owned-order'),/connection lost/);
  assert.equal(s.calls[1].options,undefined);assert.equal(s.calls.at(-1).render,vertical);
 });
}
test('busy recovery gives a customer message and refreshes the existing order',async()=>{
 const s=setup('RAIL','REFUND_ALREADY_PROCESSING');await assert.rejects(s.c.submitVerticalRefund('RAIL','owned-order'),/原退款正在核对/);
 assert.equal(s.c.state.railOrder.status,'REFUNDED');
});
test('rail interrupted change confirms the original quote instead of creating another',async()=>{
 const start=code.indexOf('async function railResumeChange('),end=code.indexOf('async function railReload(',start);
 let dialog;const calls=[];const c={state:{railOrder:{order_id:'order21',change_quotes:[{quote_id:'quote21',status:'PREPARING'}]}},
  toast:()=>{},uxConfirm:x=>{dialog=x},crypto:{randomUUID:()=> 'resume21'},api:async(p,b)=>calls.push({p,b}),railReload:async()=>calls.push({reload:true})};
 vm.createContext(c);vm.runInContext(code.slice(start,end),c);await c.railResumeChange();assert.equal(calls.length,0);
 await dialog.onConfirm();assert.match(calls[0].p,/execute-change\/quote21$/);assert.equal(calls.at(-1).reload,true);
});
