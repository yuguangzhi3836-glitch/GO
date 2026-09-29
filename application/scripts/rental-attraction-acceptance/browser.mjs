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
const ops=JSON.parse(await fs.readFile(state+'/operations.private.json','utf8'));
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
 await p.goto(origin+({consumer:'/go-app/',supplier:'/supplier-console/',admin:'/go-admin/'}[role]));
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
async function adminRental(p,orderId){
 await p.goto(origin+'/go-admin/#/vertical-rental');await p.locator('#adminOrderId').fill(orderId);
 const reviewed=waitResponse(p,`/internal/v1/admin/mobility/rentals/orders/${orderId}/deposit-money-review`), business=waitResponse(p,`/v1/mobility/rentals/orders/${orderId}/operations`);
 await p.locator('#adminOrderSearch [type=submit]').click();const snapshot=await data(await reviewed),workspace=await data(await business);
 assert.equal(workspace.actor_type,'GO_ADMIN');assert.ok(workspace.actor_id);report.facts.admin_actors??={};report.facts.admin_actors[p===maker?'maker':p===checker?'checker':'appeal_checker']=workspace.actor_id;
 assert.equal(snapshot.order_id,orderId);assert.equal(snapshot.read_only,true);await p.locator('.rental-deposit-finance [data-refresh]').waitFor();return snapshot;
}
async function finance(p,orderId,obligationId,action,title){
 const f=p.locator('.rental-deposit-finance form[data-action]').filter({has:p.getByRole('button',{name:title,exact:true})});
 await f.waitFor();await f.locator('[data-confirm]').check();
 const applied=waitResponse(p,`/internal/v1/mobility/rentals/orders/${orderId}/deposit-money/${obligationId}/${action}`,'POST');
 const reviewed=waitResponse(p,`/internal/v1/admin/mobility/rentals/orders/${orderId}/deposit-money-review`);
 await f.getByRole('button',{name:title,exact:true}).click();const receipt=await data(await applied),snapshot=await data(await reviewed);
 assert.equal(snapshot.order_id,orderId);assert.notEqual(snapshot.money.state,'RECONCILIATION_REQUIRED');return {receipt,snapshot};
}
async function caseCommand(p,orderId,caseId,action,statement,award){
 const f=p.locator(`[data-rental-command="${action}"][data-case-id="${caseId}"]`);await f.waitFor();
 if(action==='RESPONSE')await f.locator('[name=response]').selectOption('DISPUTE');
 if(award!==undefined)await f.locator('[name=award_minor]').fill(String(award));
 await f.locator('[name=statement]').fill(statement);await f.locator('[name=confirmed]').check();
 const suffix={RESPONSE:'response',DECISION:'decision',APPEAL:'appeal',APPEAL_DECISION:'appeal-decision'}[action];
 const prefix=['RESPONSE','APPEAL'].includes(action)?'/v1/mobility/rentals':'/internal/v1/admin/mobility/rentals';
 const posted=waitResponse(p,`${prefix}/orders/${orderId}/operations/cases/${caseId}/${suffix}`,'POST');
 const refreshed=waitResponse(p,`/v1/mobility/rentals/orders/${orderId}/operations`);
 await f.locator('[type=submit]').click();const claim=await data(await posted),workspace=await data(await refreshed);
 assert.equal(claim.case_id,caseId);assert.equal(workspace.order_id,orderId);return {claim,workspace};
}
async function consumerFunds(p,orderId,obligationId,expected){
 const read=waitResponse(p,`/v1/mobility/rentals/orders/${orderId}/deposit-money/${obligationId}`);
 await p.locator('[data-deposit-refresh]').click();const funds=await data(await read);
 for(const [key,value] of Object.entries(expected))assert.equal(funds[key],value,key);
 await p.waitForFunction(value=>document.querySelector('[data-deposit-net-captured]')?.textContent===value,amount(expected.net_captured_minor));return funds;
}
async function ticketWork(p,orderId,action,note,receipt=null){
 const f=p.locator('[data-ticket-form]');await f.locator('[name=action]').selectOption(action);await f.locator('[name=note]').fill(note);
 if(receipt)for(const [key,value] of Object.entries(receipt)){const el=f.locator(`[name=${key}]`);if(key==='state')await el.selectOption(value);else await el.fill(value);}
 const response=p.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith(`/ticket-operations/ATTRACTION/${orderId}`));
 await f.locator('[type=submit]').click();const result=await data(await response);
 await p.locator(`[data-ticket-form][data-ticket-revision="${result.workflow.revision}"]`).waitFor();return result;
}
async function adminAttraction(p,orderId){
 const target=origin+'/go-admin/#/vertical-attraction';
 // Same-document goto to the current hash does not cause a fresh list request.
 // Re-use the visible normal search form; its submit below always reloads the
 // exact target order and the workbench from authoritative GET responses.
 if(p.url()!==target){
  const initial=waitResponse(p,'/internal/v1/admin/operations/verticals/ATTRACTION');
  await p.goto(target);await data(await initial);
 }
 await p.getByRole('heading',{name:'景点门票 / 体验运营',exact:true}).waitFor();await p.locator('#adminOrderSearch [type=submit]:enabled').waitFor();
 await p.locator('#adminOrderId').fill(orderId);assert.equal(await p.locator('#adminOrderId').inputValue(),orderId);
 const filtered=p.waitForResponse(r=>{const u=new URL(r.url());return r.request().method()==='GET'&&u.pathname==='/internal/v1/admin/operations/verticals/ATTRACTION'&&u.searchParams.get('order_id')===orderId;});
 await p.locator('#adminOrderSearch [type=submit]').click();const listing=await data(await filtered);assert.deepEqual(listing.orders.map(o=>o.order_id),[orderId]);
 await p.waitForFunction(id=>document.querySelector('#adminOrderId')?.value===id&&document.querySelectorAll('#adminOrders tbody tr').length===1&&document.querySelector('#adminOrders tbody tr td')?.textContent===id,orderId);
 const read=waitResponse(p,`/internal/v1/admin/ticket-operations/ATTRACTION/${orderId}`);
 await p.locator('[data-ticket-links]').getByRole('button',{name:orderId,exact:true}).click();const view=await data(await read);assert.equal(view.order.order_id,orderId);await p.locator('[data-ticket-form]').waitFor();return view;
}
async function attractionOrderRow(p,orderId,status){
 const row=p.locator('#adminOrders tbody tr').filter({has:p.getByText(orderId,{exact:true})});
 await row.getByText(status,{exact:true}).waitFor();assert.equal(await row.count(),1);assert.equal(await p.locator('#adminOrderId').inputValue(),orderId);assert.equal(await p.locator('#adminOrders tbody tr').count(),1);return row;
}
async function reopenAttraction(p,orderId){
 await p.locator('[data-nav=trips]').click();await p.locator('#tripQuery').fill(orderId);
 const read=waitResponse(p,`/v1/attractions/orders/${orderId}`);await p.locator('[data-go-trip-index]').first().click();const order=await data(await read);assert.equal(order.order_id,orderId);await p.locator('#ared').waitFor();return order;
}
let consumer,supplier,maker,checker,appealChecker,rental,attraction,claimOrder,obligation,damageCase,managedAttraction,attractionQuote,attractionSupplier;
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
  await consumer.getByText('已退款',{exact:true}).first().waitFor();assert.equal(await consumer.locator('#ared').isDisabled(),true);assert.ok(!(await consumer.locator('body').innerText()).includes('占位继续保留'));report.facts.attraction_refund={receipt,order};
 });
 if(suppliers.RENTAL){
  await step('rental-second-book-for-supplier-claim',consumer,async()=>{claimOrder=await bookRental(consumer,day(40),day(43));report.facts.rental_claim_order=claimOrder;});
  await step('consumer-explicit-deposit-consent',consumer,async()=>{
   const proposed=waitResponse(consumer,`/v1/mobility/rentals/orders/${claimOrder.order_id}/deposit-obligation`,'POST');
   await consumer.locator('[data-deposit-propose]').click();const proposal=await data(await proposed);
   assert.equal(proposal.state,'PROPOSED');assert.ok(proposal.source.amount_minor>=10000);
   await consumer.locator('[data-deposit-accept]').click();
   const accepted=waitResponse(consumer,`/v1/mobility/rentals/orders/${claimOrder.order_id}/deposit-obligation/${proposal.obligation_id}/accept`,'POST');
   await consentDialog(consumer,'核对测试押金条款');obligation=await data(await accepted);
   assert.equal(obligation.state,'ACTIVATED');assert.equal(obligation.source_hash,proposal.source_hash);
   await consumer.waitForFunction(()=>document.querySelector('[data-deposit-money-state]')?.textContent==='尚未授权');report.facts.deposit_consent=obligation;
  });
  assert.ok(ops.maker&&ops.checker&&ops.appeal_checker,'Three separately seeded admin accounts required');
  assert.equal(new Set([ops.maker.username,ops.checker.username,ops.appeal_checker.username]).size,3);
  maker=await page('admin',ops.maker,1440);checker=await page('admin',ops.checker,1440);appealChecker=await page('admin',ops.appeal_checker,1440);
  await step('administrator-authorizes-accepted-deposit',maker,async()=>{
   const before=await adminRental(maker,claimOrder.order_id);assert.equal(before.money.state,'NOT_AUTHORIZED');assert.equal(before.can_authorize,true);
   const result=await finance(maker,claimOrder.order_id,obligation.obligation_id,'authorize','授权押金');
   assert.equal(result.snapshot.money.state,'AUTHORIZED');assert.equal(result.snapshot.money.authorized_minor,obligation.source.amount_minor);assert.equal(result.snapshot.money.captured_minor,0);
   report.facts.deposit_authorization=result;
  });
  await step('rental-normal-pickup-return',consumer,async()=>{
   for(const [button,expected] of [['#mstart','IN_PROGRESS'],['#mend','COMPLETED']]){
    const applied=waitResponse(consumer,`/v1/mobility/orders/${claimOrder.order_id}/fulfillment`,'POST'),fresh=waitResponse(consumer,`/v1/mobility/orders/${claimOrder.order_id}`);await consumer.locator(button).click();await data(await applied);const order=await data(await fresh);assert.equal(order.status,expected);report.facts['rental_'+expected.toLowerCase()]=order;
   }
   await consumer.getByText('已完成',{exact:true}).first().waitFor();report.facts.fulfillment_boundary='Synthetic consumer pickup/return clicks; not independently verified physical handover';
  });
  supplier=await page('supplier',suppliers.RENTAL,1440);
  await step('supplier-bound-rental-damage-claim',supplier,async()=>{
   await supplier.locator('a[href="#/rental-orders"]:visible').first().click();await supplier.getByText(claimOrder.order_id,{exact:true}).click();const form=supplier.locator('[data-rental-command="OPEN"]');await form.waitFor();
   await form.locator('[name=amount_minor]').fill('10000');await form.locator('[name=pickup_statement]').fill('隔离验收：取车时观察陈述');await form.locator('[name=return_statement]').fill('隔离验收：还车时观察陈述');await form.locator('[name=confirmed]').check();
   const posted=waitResponse(supplier,`/v1/supplier/mobility/rentals/orders/${claimOrder.order_id}/operations/cases`,'POST'),fresh=waitResponse(supplier,`/v1/mobility/rentals/orders/${claimOrder.order_id}/operations`);await form.locator('[type=submit]').click();const claim=await data(await posted),workspace=await data(await fresh);
   assert.equal(claim.order_id,claimOrder.order_id);assert.equal(claim.supplier_evidence_status,'SUPPLIER_STATEMENT_UNVERIFIED');assert.equal(claim.status,'AWAITING_CUSTOMER');assert.equal(workspace.actor_type,'SUPPLIER_USER');assert.equal(workspace.cases.length,1);assert.deepEqual(workspace.cases[0].actions,[]);
   await supplier.getByText('车损记录',{exact:true}).waitFor();await supplier.getByText('等待消费者回应 · 版本 1',{exact:true}).waitFor();assert.equal(await supplier.locator('[data-rental-command="DECISION"]').count(),0);report.facts.supplier_claim={claim,workspace};damageCase=claim;
  });
  await step('consumer-disputes-supplier-damage-claim',consumer,async()=>{
   await consumer.locator('[data-rental-operations] [data-refresh-operations]').click();
   const result=await caseCommand(consumer,claimOrder.order_id,damageCase.case_id,'RESPONSE','隔离验收：不同意供应商车损申报，请独立核对。');
   assert.equal(result.claim.status,'REVIEW_REQUIRED');damageCase=result.claim;report.facts.damage_dispute=result;
  });
  await step('independent-administrator-decides-damage',checker,async()=>{
   await adminRental(checker,claimOrder.order_id);
   const result=await caseCommand(checker,claimOrder.order_id,damageCase.case_id,'DECISION','隔离验收：独立核对陈述后裁决80元。',8000);
   assert.equal(result.claim.status,'ADJUDICATED');assert.equal(result.claim.awarded_minor,8000);
   assert.notEqual(result.claim.reviewer_id,result.claim.opened_by);assert.notEqual(result.claim.reviewer_id,result.claim.responded_by);
   damageCase=result.claim;report.facts.damage_decision=result;
  });
  await step('administrator-settles-damage-and-releases-balance',maker,async()=>{
   await adminRental(maker,claimOrder.order_id);
   const result=await finance(maker,claimOrder.order_id,obligation.obligation_id,'settle','执行已裁决结算');
   const m=result.snapshot.money;assert.equal(m.state,'SETTLED');assert.equal(m.captured_minor,8000);assert.equal(m.released_minor,obligation.source.amount_minor-8000);assert.equal(m.remaining_minor,0);assert.equal(m.compensated_minor,0);assert.equal(m.net_captured_minor,8000);
   report.facts.deposit_settlement=result;
  });
  await step('consumer-sees-settlement-and-appeals',consumer,async()=>{
   report.facts.consumer_settled_funds=await consumerFunds(consumer,claimOrder.order_id,obligation.obligation_id,{state:'SETTLED',captured_minor:8000,released_minor:obligation.source.amount_minor-8000,compensated_minor:0,net_captured_minor:8000,remaining_minor:0});
   await consumer.locator('[data-rental-operations] [data-refresh-operations]').click();
   const result=await caseCommand(consumer,claimOrder.order_id,damageCase.case_id,'APPEAL','隔离验收：对80元裁决提出申诉，请另一独立管理员复核。');
   assert.equal(result.claim.status,'APPEAL_REVIEW_REQUIRED');assert.equal(result.claim.money_instruction_state,'DISPUTE_HOLD');damageCase=result.claim;report.facts.damage_appeal=result;
  });
  await step('another-administrator-reduces-award',appealChecker,async()=>{
   await adminRental(appealChecker,claimOrder.order_id);
   const result=await caseCommand(appealChecker,claimOrder.order_id,damageCase.case_id,'APPEAL_DECISION','隔离验收：另一独立管理员复核，责任减至30元。',3000);
   assert.equal(result.claim.status,'ADJUDICATED');assert.equal(result.claim.awarded_minor,3000);
   const history=result.claim.decision_history;assert.equal(history.length,2);assert.notEqual(history[0].reviewer_id,history[1].reviewer_id);
   assert.notEqual(result.claim.reviewer_id,result.claim.opened_by);damageCase=result.claim;report.facts.damage_appeal_decision=result;
  });
  await step('administrator-compensates-reduced-award',maker,async()=>{
   const before=await adminRental(maker,claimOrder.order_id);assert.equal(before.money.net_captured_minor,8000);
   const result=await finance(maker,claimOrder.order_id,obligation.obligation_id,'compensate','执行申诉减收补偿');
   const m=result.snapshot.money;assert.equal(m.state,'SETTLED');assert.equal(m.captured_minor,8000);assert.equal(m.released_minor,obligation.source.amount_minor-8000);assert.equal(m.compensated_minor,5000);assert.equal(m.net_captured_minor,3000);assert.equal(m.remaining_minor,0);
   report.facts.deposit_compensation=result;
  });
  await step('consumer-sees-compensation-and-net-damage-charge',consumer,async()=>{
   report.facts.consumer_compensated_funds=await consumerFunds(consumer,claimOrder.order_id,obligation.obligation_id,{state:'SETTLED',captured_minor:8000,released_minor:obligation.source.amount_minor-8000,compensated_minor:5000,net_captured_minor:3000,remaining_minor:0});
   await consumer.waitForFunction(value=>document.querySelector('[data-deposit-compensated]')?.textContent===value,amount(5000));
   await consumer.locator('[data-rental-operations] [data-refresh-operations]').click();await consumer.getByText('前次裁决 80.00 CNY · 当前复核 30.00 CNY。',{exact:true}).waitFor();assert.equal(new Set(Object.values(report.facts.admin_actors)).size,3);
  });
 }else report.not_verified.push('SUPPLIER_CLAIM_NO_RENTAL_CREDENTIAL_FIXTURE');
 assert.ok(suppliers.ATTRACTION,'Bound attraction supplier credential required');
 if(!maker)maker=await page('admin',ops.maker,1440);if(!checker)checker=await page('admin',ops.checker,1440);
 attractionSupplier=await page('supplier',suppliers.ATTRACTION,1440);
 await step('attraction-operations-new-order',consumer,async()=>{
  await consumer.goto(origin+'/go-app/');await consumer.locator('[data-home-vertical=ATTRACTION]').click();await consumer.locator('#adest').fill('东京');await consumer.locator('#adate').fill(day(45));await consumer.locator('#ago').click();await consumer.locator('[data-attr="tokyo_skytree"] button').click();
  const d=consumer.locator('dialog[open]');await d.locator('#goPartyCount').selectOption('1');await d.locator('#goPartySession').selectOption('16:00');await consentDialog(consumer,'选择门票人数与场次');await consentDialog(consumer,'核对门票出行资料');
  const created=waitResponse(consumer,'/v1/attractions/orders','POST');await consentDialog(consumer,'核对门票与总价');const order=await data(await created);assert.equal(order.status,'PAYMENT_PENDING');
  const paid=waitResponse(consumer,`/v1/consumer/checkout/ATTRACTION/${order.order_id}`,'POST'),fresh=waitResponse(consumer,`/v1/attractions/orders/${order.order_id}`);
  await consentDialog(consumer,'确认门票订单');await data(await paid);managedAttraction=await data(await fresh);assert.equal(managedAttraction.status,'CONFIRMED');await consumer.locator('#achg').waitFor();report.facts.attraction_operations_order=managedAttraction;
 });
 await step('consumer-requests-attraction-date-change',consumer,async()=>{
  await consumer.locator('#achg').click();await consumer.locator('#newVisitDate').fill(day(46));
  const quoted=waitResponse(consumer,`/v1/attractions/orders/${managedAttraction.order_id}/change-quote`,'POST');await consumer.locator('#uxConfirm').click();attractionQuote=await data(await quoted);
  await consumer.getByRole('heading',{name:'确认改期',exact:true}).waitFor();
  const applied=waitResponse(consumer,`/v1/attractions/orders/${managedAttraction.order_id}/execute-change/${attractionQuote.quote_id}`,'POST'),fresh=waitResponse(consumer,`/v1/attractions/orders/${managedAttraction.order_id}`);
  await consumer.locator('#uxConfirm').click();await data(await applied);const order=await data(await fresh);assert.equal(order.status,'UNKNOWN_EXTERNAL_STATE');assert.equal(order.visit_date,day(45));assert.equal(await consumer.locator('#ared').isDisabled(),true);report.facts.attraction_pending_change={quote:attractionQuote,order};
 });
 await step('attraction-supplier-confirms-change-receipt',attractionSupplier,async()=>{
  await attractionSupplier.locator('a[href="#/attraction-orders"]:visible').first().click();await attractionSupplier.getByText(managedAttraction.order_id,{exact:true}).click();await attractionSupplier.locator('[data-ticket-form]').waitFor();
  await ticketWork(attractionSupplier,managedAttraction.order_id,'REGISTER','隔离验收：登记消费者改期');await ticketWork(attractionSupplier,managedAttraction.order_id,'CLAIM','隔离验收：所属供应商领取');
  const result=await ticketWork(attractionSupplier,managedAttraction.order_id,'RECEIPT','隔离验收：改期已确认的供应商陈述',{state:'CONFIRMED',evidence_reference:'isolated://browser-attraction-change',supplier_reference:'BROWSER-ATTR-CHANGE',voucher_code:'BROWSER-ATTR-VOUCHER',quote_id:attractionQuote.quote_id});
  assert.equal(result.workflow.stage,'RECEIPT_RECORDED');report.facts.attraction_change_receipt=result;
 });
 await step('administrator-applies-attraction-change',maker,async()=>{
  await adminAttraction(maker,managedAttraction.order_id);const result=await ticketWork(maker,managedAttraction.order_id,'APPLY','隔离验收：按已登记精确报价回执应用');assert.equal(result.workflow.stage,'APPLIED');
  await maker.getByText('BROWSER-ATTR-VOUCHER',{exact:false}).first().waitFor();const row=await attractionOrderRow(maker,managedAttraction.order_id,'已确认');await row.getByText('BROWSER-ATTR-VOUCHER',{exact:true}).waitFor();await row.getByText(day(46),{exact:true}).waitFor();report.facts.attraction_change_application=result;
 });
 await step('consumer-sees-confirmed-attraction-change',consumer,async()=>{
  const order=await reopenAttraction(consumer,managedAttraction.order_id);assert.equal(order.status,'CONFIRMED');assert.equal(order.visit_date,day(46));assert.equal(order.voucher_code,'BROWSER-ATTR-VOUCHER');await consumer.getByText('BROWSER-ATTR-VOUCHER',{exact:true}).waitFor();report.facts.attraction_changed_consumer=order;
 });
 await step('independent-administrator-verifies-attraction-change',checker,async()=>{
  await adminAttraction(checker,managedAttraction.order_id);const verified=await ticketWork(checker,managedAttraction.order_id,'VERIFY','隔离验收：独立核对消费者日期凭证与资金');assert.equal(verified.workflow.stage,'VERIFIED');
  const closed=await ticketWork(checker,managedAttraction.order_id,'FOLLOW_UP','隔离验收：改期消费者界面已核对，关闭本轮');assert.equal(closed.workflow.stage,'CLOSED');report.facts.attraction_change_closed=closed;
 });
 await step('attraction-supplier-records-closure',attractionSupplier,async()=>{
  await attractionSupplier.locator('[data-ticket-reload]').click();await attractionSupplier.getByText('工作流 CLOSED',{exact:false}).first().waitFor();
  await ticketWork(attractionSupplier,managedAttraction.order_id,'REGISTER','隔离验收：新一轮供应商闭园登记');await ticketWork(attractionSupplier,managedAttraction.order_id,'CLAIM','隔离验收：所属供应商领取闭园处理');
  const result=await ticketWork(attractionSupplier,managedAttraction.order_id,'RECEIPT','隔离验收：闭园无法履约陈述',{state:'CLOSED_BY_SUPPLIER',evidence_reference:'isolated://browser-attraction-closed'});assert.equal(result.workflow.stage,'RECEIPT_RECORDED');report.facts.attraction_closure_receipt=result;
 });
 await step('administrator-applies-attraction-closure',maker,async()=>{
  await adminAttraction(maker,managedAttraction.order_id);const result=await ticketWork(maker,managedAttraction.order_id,'APPLY','隔离验收：应用闭园，尚未退款不得关闭');assert.equal(result.workflow.stage,'APPLIED');await attractionOrderRow(maker,managedAttraction.order_id,'供应商闭园');report.facts.attraction_closure_application=result;
 });
 await step('consumer-confirms-full-closure-refund',consumer,async()=>{
  const current=await reopenAttraction(consumer,managedAttraction.order_id);assert.equal(current.status,'CLOSED_BY_SUPPLIER');assert.equal(await consumer.locator('#ared').isDisabled(),true);
  const quoted=waitResponse(consumer,`/v1/attractions/orders/${managedAttraction.order_id}/refund-quote`);await consumer.locator('#aref').click();const quote=await data(await quoted);assert.equal(quote.reason,'SUPPLIER_CLOSED');assert.equal(quote.refund_amount_minor,managedAttraction.total_amount_minor);
  const refunded=waitResponse(consumer,`/v1/attractions/orders/${managedAttraction.order_id}/refund-confirmed`,'POST'),fresh=waitResponse(consumer,`/v1/attractions/orders/${managedAttraction.order_id}`);
  await consumer.locator('#uxConfirm').click();const response=await refunded;assert.deepEqual(response.request().postDataJSON(),{quote_hash:quote.quote_hash,confirmed:true});const receipt=await data(response),order=await data(await fresh);
  assert.equal(receipt.status,'REFUND_COMPLETED');assert.equal(receipt.refund_amount_minor,quote.refund_amount_minor);assert.equal(order.status,'REFUNDED');assert.equal(order.voucher_code,null);await consumer.getByText('已退款',{exact:true}).first().waitFor();report.facts.attraction_closure_refund={quote,receipt,order};
 });
 await step('independent-administrator-verifies-refund-and-closes',checker,async()=>{
  const view=await adminAttraction(checker,managedAttraction.order_id);assert.equal(view.order.money_summary.verified,true);assert.equal(view.order.money_summary.refunded_minor,managedAttraction.total_amount_minor);assert.equal(view.order.money_summary.net_minor,0);
  const verified=await ticketWork(checker,managedAttraction.order_id,'VERIFY','隔离验收：独立核对原订单全额退款资金');assert.equal(verified.workflow.stage,'VERIFIED');const closed=await ticketWork(checker,managedAttraction.order_id,'FOLLOW_UP','隔离验收：消费者已见退款，关闭闭园处理');assert.equal(closed.workflow.stage,'CLOSED');const row=await attractionOrderRow(checker,managedAttraction.order_id,'已退款');assert.ok(!(await row.innerText()).includes('BROWSER-ATTR-VOUCHER'));await checker.locator('[data-ticket-detail]').getByText('凭证 已退款，不可使用',{exact:false}).waitFor();assert.equal(view.order.voucher_code,null);report.facts.attraction_refund_closed={money:view.order.money_summary,workflow:closed.workflow};
 });
 assert.deepEqual(report.errors,[]);report.result='PASS';
}catch(e){report.result='FAIL';report.error=e.message;process.exitCode=1;}
finally{await fs.writeFile(out+'/results.json',JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify({result:report.result,acceptance:report.acceptance,steps:report.steps.map(({name,result})=>({name,result})),error:report.error}));}
