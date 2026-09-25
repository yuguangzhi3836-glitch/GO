import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { hotelDepth } from './hotel-depth.mjs';
import { selectDateRange } from './date-range.mjs';

const out=process.env.GO_JOURNEY_EVIDENCE, origin='http://127.0.0.1:4186';
const credentials=JSON.parse(await fs.readFile(path.join(process.env.GO_JOURNEY_STATE,'credentials.private.json'),'utf8'));
const source=JSON.parse(await fs.readFile(path.join(out,'source-binding.json'),'utf8'));
const report={schema:'go.real-browser-journeys.v1',started_at:new Date().toISOString(),commit:source.candidate_commit,
  source_tree_sha256:source.source_tree_sha256,environment:'ISOLATED_SQLITE_CHROMIUM',data:'SYNTHETIC_ONLY',
  browser_tests:[],journeys:[],network:[],console_errors:[],limitations:['SQLite; independent PostgreSQL acceptance recorded separately','Simulator payment and supplier adapters; no live inventory, real payments or Hong Kong','Mobile viewport is mobile web, not a native device or Expo build'],
  hong_kong:'NOT_RUN',production:'HOLD',sealed_node_gate:'HOLD',final_release:'HOLD'};
const browser=await chromium.launch({headless:true});
report.browser_version=browser.version();report.node_version=process.version;
report.ci={run_id:process.env.GITHUB_RUN_ID||'UNKNOWN',attempt:process.env.GITHUB_RUN_ATTEMPT||'UNKNOWN',job:process.env.GITHUB_JOB||'UNKNOWN',runner_os:process.env.RUNNER_OS||'UNKNOWN'};
let seq=0; const orders=[]; const pending=[]; const business=[]; const refundRequests=new Map(); const expectedOrders=new Map();
const suppliers=JSON.parse(await fs.readFile(path.join(process.env.GO_JOURNEY_STATE,'suppliers.private.json'),'utf8'));
report.order_checks=[];
const day=n=>new Date(Date.now()+n*86400000).toISOString().slice(0,10);
const save=(name,data)=>fs.writeFile(path.join(out,name),JSON.stringify(data,null,2)+'\n');
async function pageFor(role,width=1440){
  const context=await browser.newContext({viewport:{width,height:940},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort('blockedbyclient'));
  const p=await context.newPage();p.setDefaultTimeout(12000);
  p.on('pageerror',err=>report.console_errors.push({role,width,error:err.message}));
  p.on('response',response=>{
    const url=new URL(response.url());if(!url.pathname.startsWith('/v1/')&&!url.pathname.startsWith('/internal/'))return;
    const item={role,width,time:new Date().toISOString(),method:response.request().method(),path:url.pathname,status:response.status()};report.network.push(item);
    if(/\/(refund-quote|cancellation-quote|refund-confirmed|refund|cancel)$/.test(url.pathname)&&response.ok()){
      pending.push(response.json().then(data=>business.push({path:url.pathname,status:response.status(),data:data.data||data})));
      if(response.request().method()==='POST'&&/\/(refund-confirmed|refund|cancel)$/.test(url.pathname)){
        const req=response.request();const headers=req.headers();
        refundRequests.set(url.pathname,{path:url.pathname,body:req.postData(),headers:Object.fromEntries(Object.entries(headers).filter(([k])=>['content-type','x-csrf-token','x-go-actor','idempotency-key'].includes(k)))});
      }
    }
    // Preserve synthetic business output only; never auth/vault/profile payloads or headers.
    if(/\/checkout\/(HOTEL|FLIGHT|RAIL|RIDE|RENTAL|ATTRACTION)\//.test(url.pathname)&&response.ok())pending.push(response.json().then(data=>{
      const vertical=url.pathname.split('/')[4],id=url.pathname.split('/')[5];
      orders.push({vertical,order_id:id,checkout:data,role,width});
    }));
  });return p;
}
async function capture(p,name){
  const file=`${String(++seq).padStart(3,'0')}-${name}.png`;
  await p.screenshot({path:path.join(out,file),fullPage:true});return file;
}
async function scenario(p,name,fn,kind='browser_tests'){
  const item={name,started_at:new Date().toISOString()};report[kind].push(item);
  try{await fn();item.result='PASS';}catch(e){item.result='FAIL';item.error=e.message;item.visible_text=(await p.locator('body').innerText().catch(()=>'' )).slice(-7000);}
  item.finished_at=new Date().toISOString();item.screenshot=await capture(p,name.replace(/[^a-zA-Z0-9_-]/g,'_')).catch(()=>null);
  await save('browser-results.json',report);console.log(JSON.stringify({name,result:item.result,error:item.error}));return item.result==='PASS';
}
async function login(p,role,account=credentials[role]){
  await p.goto(origin+({consumer:'/go-app/',supplier:'/supplier-console/',admin:'/go-admin/'}[role]));
  if(role==='consumer'){
    await p.locator('#accountBtn').click();await p.locator('#email').fill(credentials.consumer.username);await p.locator('#pwd').fill(credentials.consumer.password);
    await Promise.all([p.waitForResponse(r=>r.url().includes('/v1/consumer/auth/login')&&r.ok()),p.locator('#login').click()]);await p.locator('#email').waitFor({state:'detached'});await p.locator('#accountBtn').click();await p.locator('#vmAdd').waitFor();
  }else{
    await p.locator('#user').fill(account.username);await p.locator('#pass').fill(account.password);
    await p.locator('form#login button[type=submit], form#login button.primary').first().click();await p.locator('.shell').waitFor();
    const identity=await read(p,'/bff/auth/me');assert.equal(identity.actor_type,role==='admin'?'GO_ADMIN':'SUPPLIER_USER');
    if(account.supplier_id)assert.equal(identity.supplier_id,account.supplier_id);
    if(role==='supplier')await p.getByRole('heading',{name:'订单与售后',exact:true}).waitFor();
  }
}
async function noOverflow(p){
  const sizes=await p.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
  assert.ok(sizes.document<=sizes.viewport+2,`horizontal overflow ${JSON.stringify(sizes)}`);
}
async function detailViewports(p,role,vertical){
  report.detail_viewports??=[];
  for(const width of [375,390,430,1440]){
    await p.setViewportSize({width,height:940});await noOverflow(p);
    const item={role,vertical,width,result:'PASS'};
    if(width===375||width===1440)item.screenshot=await capture(p,`${vertical}-${role}-detail-${width}`);
    report.detail_viewports.push(item);
  }
}
async function traveler(p,name,rel){
  await p.locator('#vmAdd').click();const d=p.locator('dialog[open]');
  await d.locator('#pvName').fill(name);await d.locator('#pvRel').selectOption(rel);
  await d.locator('#pvPhone').fill('13800000000');await d.locator('#pvLicense').fill('TEST-LICENSE-ISOLATED');
  await d.locator('[data-confirm]').check();await d.locator('button[type=submit]').click();await d.waitFor({state:'detached'});
  await p.getByRole('heading',{name,exact:true}).waitFor();
}
async function dialog(p,{party}={}){
  const d=p.locator('dialog[open]');await d.waitFor();
  if(await d.locator('#goPartyCount').count())await d.locator('#goPartyCount').selectOption(String(party||2));
  if(await d.locator('#goTraveler').count())await d.locator('#goTraveler').selectOption({index:1});
  const travelers=d.locator('[data-traveler]');for(let i=0;i<Math.min(2,await travelers.count());i++)await travelers.nth(i).check();
  for(const el of await d.locator('[data-consent],[data-quote-consent],[data-policy-consent],[name=cashConfirmed]').all())await el.check();
  const title=await d.locator('h2').first().innerText();await d.locator('[type=submit]').click();
  await p.waitForFunction(old=>!document.querySelector('dialog[open]')||document.querySelector('dialog[open] h2')?.textContent!==old,title);
}
async function home(p,vertical){
  await p.goto(origin+'/go-app/');
  const mobility=['RIDE','RENTAL'].includes(vertical);
  await p.locator(`[data-home-vertical="${mobility?'MOBILITY':vertical}"]`).click();
  if(mobility)await p.locator(vertical==='RIDE'?'#homeRide':'#homeRental').click();
}
async function read(p,url){
  const r=await p.evaluate(async url=>{const r=await fetch(url,{credentials:'same-origin'});return {status:r.status,body:await r.json(),binding:r.headers.get('X-GO-Source-Tree')}},url);
  assert.equal(r.status,200,JSON.stringify(r.body));assert.equal(r.binding,source.source_tree_sha256);return r.body.data;
}
async function booked(p,vertical,before){
  await Promise.all(pending);
  const entries=orders.slice(before).filter(x=>x.vertical===vertical);assert.equal(entries.length,1,'one checkout record required');
  const oid=entries[0].order_id;expectedOrders.set(vertical,oid);await noOverflow(p);
  const endpoint='/v1/consumer/transaction-orders/'+vertical+'/'+oid;
  const original=await read(p,endpoint);
  assert.equal(original.original_payment.capture_count,1);assert.ok(original.original_payment.captured_minor>0);
  if(vertical==='RENTAL'){
  await scenario(p,'RENTAL-deposit-explicit-consent-without-charge',async()=>{
    assert.equal(vertical,'RENTAL');
    await p.locator('[data-deposit-propose]').click();
    await p.locator('[data-deposit-accept]').click();
    const consent=p.locator('dialog[open]');await consent.waitFor();
    const before=report.network.filter(x=>x.method==='POST'&&x.path.endsWith('/accept')&&x.path.includes('/deposit-obligation/')).length;
    await consent.locator('[type=submit]').click();
    assert.equal(await consent.isVisible(),true,'unchecked consent must remain open');
    assert.equal(report.network.filter(x=>x.method==='POST'&&x.path.endsWith('/accept')&&x.path.includes('/deposit-obligation/')).length,before,'no implicit acceptance request');
    await consent.locator('[data-consent]').check();await consent.locator('[type=submit]').click();await consent.waitFor({state:'detached'});
    await p.locator('[data-deposit-money-state]').getByText('尚未授权',{exact:true}).waitFor();
    const obligation=await read(p,`/v1/mobility/rentals/orders/${oid}/deposit-obligation`);
    assert.equal(obligation.state,'ACTIVATED');assert.equal(obligation.financial_state,'NO_FINANCIAL_FACT_ASSERTED');
    assert.equal(obligation.source.external_live,false);
    const financial=await read(p,`/v1/mobility/rentals/orders/${oid}/deposit-money/${obligation.obligation_id}?expected_revision=${obligation.revision}&expected_source_hash=${obligation.source_hash}`);
    assert.equal(financial.state,'NOT_AUTHORIZED');assert.equal(financial.payment_intent_id,null);
    await p.setViewportSize({width:375,height:940});await noOverflow(p);
    await p.locator('[data-deposit-refresh]').click();await p.locator('[data-deposit-money-state]').getByText('尚未授权',{exact:true}).waitFor();
    assert.equal(await p.locator('[data-deposit-accept]').count(),0,'same terms not offered for repeat consent');
  },'journeys');
  }
  await scenario(p,`${vertical}-after-sales-refund`,async()=>{
    const selectors={HOTEL:'#cancel',FLIGHT:'#jRefund',RAIL:'#rref',RIDE:'#mcancel',RENTAL:'#mcancel',ATTRACTION:'#aref'};
    await p.locator(selectors[vertical]).click();
    if(vertical==='HOTEL'){
      const d=p.locator('dialog[open]');await d.locator('[name=cashConfirmed]').waitFor();
      assert.equal(await d.locator('[name=cashConfirmed]').isChecked(),false);
      await d.locator('[type=submit]').click();assert.equal(await d.count(),1,'confirmation must remain required');
      await dialog(p);
    }else{
      const response=p.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.includes('/'+oid+'/')&&/\/(refund-confirmed|refund|cancel)$/.test(new URL(r.url()).pathname));
      await p.locator('#uxConfirm').click();const r=await response;assert.ok(r.ok(),`Refund returned ${r.status()}: ${await r.text()}`);
    }
    await Promise.all(pending);
    const quote=business.filter(x=>x.path.includes('/'+oid+'/')&&/quote$/.test(x.path)).at(-1)?.data;
    assert.ok(quote&&Number.isInteger(quote.refund_amount_minor),'quoted refund amount required');
    const final=await read(p,endpoint),m=final.original_payment;
    assert.ok(['CANCELLED','REFUNDED','REFUND_COMPLETED'].includes(final.order.status),final.order.status);
    assert.equal(m.binding_state,'BOUND');assert.equal(m.captured_minor,original.original_payment.captured_minor);
    assert.equal(m.capture_count,1);assert.equal(m.refund_count,1);assert.equal(m.refunded_minor,quote.refund_amount_minor);
    assert.equal(m.currency,quote.currency);assert.equal(m.net_minor,m.captured_minor-m.refunded_minor);
    assert.ok(m.ledger_balanced&&m.ledger_entries>0);
    assert.equal(final.refunds.length,1);assert.ok(['COMPLETED','REFUND_COMPLETED'].includes(final.refunds[0].status),final.refunds[0].status);
    assert.equal(final.refunds[0].amount_minor,m.refunded_minor);assert.equal(final.refunds[0].currency,m.currency);
    const req=[...refundRequests.values()].find(x=>x.path.includes('/'+oid+'/'));
    assert.ok(req,'original refund request required');
    const replay=await p.evaluate(async req=>{const r=await fetch(req.path,{method:'POST',headers:req.headers,body:req.body,credentials:'same-origin'});return {status:r.status,body:await r.json()}},req);
    assert.equal(replay.status,200,JSON.stringify(replay.body));
    assert.deepEqual(await read(p,endpoint),final,'refund replay must preserve final ledger');
    report.order_checks.push({vertical,order_id:oid,quoted_refund_minor:quote.refund_amount_minor,final,refund_replay:'NO_DUPLICATE'});
  },'journeys');
}

const consumer=await pageFor('consumer',390),supplier=await pageFor('supplier',1440),admin=await pageFor('admin',1440);
try{
  for(const [role,p]of [['consumer',consumer],['supplier',supplier],['admin',admin]])await scenario(p,`${role}-login`,async()=>{await login(p,role);await noOverflow(p);});
  await scenario(consumer,'vault-two-confirmed-travelers',async()=>{await traveler(consumer,'GO TEST ADULT A','SELF');await traveler(consumer,'GO TEST ADULT B','FAMILY');});
  await scenario(consumer,'HOTEL-search-quote-traveler-payment',async()=>{
    const before=orders.length;await home(consumer,'HOTEL');await consumer.locator('#city').fill('TYO');await selectDateRange(consumer,'#cin','#cout',day(30),day(32));await consumer.locator('#searchBtn').click();
    await consumer.locator('[data-hotel]').first().click();await consumer.locator('[data-offer]').first().click();await consumer.locator('#continue').click();await consumer.locator('#create').click();
    await dialog(consumer);await dialog(consumer);await consumer.locator('#goHotelPay').click();await dialog(consumer);await booked(consumer,'HOTEL',before);
  },'journeys');
  await scenario(consumer,'FLIGHT-roundtrip-two-adults-tickets',async()=>{
    const before=orders.length;await home(consumer,'FLIGHT');await consumer.locator('#jAdults').selectOption('2');
    await consumer.locator('[data-j-field=origin][data-leg="0"]').fill('SHA');await consumer.locator('[data-j-field=destination][data-leg="0"]').fill('PEK');
    await consumer.locator('[data-j-field=departure_date][data-leg="0"]').fill(day(30));await consumer.locator('[data-j-field=departure_date][data-leg="1"]').fill(day(35));
    await consumer.locator('#jSubmit').click();await consumer.locator('[data-select]').last().click();await consumer.locator('[data-select]').last().click();await consumer.locator('#jCompose').click();
    await consumer.locator('#jPrebook').click();await consumer.locator('#jCreate').click();await dialog(consumer);await dialog(consumer);await consumer.getByText('GO TEST ADULT A',{exact:false}).first().waitFor();assert.match(await consumer.locator('body').innerText(),/票号/);await booked(consumer,'FLIGHT',before);
  },'journeys');
  await scenario(consumer,'RAIL-two-adults-confirmed',async()=>{
    const before=orders.length;await home(consumer,'RAIL');await consumer.locator('#ro').fill('SHA');await consumer.locator('#rd').fill('HZH');await consumer.locator('#rdate').fill(day(30));await consumer.locator('#rgo').click();await consumer.locator('[data-rail]').first().click();
    await dialog(consumer);await dialog(consumer);await dialog(consumer);await dialog(consumer);await booked(consumer,'RAIL',before);
  },'journeys');
  for(const vertical of ['RIDE','RENTAL'])await scenario(consumer,`${vertical}-traveler-confirmed`,async()=>{
    const before=orders.length;await home(consumer,vertical);await consumer.locator('#m1').fill(vertical==='RIDE'?'PVG':'NRT');await consumer.locator('#m2').fill(vertical==='RIDE'?'上海外滩':'NRT');
    if(vertical==='RENTAL')await selectDateRange(consumer,'#mt1','#mt2',day(30)+'T10:00',day(32)+'T10:00');
    else await consumer.locator('#mt1').fill(day(30)+'T10:00');
    await consumer.locator('#mgo').click();await consumer.locator('[data-mob]').first().click();if(vertical==='RIDE')await dialog(consumer);await dialog(consumer);await dialog(consumer);await booked(consumer,vertical,before);
  },'journeys');
  await scenario(consumer,'ATTRACTION-two-visitors-slot-confirmed',async()=>{
    const before=orders.length;await home(consumer,'ATTRACTION');await consumer.locator('#adest').fill('东京');await consumer.locator('#adate').fill(day(30));await consumer.locator('#ago').click();await consumer.locator('[data-attr]').first().click();
    await dialog(consumer);await dialog(consumer);await dialog(consumer);await dialog(consumer);await booked(consumer,'ATTRACTION',before);
  },'journeys');
  await Promise.all(pending);await save('synthetic-orders.json',orders);
  await scenario(consumer,'consumer-unified-six-vertical-trip-reentry',async()=>{
    await consumer.goto(origin+'/go-app/');await consumer.locator('[data-nav=trips]').first().click();await consumer.locator('[data-go-trip-index]').first().waitFor();
    assert.equal(new Set(orders.map(x=>x.vertical)).size,6,'all six completed checkout records required');
    assert.ok(await consumer.locator('[data-go-trip-index]').count()>=6);await noOverflow(consumer);
  });
  for(const [vertical,oid] of expectedOrders)await scenario(consumer,vertical+'-consumer-refresh-reentry',async()=>{
    await consumer.reload();await consumer.locator('[data-nav=trips]').first().click();
    await consumer.locator('[data-go-trip-index]').first().waitFor();
    const rows=(await read(consumer,'/v1/consumer/unified-trips')).items;
    const index=rows.findIndex(x=>x.order_id===oid&&x.vertical===vertical);assert.ok(index>=0);
    const response=consumer.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname.includes('/'+oid)&&(r.ok()));
    await consumer.locator('[data-go-trip-index="'+index+'"]').click();const r=await response;
    const value=(await r.json()).data;assert.equal(value.order?.order_id||value.order_id,oid);
    await consumer.locator('#tripDetailLoading').waitFor({state:'detached'});await noOverflow(consumer);
    const tested=report.order_checks.find(x=>x.order_id===oid);assert.ok(tested);
    assert.deepEqual(await read(consumer,'/v1/consumer/transaction-orders/'+vertical+'/'+oid),tested.final);
    await detailViewports(consumer,'consumer',vertical);
  });
  for(const width of [375,430,1440])for(const [role,p]of [['consumer',consumer],['supplier',supplier],['admin',admin]])await scenario(p,`${role}-viewport-${width}`,async()=>{await p.setViewportSize({width,height:940});await noOverflow(p);});
  for(const [vertical,oid] of expectedOrders){
    const owner=await pageFor('supplier-'+vertical,390);
    await scenario(owner,vertical+'-supplier-admin-consumer-same-order',async()=>{
      await login(owner,'supplier',suppliers[vertical]);
      const metric=owner.locator('.structured-metric').filter({hasText:'累计订单'});assert.equal(await metric.locator('.metric-value').innerText(),'1');
      assert.ok(!(await owner.locator('#view').innerText()).includes('REFUND_COMPLETED'));
      await owner.goto(origin+'/supplier-console/#/orders');
      await owner.locator('tr[data-i]').filter({hasText:oid}).waitFor();
      await owner.locator('tr[data-i]').filter({hasText:oid}).click();
      await owner.getByRole('heading',{name:'订单详情',exact:true}).waitFor();
      const supplierData=await read(owner,'/v1/supplier/transaction-orders/'+vertical+'/'+oid);
      const consumerData=await read(consumer,'/v1/consumer/transaction-orders/'+vertical+'/'+oid);
      const adminData=await read(admin,'/internal/v1/admin/transaction-orders/'+vertical+'/'+oid);
      assert.deepEqual(supplierData,consumerData);assert.deepEqual(adminData,consumerData);
      const tested=report.order_checks.find(x=>x.order_id===oid);assert.ok(tested,'refund final-state check must pass');assert.deepEqual(tested.final,consumerData);
      await detailViewports(owner,'supplier',vertical);
      await owner.reload();await owner.locator('tr[data-i]').filter({hasText:oid}).waitFor();await noOverflow(owner);
      await admin.goto(origin+'/go-admin/#/vertical-'+vertical.toLowerCase());
      await admin.locator('#view').getByText(oid,{exact:true}).first().waitFor();
      const adminVertical=await read(admin,'/internal/v1/admin/operations/verticals/'+vertical);
      assert.equal(adminVertical.orders.find(x=>x.order_id===oid).status,consumerData.order.status);
      assert.equal(adminVertical.refunds.find(x=>x.order_id===oid).refund_amount_minor,consumerData.refunds[0].amount_minor);
      await detailViewports(admin,'admin',vertical);
      const denied=await supplier.evaluate(async url=>(await fetch(url)).status,'/v1/supplier/transaction-orders/'+vertical+'/'+oid);
      assert.equal(denied,404,'unrelated supplier must remain denied');
      tested.cross_surface='PASS';
    });
    await owner.context().close();
  }
  await hotelDepth({consumer,admin,unrelatedSupplier:supplier,report,origin,read,scenario,home,dialog,day,
    noOverflow,pageFor,login,suppliers,capture,expectedOrders});
  await scenario(consumer,'DEPTH45-required-journey-completion',async()=>{
    assert.equal(report.depth45?.complete,true);assert.equal(report.depth45.search_viewports.length,4);
    assert.equal(report.depth45.payment_viewports.length,4);
    assert.equal(report.cash_journeys.length,1);assert.equal(report.cash_journeys[0].complete,true);
  });
  await scenario(consumer,'no-unhandled-browser-errors',async()=>assert.deepEqual(report.console_errors,[]));
  await save('business-responses.json',business);

}finally{
  await Promise.allSettled(pending);report.finished_at=new Date().toISOString();report.failed=report.browser_tests.concat(report.journeys).filter(x=>x.result!=='PASS').map(x=>x.name);
  report.result=report.failed.length?'GAPS_FOUND':'SCOPED_CHECKS_PASS';report.three_end_real_ux_login=report.failed.length?'HOLD':'ISOLATED_WEB_SCOPED_PASS';
  report.six_vertical_closed_loop=report.order_checks.length===6&&report.order_checks.every(x=>x.cross_surface==='PASS')&&!report.failed.length?'ISOLATED_WEB_SIMULATOR_PASS':'HOLD';
  await save('browser-results.json',report);await save('synthetic-orders.json',orders);await save('business-responses.json',business);await browser.close();
}
process.exitCode=report.failed.length?1:0;
