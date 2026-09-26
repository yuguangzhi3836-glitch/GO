/* Deterministic delayed transport callbacks executing the real three UI functions.
   This is a source callback test, not a substitute for browser CI. */
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
const path=new URL('../../frontend/shared/app.js',import.meta.url);const text=fs.readFileSync(path,'utf8');const hash=s=>createHash('sha256').update(s).digest('hex');const before=hash(text);
const functions=text.slice(text.indexOf('async function supplierCommandCenter(){'),text.indexOf('\nfunction cashAfterSalesCard('));
function fixture(){
 let currentView={isConnected:true,innerHTML:'INITIAL',appendChild:()=>{},querySelector:()=>({})};const requests=[];const buttons={};
 const ctx={location:{hash:'#/orders'},currentSupplierRoute:'',document:{createElement:()=>({isConnected:true,className:''})},window:{GORentalOperations:{render:async()=>{}},GOTicketOperations:{mount:async()=>{}}},
  $:q=>q==='#view'?currentView:(buttons[q]??={}),unwrap:x=>x,esc:x=>String(x),money:x=>String(x),supplierFriendlyValue:x=>String(x),metrics:()=>'',table:x=>JSON.stringify(x),supplierStructuredShell:(route,body)=>route+body,supplierObjectCard:(label,o)=>JSON.stringify(o),bindRows:()=>{},notice:()=>{},
  api:{request:path=>new Promise((resolve,reject)=>requests.push({path,resolve,reject}))}};
 vm.createContext(ctx);vm.runInContext(functions,ctx);
 return {ctx,requests,view:()=>currentView,replaceView:()=>{currentView.isConnected=false;currentView={isConnected:true,innerHTML:'NEW_ACCOUNT_VIEW',appendChild:()=>{},querySelector:()=>({})};}};
}
const detail=id=>({order:{order_id:id,status:'COMPLETED'},original_payment:{captured_minor:126000,refunded_minor:0,net_minor:126000,currency:'CNY',binding_state:'BOUND'},refunds:[]});
const results=[];
for(const fail of [false,true]){
 const f=fixture();f.ctx.location.hash='#/command';const stale=f.ctx.supplierCommandCenter();f.ctx.location.hash='#/orders';const list=f.ctx.supplierOrders();
 f.requests[1].resolve({items:[{order_id:'CURRENT_LIST',status:'CONFIRMED'}]});await list;const current=f.view().innerHTML;
 if(fail)f.requests[0].reject(Error('LATE_DASHBOARD_FAILURE'));else f.requests[0].resolve({orders:{CONFIRMED:999}});await stale;
 assert.equal(f.view().innerHTML,current);assert.ok(current.includes('CURRENT_LIST'));results.push('late_dashboard_'+(fail?'failure':'success'));
}
{
 const f=fixture();const stale=f.ctx.supplierOrders();const current=f.ctx.supplierTransactionWorkbench('RENTAL','CURRENT_DETAIL');f.requests[1].resolve(detail('CURRENT_DETAIL'));await current;const html=f.view().innerHTML;
 f.requests[0].resolve({items:[{order_id:'OLD_LIST',status:'CONFIRMED'}]});await stale;assert.equal(f.view().innerHTML,html);assert.ok(html.includes('CURRENT_DETAIL'));results.push('old_list_same_route_cannot_replace_detail');
}
{
 const f=fixture();const stale=f.ctx.supplierTransactionWorkbench('RENTAL','OLD_DETAIL');const current=f.ctx.supplierTransactionWorkbench('RENTAL','CURRENT_DETAIL');f.requests[1].resolve(detail('CURRENT_DETAIL'));await current;const html=f.view().innerHTML;
 f.requests[0].resolve(detail('OLD_DETAIL'));await stale;assert.equal(f.view().innerHTML,html);assert.ok(html.includes('CURRENT_DETAIL'));results.push('old_detail_same_route_cannot_replace_new_detail');
}
{
 const f=fixture();const stale=f.ctx.supplierCommandCenter();const current=f.ctx.supplierTransactionWorkbench('RENTAL','CURRENT_DETAIL');f.requests[1].resolve(detail('CURRENT_DETAIL'));await current;const html=f.view().innerHTML;
 f.requests[0].resolve({orders:{CONFIRMED:999}});await stale;assert.equal(f.view().innerHTML,html);results.push('same_route_dashboard_token_fence');
}
{
 const f=fixture();const stale=f.ctx.supplierTransactionWorkbench('RENTAL','OLD_ACCOUNT_DETAIL');f.replaceView();f.requests[0].resolve(detail('OLD_ACCOUNT_DETAIL'));await stale;assert.equal(f.view().innerHTML,'NEW_ACCOUNT_VIEW');results.push('replaced_view_does_not_receive_old_detail');
}
{
 const f=fixture();let refresh;
 f.ctx.window.GOTicketOperations.mount=async(...args)=>{refresh=args[5];};
 const initial=f.ctx.supplierTransactionWorkbench('FLIGHT','OLD_FLIGHT');f.requests[0].resolve(detail('OLD_FLIGHT'));await initial;
 const staleRefresh=refresh();
 const current=f.ctx.supplierTransactionWorkbench('RENTAL','NEW_RENTAL');f.requests[2].resolve(detail('NEW_RENTAL'));await current;
 const html=f.view().innerHTML;f.requests[1].reject(Error('LATE_DETAIL_FAILURE'));await staleRefresh;
 assert.equal(f.view().innerHTML,html,'Late ticket refresh failure must not erase a newer rental detail');results.push('late_refresh_failure');
}
assert.equal(hash(fs.readFileSync(path,'utf8')),before);console.log(JSON.stringify({result:'PASS',tests:results.length,scenarios:results,mode:'ACTUAL_UI_CALLBACK_DELAY_STUB_NOT_BROWSER',app_js_sha256:before}));
