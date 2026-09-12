import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const out=process.env.GO_JOURNEY_EVIDENCE, origin='http://127.0.0.1:4186';
const credentials=JSON.parse(await fs.readFile(path.join(process.env.GO_JOURNEY_STATE,'credentials.private.json'),'utf8'));
const source=JSON.parse(await fs.readFile(path.join(out,'source-binding.json'),'utf8'));
const report={schema:'go.real-browser-journeys.v1',started_at:new Date().toISOString(),commit:source.candidate_commit,
  source_tree_sha256:source.source_tree_sha256,environment:'ISOLATED_SQLITE_CHROMIUM',data:'SYNTHETIC_ONLY',
  browser_tests:[],journeys:[],network:[],console_errors:[],limitations:['SQLite; independent PostgreSQL acceptance recorded separately','Simulator payment and supplier adapters; no live inventory, real payments or Hong Kong','Mobile viewport is mobile web, not a native device or Expo build'],
  hong_kong:'NOT_RUN',production:'HOLD',sealed_node_gate:'HOLD',final_release:'HOLD'};
const browser=await chromium.launch({headless:true});
report.browser_version=browser.version();
let seq=0; const orders=[]; const pending=[];
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
async function login(p,role){
  await p.goto(origin+({consumer:'/go-app/',supplier:'/supplier-console/',admin:'/go-admin/'}[role]));
  if(role==='consumer'){
    await p.locator('#accountBtn').click();await p.locator('#email').fill(credentials.consumer.username);await p.locator('#pwd').fill(credentials.consumer.password);
    await Promise.all([p.waitForResponse(r=>r.url().includes('/v1/consumer/auth/login')&&r.ok()),p.locator('#login').click()]);await p.locator('#email').waitFor({state:'detached'});await p.locator('#accountBtn').click();await p.locator('#pvAdd').waitFor();
  }else{
    await p.locator('#user').fill(credentials[role].username);await p.locator('#pass').fill(credentials[role].password);
    await p.locator('form#login button[type=submit], form#login button.primary').first().click();await p.locator('.shell').waitFor();
    assert.match(await p.locator('.actor').innerText(),role==='admin'?/GO_ADMIN/:/SUPPLIER_USER/);
  }
}
async function noOverflow(p){
  const sizes=await p.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
  assert.ok(sizes.document<=sizes.viewport+2,`horizontal overflow ${JSON.stringify(sizes)}`);
}
async function traveler(p,name,rel){
  await p.locator('#pvAdd').click();const d=p.locator('dialog[open]');
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
  for(const el of await d.locator('[data-consent],[data-quote-consent]').all())await el.check();
  const title=await d.locator('h2').first().innerText();await d.locator('[type=submit]').click();
  await p.waitForFunction(old=>!document.querySelector('dialog[open]')||document.querySelector('dialog[open] h2')?.textContent!==old,title);
}
async function home(p,vertical){await p.goto(origin+'/go-app/');await p.locator(`[data-vertical="${vertical}"]`).first().click();}
async function booked(p,vertical,before){
  await p.waitForResponse(r=>r.url().includes(`/v1/consumer/checkout/${vertical}/`)&&r.ok()).catch(async()=>{await Promise.all(pending);assert.ok(orders.slice(before).some(x=>x.vertical===vertical),'checkout response absent');});
  await Promise.all(pending);assert.ok(orders.slice(before).some(x=>x.vertical===vertical),'paid order missing');await noOverflow(p);
}
const consumer=await pageFor('consumer',390),supplier=await pageFor('supplier',1440),admin=await pageFor('admin',1440);
try{
  for(const [role,p]of [['consumer',consumer],['supplier',supplier],['admin',admin]])await scenario(p,`${role}-login`,async()=>{await login(p,role);await noOverflow(p);});
  await scenario(consumer,'vault-two-confirmed-travelers',async()=>{await traveler(consumer,'GO TEST ADULT A','SELF');await traveler(consumer,'GO TEST ADULT B','FAMILY');});
  await scenario(consumer,'HOTEL-search-quote-traveler-payment',async()=>{
    const before=orders.length;await home(consumer,'HOTEL');await consumer.locator('#city').fill('TYO');await consumer.locator('#cin').fill(day(30));await consumer.locator('#cout').fill(day(32));await consumer.locator('#searchBtn').click();
    await consumer.locator('[data-hotel]').first().click();await consumer.locator('[data-offer]').first().click();await consumer.locator('#continue').click();await consumer.locator('#create').click();
    await dialog(consumer);await dialog(consumer);await consumer.locator('#goHotelPay').click();await dialog(consumer);await booked(consumer,'HOTEL',before);
  },'journeys');
  await scenario(consumer,'FLIGHT-roundtrip-two-adults-tickets',async()=>{
    const before=orders.length;await home(consumer,'FLIGHT');await consumer.locator('#jAdults').selectOption('2');
    await consumer.locator('[data-j-field=origin][data-leg="0"]').fill('SHA');await consumer.locator('[data-j-field=destination][data-leg="0"]').fill('PEK');
    await consumer.locator('[data-j-field=departure_date][data-leg="0"]').fill(day(30));await consumer.locator('[data-j-field=departure_date][data-leg="1"]').fill(day(35));
    await consumer.locator('#jSubmit').click();await consumer.locator('[data-select]').last().click();await consumer.locator('[data-select]').last().click();await consumer.locator('#jCompose').click();
    await consumer.locator('#jPrebook').click();await consumer.locator('#jCreate').click();await dialog(consumer);await dialog(consumer);await booked(consumer,'FLIGHT',before);
    await consumer.getByText('GO TEST ADULT A',{exact:false}).first().waitFor();assert.match(await consumer.locator('body').innerText(),/票号/);
  },'journeys');
  await scenario(consumer,'RAIL-two-adults-confirmed',async()=>{
    const before=orders.length;await home(consumer,'RAIL');await consumer.locator('#ro').fill('SHA');await consumer.locator('#rd').fill('HZH');await consumer.locator('#rdate').fill(day(30));await consumer.locator('#rgo').click();await consumer.locator('[data-rail]').first().click();
    await dialog(consumer);await dialog(consumer);await dialog(consumer);await dialog(consumer);await booked(consumer,'RAIL',before);
  },'journeys');
  for(const vertical of ['RIDE','RENTAL'])await scenario(consumer,`${vertical}-traveler-confirmed`,async()=>{
    const before=orders.length;await home(consumer,vertical);await consumer.locator('#m1').fill(vertical==='RIDE'?'PVG':'NRT');await consumer.locator('#m2').fill(vertical==='RIDE'?'上海外滩':'NRT');await consumer.locator('#mt1').fill(day(30)+'T10:00');
    if(vertical==='RENTAL')await consumer.locator('#mt2').fill(day(32)+'T10:00');await consumer.locator('#mgo').click();await consumer.locator('[data-mob]').first().click();await dialog(consumer);await dialog(consumer);await booked(consumer,vertical,before);
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
  for(const width of [375,430,1440])for(const [role,p]of [['consumer',consumer],['supplier',supplier],['admin',admin]])await scenario(p,`${role}-viewport-${width}`,async()=>{await p.setViewportSize({width,height:940});await noOverflow(p);});
  await scenario(supplier,'supplier-owned-order-visibility',async()=>{
    await supplier.goto(origin+'/supplier-console/#/orders');await supplier.locator('#view').waitFor();
    await supplier.getByRole('heading',{name:/订单/}).first().waitFor();
    const html=await supplier.locator('#view').innerText();assert.ok(orders.some(x=>html.includes(x.order_id)),'No journey order visible to supplier: inspect ownership and supported vertical scope');
  });
}finally{
  await Promise.allSettled(pending);report.finished_at=new Date().toISOString();report.failed=report.browser_tests.concat(report.journeys).filter(x=>x.result!=='PASS').map(x=>x.name);
  report.result=report.failed.length?'GAPS_FOUND':'SCOPED_CHECKS_PASS';report.three_end_real_ux_login=report.failed.some(x=>/login|viewport/.test(x))?'HOLD':'ISOLATED_WEB_SCOPED_PASS';
  report.six_vertical_closed_loop='HOLD_PENDING_AFtersales_AND_CROSS_SURFACE';
  await save('browser-results.json',report);await save('synthetic-orders.json',orders);await browser.close();
}
process.exitCode=report.failed.length?1:0;
