/* Execute actual UI callbacks with observed request stubs; not browser evidence. */
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
const path=new URL('../../frontend/consumer/app.js',import.meta.url);const source=fs.readFileSync(path,'utf8');
const digest=s=>createHash('sha256').update(s).digest('hex');const before=digest(source);
const functions=source.slice(source.indexOf('async function submitVerticalRefund('),source.indexOf('async function railRefund('))+'\n'+source.slice(source.indexOf('async function attractionRefund('),source.indexOf('\n\nbootstrapConsumer'));
function fixture(status='CONFIRMED',reject=false){
 const calls=[];let confirm,quote={quote_hash:'a'.repeat(64),refundable:true,refund_amount_minor:18000,currency:'CNY'};
 const ctx={state:{attractionOrder:{order_id:'order-A',status}},crypto:{randomUUID:()=> 'isolated-id'},money:v=>String(v),toast:()=>{},renderAttractionOrder:()=>{},renderRailOrder:()=>{},uxConfirm:args=>{confirm=args;},api:async(path,options)=>{calls.push({path,options});if(path.endsWith('/refund-quote'))return {...quote};if(options?.method==='POST'){if(reject)throw Error('REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED');return {status:'REFUND_COMPLETED'};}return {order_id:'order-A',status:'REFUNDED'};}};
 vm.createContext(ctx);vm.runInContext(functions,ctx);
 return {ctx,calls,confirmation:()=>confirm,replaceQuote:q=>quote=q};
}
{
 const f=fixture();await f.ctx.attractionRefund();assert.ok(f.confirmation().summary.includes('18000'));
 f.replaceQuote({quote_hash:'b'.repeat(64),refundable:true,refund_amount_minor:1,currency:'CNY'});
 await f.confirmation().onConfirm();const posts=f.calls.filter(c=>c.options?.method==='POST');assert.equal(posts.length,1);assert.equal(posts[0].path,'/v1/attractions/orders/order-A/refund-confirmed');assert.deepEqual(JSON.parse(posts[0].options.body),{quote_hash:'a'.repeat(64),confirmed:true});assert.equal(f.calls.filter(c=>c.path.endsWith('/refund-quote')).length,1);
}
{
 const f=fixture('CONFIRMED',true);await f.ctx.attractionRefund();await assert.rejects(f.confirmation().onConfirm(),/RECONFIRM_REQUIRED/);assert.equal(f.calls.filter(c=>c.path.endsWith('/refund-quote')).length,1);assert.equal(f.calls.filter(c=>c.options?.method==='POST').length,1);
}
{
 const f=fixture('REFUND_PENDING');await f.ctx.attractionRefund();assert.equal(f.calls.length,0);await f.confirmation().onConfirm();assert.equal(f.calls[0].path,'/v1/attractions/orders/order-A/refund-quote');assert.deepEqual(JSON.parse(f.calls[1].options.body),{quote_hash:'a'.repeat(64),confirmed:true});
}
assert.equal(digest(fs.readFileSync(path,'utf8')),before);console.log(JSON.stringify({tests:3,result:'PASS',mode:'ACTUAL_UI_CALLBACK_STUB_NOT_BROWSER',app_js_sha256:before}));
