import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs/promises';
import path from 'node:path';
const execute=promisify(execFile);
const review=oid=>`/internal/v1/admin/mobility/rentals/orders/${oid}/deposit-money-review`;
// These supplemental negative/replay requests are explicitly NOT UI actions.
async function negativePost(page,url,body){
  return page.evaluate(async({url,body})=>{
    const csrf=document.cookie.split('; ').find(x=>x.startsWith('go_csrf='))?.slice(8);
    const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-GO-Actor':'GO_ADMIN','X-GO-Session':'console','X-CSRF-Token':decodeURIComponent(csrf||'')},body:JSON.stringify(body)});
    return {status:response.status,body:await response.json()};
  },{url,body});
}
export async function compensationDepth(c,consumer,h){
  const {report,scenario,pages,read}=c;
  const result=report.compensation={schema:'go.rental-compensation-browser.v1',commit:report.commit,
    source_tree_sha256:report.source_tree_sha256,scope:'ISOLATED_HTTP_SYNTHETIC',complete:false,
    unknown_recovery:'NOT_IMPLEMENTED_NO_TRUSTED_RECEIPT',negative_api_checks:[]};
  let requestBody,requestUrl;
  await scenario(consumer,'round4-compensation-settled-appeal-independent-review-real-ui',async()=>{
    const oid=await h.book(c,consumer,'RENTAL');result.order_id=oid;
    const obligation=await h.acceptedDeposit(c,consumer,oid);result.obligation_id=obligation.obligation_id;
    await h.adminRental(c,pages.maker,oid);await h.finance(c,pages.maker,oid,'授权押金','AUTHORIZED');
    await h.completeRental(c,consumer,oid);await h.adminRental(c,pages.maker,oid);
    await h.command(c,pages.maker,oid,'OPEN',{amount_minor:10000,pickup_statement:'补偿隔离演练：取车时无本项痕迹',return_statement:'补偿隔离演练：申报痕迹待客人回应'});
    await h.consumerRefresh(consumer);await h.command(c,consumer,oid,'RESPONSE',{response:'DISPUTE',statement:'补偿隔离演练：不同意申报，要求独立审核。'});
    await h.adminRental(c,pages.checker,oid);await h.command(c,pages.checker,oid,'DECISION',{award_minor:4000,statement:'隔离初审：核对双方陈述，裁决40元。'});
    await h.adminRental(c,pages.maker,oid);result.before=await h.finance(c,pages.maker,oid,'执行已裁决结算','SETTLED');
    assert.equal(result.before.money.captured_minor,4000);assert.equal(result.before.money.remaining_minor,0);
    // Existing disposable database only, opened read-only. This is evidence
    // capture between UI stages, never a database mutation or a fixture reset.
    const python=process.env.GO_JOURNEY_PYTHON;assert.ok(python,'runner-bound Python interpreter required');
    await execute(python,[fileURLToPath(new URL('./compensation-ledger.py',import.meta.url)),'snapshot',process.env.GO_JOURNEY_STATE,process.env.GO_JOURNEY_EVIDENCE,oid,obligation.obligation_id],{timeout:30000});
    await h.consumerRefresh(consumer);const appealed=await h.command(c,consumer,oid,'APPEAL',{statement:'已经结算后发现新陈述，申请另一审核人复核并减少费用。'});
    assert.equal(appealed.cases[0].case.status,'APPEAL_REVIEW_REQUIRED');
    result.during_appeal=await read(pages.maker,review(oid));
    assert.ok(result.during_appeal.decisions.every(item=>!item.can_compensate));
    assert.equal(result.during_appeal.money.captured_minor,4000);assert.equal(result.during_appeal.money.compensated_minor,0);
    await h.adminRental(c,pages.checker,oid);assert.equal(await pages.checker.locator('[data-rental-command=APPEAL_DECISION]').count(),0);
    await h.adminRental(c,pages.maker,oid);assert.equal(await pages.maker.locator('[data-rental-command=APPEAL_DECISION]').count(),0);
    await h.adminRental(c,pages.appeal_checker,oid);result.reviewed_case=await h.command(c,pages.appeal_checker,oid,'APPEAL_DECISION',{award_minor:1000,statement:'隔离独立复核：根据补充陈述将应收减为10元；该裁决本身不代表资金已补偿。'});
    await h.adminRental(c,pages.maker,oid);const ready=await read(pages.maker,review(oid));
    assert.equal(ready.money.compensated_minor,0);assert.equal(ready.money.captured_minor,4000);
    const decision=ready.decisions.find(item=>item.can_compensate);assert.ok(decision);assert.equal(decision.compensation.amount_minor,3000);
    const request=pages.maker.waitForRequest(r=>r.method()==='POST'&&new URL(r.url()).pathname.endsWith('/compensate'));
    try{result.after=await h.finance(c,pages.maker,oid,'执行申诉减收补偿','SETTLED');}
    catch(error){result.financial_failure={error:error.message,screenshot:await c.capture(pages.maker,'round4-compensation-actual-operator-failure'),visible_text:(await pages.maker.locator('body').innerText()).slice(-7000)};throw error;}
    const actual=await request;requestBody=actual.postDataJSON();requestUrl=new URL(actual.url()).pathname;
    assert.equal('amount_minor' in requestBody,false,'amount is derived by server, never operator-submitted');
    assert.equal(result.after.money.captured_minor,4000);assert.equal(result.after.money.compensated_minor,3000);assert.equal(result.after.money.net_captured_minor,1000);assert.equal(result.after.money.remaining_minor,0);
    assert.equal(result.after.money.released_minor,result.before.money.released_minor);
    for(const original of result.before.movements)assert.deepEqual(result.after.movements.find(m=>m.movement_id===original.movement_id),original);
    await h.adminRental(c,pages.maker,oid);assert.equal(await pages.maker.getByRole('button',{name:'执行申诉减收补偿',exact:true}).count(),0);
    await consumer.locator('[data-deposit-refresh]').click();await consumer.locator('[data-deposit-money-state]').getByText('测试资金处理已完成',{exact:true}).waitFor();
    await consumer.locator('[data-deposit-compensated]').filter({hasText:'30.00'}).waitFor();
    await consumer.locator('[data-deposit-net-captured]').filter({hasText:'10.00'}).waitFor();
    result.consumer_display={compensated:await consumer.locator('[data-deposit-compensated]').innerText(),net_captured:await consumer.locator('[data-deposit-net-captured]').innerText()};
    assert.equal(result.consumer_display.compensated.replace(/[^\d.-]/g,''),'30.00');
    assert.equal(result.consumer_display.net_captured.replace(/[^\d.-]/g,''),'10.00');
    const money=await read(consumer,`/v1/mobility/rentals/orders/${oid}/deposit-money/${obligation.obligation_id}?expected_revision=${obligation.revision}&expected_source_hash=${obligation.source_hash}`);
    assert.equal(money.compensated_minor,3000);assert.equal(money.net_captured_minor,1000);
    result.ui_flow_complete=true;
  },'journeys');
  await scenario(pages.maker,'round4-compensation-replay-stale-readonly-no-extra-effects',async()=>{
    assert.equal(result.ui_flow_complete,true);
    const first=await read(pages.maker,review(result.order_id));
    const replay=await negativePost(pages.maker,requestUrl,requestBody);assert.equal(replay.status,200,JSON.stringify(replay.body));
    result.negative_api_checks.push({kind:'EXACT_REPLAY',status:200});
    const stale=await negativePost(pages.maker,requestUrl,{...requestBody,expected_case_version:requestBody.expected_case_version-1});assert.equal(stale.status,409);
    result.negative_api_checks.push({kind:'STALE_VERSION',status:409});
    const denied=await negativePost(pages.readonly,requestUrl,requestBody);assert.equal(denied.status,403);
    result.negative_api_checks.push({kind:'READONLY_ACTOR',status:403});
    const final=await read(pages.maker,review(result.order_id));assert.deepEqual(final.money,first.money);assert.deepEqual(final.movements,first.movements);
    result.no_duplicate_effects=true;
  },'journeys');
  await scenario(consumer,'round4-compensation-required-completion',async()=>{
    assert.equal(result.ui_flow_complete,true);assert.equal(result.no_duplicate_effects,true);
    assert.equal(result.negative_api_checks.length,3);result.complete=true;
  });
  await fs.writeFile(path.join(process.env.GO_JOURNEY_EVIDENCE,'compensation-browser.json'),JSON.stringify(result,null,2)+'\n');
}
