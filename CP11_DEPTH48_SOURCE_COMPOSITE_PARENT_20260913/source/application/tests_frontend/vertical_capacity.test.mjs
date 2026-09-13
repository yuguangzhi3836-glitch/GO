import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const code=fs.readFileSync('frontend/consumer/app.js','utf8');
const helper=code.slice(code.indexOf('function cancelUnpaidVertical('));
function setup(vertical,status='PAYMENT_PENDING',fail=false){
 const calls=[],order={order_id:'order/23',status};
 const c={state:{railOrder:order,attractionOrder:order},encodeURIComponent,
  uxConfirm:args=>args,api:async(path,args)=>{calls.push({path,args});if(fail)throw Error('connection lost')},
  railReload:async()=>calls.push({reload:'RAIL'}),attractionReload:async()=>calls.push({reload:'ATTRACTION'})};
 vm.createContext(c);vm.runInContext(helper,c);return {c,calls};
}
for(const vertical of ['RAIL','ATTRACTION']){
 test(`${vertical} cancellation requires explicit confirmation`,async()=>{
  const s=setup(vertical),dialog=s.c.cancelUnpaidVertical(vertical);
  assert.equal(s.calls.length,0);await dialog.onConfirm();
  assert.equal(s.calls[0].args.method,'POST');assert.match(s.calls[0].path,/order%2F23\/cancel-unpaid$/);
  assert.equal(s.calls.at(-1).reload,vertical);
 });
 test(`${vertical} response loss still reloads persisted order`,async()=>{
  const s=setup(vertical,'PAYMENT_PENDING',true);
  await assert.rejects(s.c.cancelUnpaidVertical(vertical).onConfirm(),/connection lost/);
  assert.equal(s.calls.at(-1).reload,vertical);
 });
 test(`${vertical} paid or uncertain orders cannot open unpaid cancellation`,()=>{
  for(const status of ['CONFIRMED','TICKETED','UNKNOWN_EXTERNAL_STATE','REFUND_PENDING','CANCELLED']){
   const s=setup(vertical,status);assert.equal(s.c.cancelUnpaidVertical(vertical),undefined);assert.equal(s.calls.length,0);
  }
 });
}
