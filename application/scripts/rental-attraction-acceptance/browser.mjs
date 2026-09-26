/* Independent UI-only journey probe. No API request client, DB writes or app-state injection. */
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.TICKET_BROWSER_ROOT,state=process.env.TICKET_BROWSER_STATE;
assert.ok(base&&state,'TICKET_BROWSER_ROOT and TICKET_BROWSER_STATE required');
const origin='http://127.0.0.1:4187',out=base+'/rental-attractions-evidence';await fs.mkdir(out,{recursive:true});
const credentials=JSON.parse(await fs.readFile(state+'/credentials.private.json','utf8'));
const suppliers=JSON.parse(await fs.readFile(state+'/suppliers.private.json','utf8'));
const report={binding:JSON.parse(await fs.readFile(base+'/binding.json','utf8')),mode:'ISOLATED_SQLITE_CHROMIUM',native_device:'NOT_RUN',acceptance:'LIMITED_SCENARIOS_ONLY',events:[],steps:[],errors:[],facts:{},not_verified:['FULL_C04_30_108','FULL_C06_14_44','PG_BROWSER_CONCURRENCY','NATIVE_INTERACTION','OPERATIONS_SLA_ESCALATION','REAL_SUPPLIER_POLICY']};
const browser=await chromium.launch({headless:true});report.browser=browser.version();
const day=n=>new Date(Date.now()+n*86400000).toISOString().slice(0,10);
const amount=(minor,currency='CNY')=>new Intl.NumberFormat('zh-CN',{style:'currency',currency}).format(minor/100);
const waitResponse=(p,path,method='GET')=>p.waitForResponse(r=>new URL(r.url()).pathname===path&&r.request().method()===method);
async function data(response){assert.equal(response.status(),200,await response.text());return (await response.json()).data;}
async function step(name,p,fn){try{await fn();report.steps.push({name,result:'PASS'});}catch(e){report.steps.push({name,result:'FAIL',error:e.message,visible:(await p.locator('body').innerText()).slice(-7000)});throw e;}finally{await p.screenshot({path:out+'/'+report.steps.length+'-'+name+'.png',fullPage:true});await fs.writeFile(out+'/results.json',JSON.stringify(report,null,2));}}
async function page(role,account,width){
 const context=await browser.newContext({viewport:{width,height:950},locale:'zh-CN',timezoneId:'UTC'});
 await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
 const p=await context.newPage();p.setDefaultTimeout(15000);
 p.on('pageerror',e=>report.errors.push({role,message:e.message}));
 p.on('response',r=>{const path=new URL(r.url()).pathname;if(path.startsWith('/v1/')||path.startsWith('/internal/'))report.events.push({role,path,status:r.status(),method:r.request().method()});});
 await p.goto(origin+(role==='consumer'?'/go-app/':'/supplier-console/'));
 if(role==='consumer'){await p.locator('#accountBtn').click();await p.locator('#email').fill(account.username);await p.locator('#pwd').fill(account.password);await p.locator('#login').click();await p.locator('#email').waitFor({state:'detached'});}
 else{await p.locator('#user').fill(account.username);await p.locator('#pass').fill(account.password);await p.locator('form#login button').first().click();await p.locator('.shell').waitFor();}
 return p;
}
async function consentDialog(p,title){
 const d=p.locator('dialog[open]');await d.waitFor();if(title)assert.equal(await d.locator('h2').first().innerText(),title);
 const traveler=d.locator('#goTraveler');if(await traveler.count())await traveler.selectOption({index:1});
 for(const box of await d.locator('[data-consent],[data-quote-consent],[data-policy-consent]').all())await box.check();
 const previous=await d.locator('h2').first().innerText();await d.locator('[type=submit]').click();
 await p.waitForFunction(t=>document.querySelector('dialog[open] h2')?.textContent!==t,previous);
}
async function chooseRentalDates(p,start,end){
 await p.locator('#mt1').click();const cal=p.locator('.go-date-range');await cal.waitFor();
 async function pick(value){
  for(let i=0;i<15&&!await cal.locator(`[data-day="${value}"]`).count();i++){
   const shown=await cal.locator('[data-month]').innerText();const parts=shown.match(/(\d+)年(\d+)月/);assert.ok(parts,'Calendar month label');
   const displayed=Number(parts[1])*12+Number(parts[2]),desired=Number(value.slice(0,4))*12+Number(value.slice(5,7));
   await cal.locator(desired>displayed?'[data-next]':'[data-prev]').click();
  }
  await cal.locator(`[data-day="${value}"]`).click();
 }
 await pick(start);await pick(end);await cal.locator('[data-start-time]').fill('10:00');await cal.locator('[data-end-time]').fill('10:00');
 await cal.locator('[data-confirm]').click();await cal.waitFor({state:'detached'});
 assert.equal(await p.locator('#mt1').inputValue(),start+'T10:00');assert.equal(await p.locator('#mt2').inputValue(),end+'T10:00');
}
async function bookRental(p,start,end){
 await p.goto(origin+'/go-app/');await p.locator('[data-home-vertical=MOBILITY]').click();await p.locator('#homeRental').click();
 await p.locator('#m1').fill('哈尔滨机场');await p.locator('#m2').fill('哈尔滨机场');await chooseRentalDates(p,start,end);await p.locator('#mgo').click();
 await p.locator('[data-mob="rental_compact"] button').click();const created=waitResponse(p,'/v1/mobility/rentals/orders','POST');await consentDialog(p,'核对租车出行资料');
 const order=await data(await created);assert.equal(order.status,'PAYMENT_PENDING');
 const checkout=waitResponse(p,`/v1/consumer/checkout/RENTAL/${order.order_id}`,'POST');const refreshed=waitResponse(p,`/v1/mobility/orders/${order.order_id}`);
 await consentDialog(p,'确认租车订单');await data(await checkout);const fresh=await data(await refreshed);assert.equal(fresh.status,'CONFIRMED');assert.ok(fresh.supplier_reference);assert.equal(fresh.order_id,order.order_id);
 await p.locator('#mmod').waitFor();assert.equal(await p.locator('#mmod').isEnabled(),true);return fresh;
}
let consumer,supplier,rental,attraction,claimOrder;
try{
 consumer=await page('consumer',credentials.consumer,390);
 await step('traveler',consumer,async()=>{
  await consumer.locator('#accountBtn').click();await consumer.locator('#vmAdd').click();const d=consumer.locator('dialog[open]');
  await d.locator('#pvName').fill('INDEPENDENT RENTAL ADULT');await d.locator('#pvRel').selectOption('SELF');await d.locator('#pvPhone').fill('13800000000');await d.locator('#pvLicense').fill('TEST-ISOLATED-RENTAL');await d.locator('[data-confirm]').check();await d.locator('[type=submit]').click();await d.waitFor({state:'detached'});
 });
 await step('rental-search-book-pay',consumer,async()=>{rental=await bookRental(consumer,day(30),day(33));report.facts.rental_booked=rental;});
 await step('rental-reprice-change',consumer,async()=>{
  await consumer.locator('#mmod').click();const d=consumer.locator('dialog[open]');await d.locator('#rentalReturn').fill(day(34)+'T10:00');
  const quoted=waitResponse(consumer,`/v1/mobility/rentals/orders/${rental.order_id}/change-quotes`,'POST');await consentDialog(consumer,'选择新的取还车时间');const q=await data(await quoted);assert.ok(q.difference_minor>0);
  const executed=waitResponse(consumer,`/v1/mobility/rentals/orders/${rental.order_id}/changes/${q.quote_id}`,'POST'),fresh=waitResponse(consumer,`/v1/mobility/orders/${rental.order_id}`);
  await consentDialog(consumer,'核对租车改期');const result=await data(await executed);assert.equal(result.status,'EXECUTED');const changed=await data(await fresh);
  assert.equal(changed.return_at.slice(0,16),day(34)+'T10:00');assert.equal(changed.total_amount_minor,rental.total_amount_minor+q.difference_minor);
  await consumer.getByText('取还车安排',{exact:true}).waitFor();await consumer.getByText(amount(changed.total_amount_minor),{exact:true}).first().waitFor();rental=changed;report.facts.rental_changed=changed;
 });
 await step('rental-cancel-refund',consumer,async()=>{
  const quoted=waitResponse(consumer,`/v1/mobility/orders/${rental.order_id}/refund-quote`);await consumer.locator('#mcancel').click();const q=await data(await quoted);assert.equal(q.refund_amount_minor,rental.total_amount_minor);
  const refunded=waitResponse(consumer,`/v1/mobility/orders/${rental.order_id}/refund-confirmed`,'POST'),fresh=waitResponse(consumer,`/v1/mobility/orders/${rental.order_id}`);
  await consumer.locator('#uxConfirm').click();const receipt=await data(await refunded),order=await data(await fresh);assert.equal(receipt.status,'REFUND_COMPLETED');assert.equal(receipt.refund_amount_minor,q.refund_amount_minor);assert.equal(order.status,'REFUNDED');assert.equal(order.order_id,rental.order_id);
  await consumer.getByText('已退款',{exact:true}).first().waitFor();report.facts.rental_refund={receipt,order};
 });
 await step('attraction-search-book-pay',consumer,async()=>{
  await consumer.goto(origin+'/go-app/');await consumer.locator('[data-home-vertical=ATTRACTION]').click();await consumer.locator('#adest').fill('东京');await consumer.locator('#adate').fill(day(30));await consumer.locator('#ago').click();await consumer.locator('[data-attr="tokyo_skytree"] button').click();
  const d=consumer.locator('dialog[open]');await d.locator('#goPartyCount').selectOption('1');await d.locator('#goPartySession').selectOption('16:00');await consentDialog(consumer,'选择门票人数与场次');await consentDialog(consumer,'核对门票出行资料');
  const created=waitResponse(consumer,'/v1/attractions/orders','POST');await consentDialog(consumer,'核对门票与总价');const o=await data(await created);assert.equal(o.status,'PAYMENT_PENDING');
  const paid=waitResponse(consumer,`/v1/consumer/checkout/ATTRACTION/${o.order_id}`,'POST'),fresh=waitResponse(consumer,`/v1/attractions/orders/${o.order_id}`);await consentDialog(consumer,'确认门票订单');await data(await paid);attraction=await data(await fresh);
  assert.equal(attraction.status,'CONFIRMED');assert.ok(attraction.voucher_code);assert.equal(attraction.order_id,o.order_id);await consumer.locator('#ared').waitFor();report.facts.attraction_booked=attraction;
 });
 await step('attraction-future-window-disables-redemption',consumer,async()=>{
  assert.equal(attraction.can_redeem,false);assert.ok(Date.parse(attraction.redemption_window.opens_at)>Date.now());assert.equal(await consumer.locator('#ared').isDisabled(),true);
  await consumer.getByText('当前不可核销，请核对日期、场次与处理状态',{exact:true}).waitFor();assert.ok(!report.events.some(e=>e.path===`/v1/attractions/orders/${attraction.order_id}/redeem`));
  report.facts.future_window_guard='UI_DISABLED_WITH_SERVER_CAN_REDEEM_FALSE; backend bypass rejection is outside this UI probe';
 });
 await step('attraction-refund',consumer,async()=>{
  const quoted=waitResponse(consumer,`/v1/attractions/orders/${attraction.order_id}/refund-quote`);await consumer.locator('#aref').click();const q=await data(await quoted);assert.equal(q.refund_amount_minor,attraction.total_amount_minor);
  const refunded=consumer.waitForResponse(r=>new URL(r.url()).pathname.startsWith(`/v1/attractions/orders/${attraction.order_id}/refund`)&&r.request().method()==='POST'),fresh=waitResponse(consumer,`/v1/attractions/orders/${attraction.order_id}`);
  await consumer.locator('#uxConfirm').click();const response=await refunded;assert.equal(new URL(response.url()).pathname,`/v1/attractions/orders/${attraction.order_id}/refund-confirmed`);assert.deepEqual(response.request().postDataJSON(),{quote_hash:q.quote_hash,confirmed:true});const receipt=await data(response),order=await data(await fresh);assert.equal(receipt.status,'REFUND_COMPLETED');assert.equal(receipt.refund_amount_minor,q.refund_amount_minor);assert.equal(order.status,'REFUNDED');assert.equal(order.voucher_code,null);assert.equal(order.order_id,attraction.order_id);
  await consumer.getByText('已退款',{exact:true}).first().waitFor();assert.equal(await consumer.locator('#ared').isDisabled(),true);report.facts.attraction_refund={receipt,order};
 });
 if(suppliers.RENTAL){
  await step('rental-second-book-for-supplier-claim',consumer,async()=>{claimOrder=await bookRental(consumer,day(40),day(43));report.facts.rental_claim_order=claimOrder;});
  await step('rental-normal-pickup-return',consumer,async()=>{
   for(const [button,expected] of [['#mstart','IN_PROGRESS'],['#mend','COMPLETED']]){
    const applied=waitResponse(consumer,`/v1/mobility/orders/${claimOrder.order_id}/fulfillment`,'POST'),fresh=waitResponse(consumer,`/v1/mobility/orders/${claimOrder.order_id}`);await consumer.locator(button).click();await data(await applied);const order=await data(await fresh);assert.equal(order.status,expected);report.facts['rental_'+expected.toLowerCase()]=order;
   }
   await consumer.getByText('已完成',{exact:true}).first().waitFor();report.facts.fulfillment_boundary='Synthetic consumer pickup/return clicks; not independently verified physical handover';
  });
  supplier=await page('supplier',suppliers.RENTAL,1440);
  await step('supplier-bound-rental-damage-claim',supplier,async()=>{
   await supplier.goto(origin+'/supplier-console/#/orders');await supplier.getByText(claimOrder.order_id,{exact:true}).click();const form=supplier.locator('[data-rental-command="OPEN"]');await form.waitFor();
   await form.locator('[name=amount_minor]').fill('10000');await form.locator('[name=pickup_statement]').fill('隔离验收：取车时观察陈述');await form.locator('[name=return_statement]').fill('隔离验收：还车时观察陈述');await form.locator('[name=confirmed]').check();
   const posted=waitResponse(supplier,`/v1/supplier/mobility/rentals/orders/${claimOrder.order_id}/operations/cases`,'POST'),fresh=waitResponse(supplier,`/v1/mobility/rentals/orders/${claimOrder.order_id}/operations`);await form.locator('[type=submit]').click();const claim=await data(await posted),workspace=await data(await fresh);
   assert.equal(claim.order_id,claimOrder.order_id);assert.equal(claim.supplier_evidence_status,'SUPPLIER_STATEMENT_UNVERIFIED');assert.equal(claim.status,'AWAITING_CUSTOMER');assert.equal(workspace.actor_type,'SUPPLIER_USER');assert.equal(workspace.cases.length,1);assert.deepEqual(workspace.cases[0].actions,[]);
   await supplier.getByText('车损记录',{exact:true}).waitFor();assert.equal(await supplier.locator('[data-rental-command="DECISION"]').count(),0);report.facts.supplier_claim={claim,workspace};
  });
 }else report.not_verified.push('SUPPLIER_CLAIM_NO_RENTAL_CREDENTIAL_FIXTURE');
 assert.deepEqual(report.errors,[]);report.result='PASS';
}catch(e){report.result='FAIL';report.error=e.message;process.exitCode=1;}
finally{await fs.writeFile(out+'/results.json',JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify({result:report.result,acceptance:report.acceptance,steps:report.steps.map(({name,result})=>({name,result})),error:report.error}));}
