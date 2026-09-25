import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { selectDateRange } from './date-range.mjs';

const policyBase='/internal/v1/ride-policy-operations';
const moneyUrl=oid=>`/internal/v1/admin/mobility/rentals/orders/${oid}/deposit-money-review`;
const operationsUrl=oid=>`/v1/mobility/rentals/orders/${oid}/operations`;

// All business mutations below are actual UI submissions. Fixture setup seeds
// identities only; these accounts and this state never leave the disposable run.
export async function prepareOperations(ctx) {
  const {pageFor,login,scenario,origin,read,report}=ctx;
  const accounts=JSON.parse(await fs.readFile(path.join(process.env.GO_JOURNEY_STATE,'operations.private.json'),'utf8'));
  const pages={};
  report.operations={schema:'go.operations-browser.v1',commit:report.commit,source_tree_sha256:report.source_tree_sha256,scope:'ISOLATED_HTTP_SYNTHETIC',complete:false,
    original_journeys_preserved:true,policy:[],rentals:[],limitations:['No real PSP or supplier','SQLite browser flow; PostgreSQL evidence is separate']};
  for(const role of ['maker','checker','appeal_checker','readonly']) {
    pages[role]=await pageFor('operations-'+role,1440);
    await scenario(pages[role],`operations-${role}-login`,()=>login(pages[role],'admin',accounts[role]));
  }
  const ops={...ctx,pages};
  await scenario(pages.maker,'operations-policy-initial-two-offer-ui-activation',async()=>{
    for(const offer of ['ride_standard','ride_premium']) {
      const row=await draft(ops,offer,`browser-initial-${offer}`,0);
      await policyPage(ops,pages.maker);
      const self=pages.maker.locator(`[data-version="${row.policy_id}"]`);
      assert.equal(await self.getByRole('button',{name:'由另一管理员激活工程版本',exact:true}).count(),0,'self-approval action is absent');
      // Independent negative API check; not counted as a UI mutation.
      const denied=await pages.maker.evaluate(async ({url,revision})=>{
        const csrf=document.cookie.split('; ').find(x=>x.startsWith('go_csrf='))?.slice(8);
        const r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-GO-Actor':'GO_ADMIN','X-GO-Session':'console','X-CSRF-Token':decodeURIComponent(csrf||'')},body:JSON.stringify({revision})});return r.status;
      },{url:`${policyBase}/${row.policy_id}/activate`,revision:row.revision});
      assert.equal(denied,409,'maker cannot activate own draft');
      assert.equal((await read(pages.maker,policyBase)).offers.find(o=>o.offer_id===offer).versions.find(v=>v.policy_id===row.policy_id).state,'DRAFT');
      await transition(ops,row,'activate',pages.checker);
      report.operations.policy.push({offer,policy_id:row.policy_id,state:'ACTIVE',maker_self_activation:'DENIED_409'});
    }
    const state=await read(pages.checker,policyBase);
    assert.equal(state.registry_enabled,true);assert.ok(state.offers.every(o=>o.state==='ISOLATED_READY'));
  },'journeys');
  return ops;
}

async function policyPage(c,p){
  await p.goto(c.origin+'/go-admin/#/ride-policy-operations');
  await p.getByRole('heading',{name:'用车取消政策运营',exact:true}).waitFor();
  // Navigating to the same hash is not a new render. Another administrator may
  // have changed the registry since this page was opened. Refresh via the real
  // workspace control, then wait for its authoritative read and completed draw.
  const refresh=p.locator('#view [data-refresh]:not([disabled])');
  await refresh.waitFor();
  const response=p.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname===policyBase);
  await refresh.click();const r=await response;assert.ok(r.ok(),await r.text());
  const snapshot=(await r.json()).data;
  await refresh.waitFor();
  assert.equal(snapshot.registry_enabled,true);
  await p.locator('[data-draft=ride_standard]').waitFor();
  return snapshot;
}
async function draft(c,offer,version,after){
  const p=c.pages.maker;await policyPage(c,p);const f=p.locator(`[data-draft="${offer}"]`);
  for(const [name,value] of Object.entries({version,hours:'24',before:'0',after:String(after),from:c.day(-2)+'T00:00',until:c.day(90)+'T23:59'}))await f.locator(`[name="${name}"]`).fill(value);
  await f.locator('[name=consent]').check();
  const response=p.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname===policyBase+'/drafts');
  await f.getByRole('button',{name:'提交草稿',exact:true}).click();const r=await response;assert.ok(r.ok(),await r.text());
  const data=await c.read(p,policyBase);const row=data.offers.find(o=>o.offer_id===offer).versions.find(v=>v.policy.version===version);
  assert.ok(row);assert.equal(row.state,'DRAFT');return row;
}
async function transition(c,row,action,p){
  const snapshot=await policyPage(c,p);
  const current=snapshot.offers.flatMap(o=>o.versions).find(v=>v.policy_id===row.policy_id);
  assert.ok(current,'fresh policy snapshot must contain the target version');
  assert.equal(current[action==='activate'?'can_activate':'can_revoke'],true,'fresh actor authority must allow the requested action');
  const f=p.locator(`[data-version="${row.policy_id}"]`);await f.locator('[data-confirm]').check();
  const response=p.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname===`${policyBase}/${row.policy_id}/${action}`);
  await f.getByRole('button',{name:action==='activate'?'由另一管理员激活工程版本':'撤销此版本',exact:true}).click();const r=await response;assert.ok(r.ok(),await r.text());
  const state=await c.read(p,policyBase);assert.equal(state.offers.flatMap(o=>o.versions).find(v=>v.policy_id===row.policy_id).state,action==='activate'?'ACTIVE':'REVOKED');
}
async function book(c,p,vertical){
  await c.home(p,vertical);await p.locator('#m1').fill(vertical==='RENTAL'?'NRT':'PVG');await p.locator('#m2').fill(vertical==='RENTAL'?'NRT':'上海外滩');
  if(vertical==='RENTAL')await selectDateRange(p,'#mt1','#mt2',c.day(30)+'T10:00',c.day(32)+'T10:00');
  else await p.locator('#mt1').fill(c.day(30)+'T10:00');
  await p.locator('#mgo').click();await p.locator('[data-mob]').first().click();
  const checkout=p.waitForResponse(r=>new URL(r.url()).pathname.includes('/checkout/'+vertical+'/')&&r.ok());
  if(vertical==='RIDE')await c.dialog(p);await c.dialog(p);await c.dialog(p);
  const response=await checkout;const oid=new URL(response.url()).pathname.split('/')[5];assert.ok(oid);
  await p.locator('#mstart').waitFor();assert.equal((await c.read(p,'/v1/mobility/orders/'+oid)).status,'CONFIRMED');
  return oid;
}
async function acceptedDeposit(c,p,oid){
  await p.locator('[data-deposit-propose]').click();await p.locator('[data-deposit-accept]').click();
  const d=p.locator('dialog[open]');await d.locator('[data-consent]').check();await d.locator('[type=submit]').click();await d.waitFor({state:'detached'});
  await p.locator('[data-deposit-money-state]').getByText('尚未授权',{exact:true}).waitFor();
  const obligation=await c.read(p,`/v1/mobility/rentals/orders/${oid}/deposit-obligation`);assert.equal(obligation.state,'ACTIVATED');return obligation;
}
async function adminRental(c,p,oid){
  await p.goto(c.origin+'/go-admin/#/vertical-rental');
  await p.locator('#adminOrderId').fill(oid);
  const responses=[
    p.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname==='/internal/v1/admin/operations/verticals/RENTAL'&&new URL(r.url()).searchParams.get('order_id')===oid),
    p.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname===operationsUrl(oid)),
    p.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname===moneyUrl(oid))
  ];
  // Exact search already mounts its result. A second click is a second mount,
  // not a readiness barrier. Wait for this search and its two actual reads.
  await p.getByRole('button',{name:'查询订单',exact:true}).click();
  const returned=await Promise.all(responses);
  for(const r of returned)assert.ok(r.ok(),await r.text());
  for(const r of returned.slice(1))assert.equal((await r.json()).data.order_id,oid);
  const workspace=p.locator(`#rentalOperationsWorkspace[data-rental-order-id="${oid}"][data-rental-mount-state="ready"]`);
  await workspace.waitFor();
  await workspace.locator('[data-rental-business] [data-refresh-operations]').waitFor();
  await workspace.locator('[data-rental-finance] [data-refresh]:not([disabled])').waitFor();
}
async function finance(c,p,oid,title,state){
  const workspace=p.locator('[data-rental-finance]');
  const form=workspace.locator('form[data-action]').filter({has:p.getByRole('button',{name:title,exact:true})});
  await form.locator('[data-confirm]').check();
  const response=p.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.includes(`/rentals/orders/${oid}/deposit-money/`));
  await form.getByRole('button',{name:title,exact:true}).click();const r=await response;assert.ok(r.ok(),await r.text());
  const current=await c.read(p,moneyUrl(oid));assert.equal(current.money.state,state);return current;
}
async function command(c,p,oid,action,fields){
  const form=p.locator(`[data-rental-command="${action}"]`);await form.waitFor();
  try{
    for(const [name,value] of Object.entries(fields)){const input=form.locator(`[name="${name}"]`);if(name==='response')await input.selectOption(value);else await input.fill(String(value));}
    await form.locator('[name=confirmed]').check();
    const snapshot=await form.evaluate(f=>({action:f.dataset.rentalCommand,case_id:f.dataset.caseId,
      valid:f.checkValidity(),confirmed:f.elements.namedItem('confirmed').checked,
      values:Object.fromEntries([...f.elements].filter(e=>e.name&&e.name!=='confirmed').map(e=>[e.name,e.value]))}));
    c.report.operations.command_checks??=[];
    c.report.operations.command_checks.push({order_id:oid,...snapshot});
    assert.equal(snapshot.action,action);assert.equal(snapshot.valid,true,'current form must retain valid inputs before real submit');assert.equal(snapshot.confirmed,true);
    for(const [name,value] of Object.entries(fields))assert.equal(snapshot.values[name],String(value),'input must survive mount: '+name);
    const response=p.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.includes(`/rentals/orders/${oid}/operations/`));
    await form.locator('button[type=submit]').click();const r=await response;assert.ok(r.ok(),await r.text());
    return c.read(p,operationsUrl(oid));
  }catch(error){
    c.report.operations.command_failures??=[];
    c.report.operations.command_failures.push({order_id:oid,action,error:error.message,
      screenshot:await c.capture(p,`operations-${action}-actual-actor-failure`),
      visible_text:(await p.locator('body').innerText()).slice(-7000)});
    throw error;
  }
}
async function consumerRefresh(p){await p.locator('[data-refresh-operations]').click();}
async function completeRental(c,p,oid){
  for(const [button,status] of [['#mstart','IN_PROGRESS'],['#mend','COMPLETED']]){
    const response=p.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname===`/v1/mobility/orders/${oid}/fulfillment`);
    await p.locator(button).click();const r=await response;assert.ok(r.ok(),await r.text());
    assert.equal((await c.read(p,'/v1/mobility/orders/'+oid)).status,status);
    if(status==='IN_PROGRESS')await p.locator('#mend:not([disabled])').waitFor();
  }
}
function checkConservation(snapshot,capture){
  const m=snapshot.money;assert.equal(m.currency,'CNY');assert.equal(m.captured_minor,capture);assert.equal(m.remaining_minor,0);
  assert.equal(m.authorized_minor,m.captured_minor+m.released_minor);assert.ok(m.authorized_minor>0);
}

export async function finishOperations(c){
  const {report,scenario,pages,read}=c;
  const consumer=await c.pageFor('operations-consumer',390);await c.login(consumer,'consumer');
  await scenario(consumer,'operations-rental-dispute-appeal-independent-checker-settlement',async()=>{
    const oid=await book(c,consumer,'RENTAL');const obligation=await acceptedDeposit(c,consumer,oid);
    await adminRental(c,pages.maker,oid);await finance(c,pages.maker,oid,'授权押金','AUTHORIZED');
    await completeRental(c,consumer,oid);await adminRental(c,pages.maker,oid);
    let ws=await command(c,pages.maker,oid,'OPEN',{amount_minor:10000,pickup_statement:'隔离演练取车记录：无本项划痕',return_statement:'隔离演练还车记录：申报一处划痕，待客人回应'});
    assert.equal(ws.cases[0].case.status,'AWAITING_CUSTOMER');
    await consumerRefresh(consumer);ws=await command(c,consumer,oid,'RESPONSE',{response:'DISPUTE',statement:'隔离演练：不同意申报，要求独立审核。'});
    assert.equal(ws.cases[0].case.status,'REVIEW_REQUIRED');
    await adminRental(c,pages.maker,oid);assert.equal(await pages.maker.locator('[data-rental-command=DECISION]').count(),0,'maker may not judge own case');
    await adminRental(c,pages.checker,oid);ws=await command(c,pages.checker,oid,'DECISION',{award_minor:8000,statement:'隔离初审：核对双方陈述，裁决80元。'});
    assert.equal(ws.cases[0].case.awarded_minor,8000);
    await consumerRefresh(consumer);ws=await command(c,consumer,oid,'APPEAL',{statement:'隔离演练：申请另一审核人复核裁决金额。'});
    assert.equal(ws.cases[0].case.status,'APPEAL_REVIEW_REQUIRED');
    const held=await read(pages.maker,moneyUrl(oid));assert.ok(held.decisions.every(x=>!x.can_settle));assert.equal(held.money.captured_minor,0);
    await adminRental(c,pages.checker,oid);assert.equal(await pages.checker.locator('[data-rental-command=APPEAL_DECISION]').count(),0,'original checker cannot hear appeal');
    await adminRental(c,pages.appeal_checker,oid);ws=await command(c,pages.appeal_checker,oid,'APPEAL_DECISION',{award_minor:5000,statement:'隔离复核：核对申诉及原审核，裁决50元。'});
    assert.equal(ws.cases[0].case.status,'ADJUDICATED');assert.equal(ws.cases[0].case.awarded_minor,5000);
    await adminRental(c,pages.maker,oid);const settled=await finance(c,pages.maker,oid,'执行已裁决结算','SETTLED');checkConservation(settled,5000);
    await adminRental(c,pages.maker,oid);assert.equal(await pages.maker.getByRole('button',{name:'执行已裁决结算',exact:true}).count(),0);
    assert.deepEqual((await read(pages.maker,moneyUrl(oid))).money,settled.money,'refresh preserves exact settled money');
    const identities=await Promise.all([pages.maker,pages.checker,pages.appeal_checker].map(p=>read(p,'/bff/auth/me')));assert.equal(new Set(identities.map(x=>x.user_id)).size,3);
    report.operations.rentals.push({order_id:oid,obligation_id:obligation.obligation_id,flow:'DISPUTE_APPEAL_SETTLE',workspace:ws,financial:settled});
    for(const width of [375,430,1440]){await pages.maker.setViewportSize({width,height:940});await c.noOverflow(pages.maker);}
  },'journeys');
  await scenario(consumer,'operations-rental-no-damage-reviewed-release',async()=>{
    const oid=await book(c,consumer,'RENTAL');const obligation=await acceptedDeposit(c,consumer,oid);
    await adminRental(c,pages.maker,oid);await finance(c,pages.maker,oid,'授权押金','AUTHORIZED');
    await completeRental(c,consumer,oid);await adminRental(c,pages.checker,oid);
    const ws=await command(c,pages.checker,oid,'RETURN_REVIEW',{statement:'隔离演练：最终还车检查已完成，无损，不再登记本押金车损。'});
    assert.ok(ws.release);await adminRental(c,pages.maker,oid);const released=await finance(c,pages.maker,oid,'释放已核验余额','SETTLED');checkConservation(released,0);
    await adminRental(c,pages.maker,oid);assert.equal(await pages.maker.getByRole('button',{name:'释放已核验余额',exact:true}).count(),0);
    report.operations.rentals.push({order_id:oid,obligation_id:obligation.obligation_id,flow:'NO_DAMAGE_RELEASE',workspace:ws,financial:released});
  },'journeys');
  await scenario(consumer,'operations-policy-replacement-revoke-preserves-accepted-order',async()=>{
    const oid=await book(c,consumer,'RIDE');const before=await read(consumer,'/v1/mobility/orders/'+oid);assert.ok(before.cancellation);
    const newer=await draft(c,'ride_standard','browser-replacement-standard',12);await transition(c,newer,'activate',pages.checker);
    assert.deepEqual((await read(consumer,'/v1/mobility/orders/'+oid)).cancellation,before.cancellation);
    await transition(c,newer,'revoke',pages.checker);
    const diag=await read(pages.checker,policyBase);assert.equal(diag.offers.find(o=>o.offer_id==='ride_standard').state,'HOLD');
    assert.deepEqual((await read(consumer,'/v1/mobility/orders/'+oid)).cancellation,before.cancellation);
    await c.home(consumer,'RIDE');await consumer.locator('#m1').fill('PVG');await consumer.locator('#m2').fill('上海外滩');await consumer.locator('#mt1').fill(c.day(30)+'T10:00');
    const response=consumer.waitForResponse(r=>new URL(r.url()).pathname==='/v1/mobility/rides/search');await consumer.locator('#mgo').click();const res=await response;assert.ok(res.ok(),await res.text());
    const search=(await res.json()).data;const held=search.items.find(o=>o.offer_id==='ride_standard');assert.ok(held);assert.equal(held.cancellation.state,'POLICY_UNAVAILABLE');assert.equal(held.cancellation.cancellable,false);
    report.operations.policy.push({flow:'REPLACE_REVOKE_PRESERVE_OLD',order_id:oid,accepted_cancellation:before.cancellation,replacement_policy_id:newer.policy_id,new_offer:held.cancellation});
  },'journeys');
  await scenario(pages.readonly,'operations-readonly-rejected-no-financial-side-effects',async()=>{
    assert.equal(report.operations.rentals.length,2);const oid=report.operations.rentals[0].order_id;
    const before=await read(pages.maker,moneyUrl(oid));
    // A direct negative read supplements real UI writes, and is not reported as a UI action.
    const denied=await pages.readonly.evaluate(async url=>(await fetch(url,{credentials:'same-origin',headers:{'X-GO-Actor':'GO_ADMIN'}})).status,moneyUrl(oid));
    assert.equal(denied,403);assert.deepEqual((await read(pages.maker,moneyUrl(oid))).money,before.money);
  },'journeys');
  await scenario(consumer,'operations-required-completion',async()=>{
    assert.equal(report.operations.rentals.length,2);assert.equal(report.operations.policy.length,3);
    assert.ok(report.journeys.filter(x=>x.name.startsWith('operations-')).every(x=>x.result==='PASS'));
    report.operations.complete=true;
  });
  await fs.writeFile(path.join(process.env.GO_JOURNEY_EVIDENCE,'operations-order-checks.json'),JSON.stringify(report.operations,null,2)+'\n');
  await Promise.all([...Object.values(pages),consumer].map(p=>p.context().close()));
}
