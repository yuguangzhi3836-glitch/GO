import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const ctx={window:{},Intl};
vm.runInNewContext(fs.readFileSync('frontend/consumer/direct-after-sales.js','utf8'),ctx);
const ui=ctx.window.GODirectAfterSales;
const base={held_minor:0,capture_minor:81001,release_minor:80999,refund_minor:10001};
test('hotel funds distinguish frozen, charged, released and refunded cent amounts',()=>{
 const html=ui.render({funds:base,cases:[]});
 for(const text of ['仍在授权中','已扣款（房费或规则费用）','已释放授权','已退回原扣款','810.01','809.99','100.01','未发生真实资金交易'])assert.ok(html.includes(text));
 assert.equal(html.includes('data-refund-retry'),false);
});
test('only approved pending refunds expose retry and all server labels are escaped',()=>{
 const html=ui.render({cases:[{state:'DECIDED',approved_refund_minor:10001,refund_state:'REFUND_PENDING_SIMULATION',retry_allowed:true,refund_eligibility_id:'x" onfocus="alert(1)'}]});
 assert.ok(html.includes('退款处理中'));assert.ok(html.includes('data-refund-retry="x&quot; onfocus=&quot;alert(1)"'));
 assert.equal(html.includes('data-refund-retry="x"'),false);
 const done=ui.render({cases:[{state:'CLOSED',approved_refund_minor:10001,refund_state:'REFUND_CONFIRMED_SIMULATION',retry_allowed:false}]});
 assert.ok(done.includes('退款已完成'));assert.equal(done.includes('data-refund-retry'),false);
});
test('unknown funding shows reconciliation instead of a false payment claim',()=>{
 const html=ui.render({funds:{...base,reconciliation_required:true}});
 assert.ok(html.includes('资金状态正在核对'));assert.ok(html.includes('role="alert"'));
});
test('trip links only open the exact canonical owned direct-reservation path',()=>{
 const item={vertical:'HOTEL',order_id:'hdr_123',facts_json:{detail_url:'/go-app/direct.html?reservation=hdr_123'}};
 assert.equal(ui.tripLink(item),item.facts_json.detail_url);
 for(const bad of ['javascript:alert(1)','https://evil.example','//evil.example','/go-app/direct.html?reservation=other'])
  assert.equal(ui.tripLink({...item,facts_json:{detail_url:bad}}),null);
 assert.equal(ui.tripLink({...item,vertical:'FLIGHT'}),null);
 assert.equal(ui.tripLink({...item,order_id:'../../other'}),null);
});
const source=fs.readFileSync('frontend/consumer/direct.js','utf8');
const fn=source.slice(source.indexOf('  async function openStayCase('),source.indexOf('  async function restoreReservations('));
function setup(){
 const calls=[];let dialog,removed=false;
 const document={createElement(){const nodes=new Map();return {innerHTML:'',setAttribute(){},showModal(){},close(){},remove(){removed=true},querySelector(k){if(!nodes.has(k))nodes.set(k,{disabled:false,value:k==='[name=kind]'?'SERVICE':'服务未达约定',textContent:''});return nodes.get(k)}}},body:{append(d){dialog=d}}};
 const ctx={document,crypto:{randomUUID:()=> 'stable-case-key'},api:async(...args)=>{calls.push(args);return{}},showReservation:async()=>{}};
 vm.runInNewContext(fn,ctx);return {ctx,calls,get dialog(){return dialog},get removed(){return removed}};
}
test('closing a stay complaint form makes no request',async()=>{
 const s=setup();await s.ctx.openStayCase('hdr_123');s.dialog.querySelector('[data-close]').onclick();assert.equal(s.calls.length,0);assert.ok(s.removed);
});
test('complaint retries reuse the same request identity and have no refund approval fields',async()=>{
 const s=setup();await s.ctx.openStayCase('hdr_123');let attempts=0;
 s.ctx.api=async(...args)=>{s.calls.push(args);if(++attempts===1)throw Error('连接中断');return {}};
 const submit=s.dialog.querySelector('form').onsubmit;await submit({preventDefault(){}});
 assert.equal(s.dialog.querySelector('[role=alert]').textContent,'连接中断');assert.equal(s.removed,false);
 await submit({preventDefault(){}});assert.equal(s.calls.length,2);assert.equal(s.calls[0][3],s.calls[1][3]);
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0][1])),{dispute_type:'SERVICE',description:'服务未达约定'});
});
test('blank complaints and duplicate submission clicks cannot send extra requests',async()=>{
 const s=setup();await s.ctx.openStayCase('hdr_123');const submit=s.dialog.querySelector('form').onsubmit;
 s.dialog.querySelector('[name=description]').value=' ';await submit({preventDefault(){}});assert.equal(s.calls.length,0);
 let finish;s.ctx.api=(...args)=>{s.calls.push(args);return new Promise(r=>finish=r)};
 s.dialog.querySelector('[name=description]').value='房间与预订不符';const pending=submit({preventDefault(){}});
 await submit({preventDefault(){}});s.dialog.querySelector('[data-close]').onclick();assert.equal(s.calls.length,1);assert.equal(s.removed,false);
 finish({});await pending;assert.equal(s.removed,true);
});
