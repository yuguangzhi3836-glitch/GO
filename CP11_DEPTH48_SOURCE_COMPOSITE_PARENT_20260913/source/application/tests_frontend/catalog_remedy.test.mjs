import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function fixture(){
 const posts=[],notices=[];let html='',created=false,fail=true,back=0;
 const button={disabled:false},form={elements:{claimed_cause:{value:'NO_ROOM'},references:{value:' stock evidence '}},querySelector(){return button}};
 const container={set innerHTML(v){html=v},get innerHTML(){return html},querySelector(selector){
  if(selector==='#crRequest')return html.includes('id="crRequest"')?form:null;
  if(selector==='#crProof')return null;
  return html.includes('id="'+selector.slice(1)+'"')?{}:null;
 }};
 const context={window:{},crypto:{randomUUID:()=> 'one-request-key'}};
 vm.runInNewContext(fs.readFileSync('frontend/shared/catalog-remedy.js','utf8'),context);
 const ctx={container,esc:v=>String(v).replace(/</g,'&lt;'),unwrap:r=>r,notice:(...x)=>notices.push(x),onBack:()=>back++,request:async(path,options)=>{
  if(!options)return created?{case_id:'case-one',state:'EVIDENCE_REQUIRED'}:null;
  posts.push({path,options});if(fail)throw Error('网络中断');created=true;return {case_id:'case-one'};
 }};
 return {ui:context.window.GOCatalogRemedy,ctx,form,button,posts,notices,get html(){return html},set fail(v){fail=v}};
}
test('supplier lost-response retry keeps request identity and sends only the claimed cause',async()=>{
 const f=fixture();await f.ui.supplierRequest(f.ctx,{order_id:'ord_owned'});
 await f.form.onsubmit({preventDefault(){}});assert.equal(f.posts.length,1);assert.equal(f.notices[0][0],'网络中断');
 f.fail=false;await f.form.onsubmit({preventDefault(){}});assert.equal(f.posts.length,2);
 const first=f.posts[0].options,second=f.posts[1].options;
 assert.equal(first.headers['Idempotency-Key'],second.headers['Idempotency-Key']);
 assert.deepEqual(JSON.parse(JSON.stringify(first.body)),{reason_code:'NO_ROOM',evidence_ids:['stock evidence']});
 assert.ok(f.html.includes('待补充证据'));assert.equal(f.html.includes('赔付成功'),false);
});
test('supplier duplicate clicks while a request is pending cannot create another request',async()=>{
 const f=fixture();await f.ui.supplierRequest(f.ctx,{order_id:'ord_owned'});let finish;
 f.ctx.request=async(path,options)=>{if(!options)return {state:'EVIDENCE_REQUIRED'};f.posts.push({path,options});return new Promise(r=>finish=r)};
 const pending=f.form.onsubmit({preventDefault(){}});await f.form.onsubmit({preventDefault(){}});
 assert.equal(f.posts.length,1);finish({case_id:'case-one'});await pending;
});
const consumer={window:{},Intl};vm.runInNewContext(fs.readFileSync('frontend/consumer/direct-after-sales.js','utf8'),consumer);
test('unknown supplier cancellation shows approved refund waiting for confirmation, without a resend button',()=>{
 const html=consumer.window.GODirectAfterSales.disruption({state:'UNKNOWN_SUPPLIER_CANCEL',actual_paid_minor:120000,refund_due_minor:120000,compensation_due_minor:120000,refund_state:'REFUND_ELIGIBLE_CONTRACT_ONLY',compensation_state:'PENDING',retry_allowed:false},'CNY');
 assert.ok(html.includes('正在核对酒店取消结果'));assert.ok(html.includes('退款已批准'));assert.equal(html.includes('退款已完成'),false);assert.equal(html.includes('retrySupplierRemedy'),false);
});
