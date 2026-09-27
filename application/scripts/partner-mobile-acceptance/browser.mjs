import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),{chromium,webkit}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const out=process.env.MOBILE_EVIDENCE_DIR||'/tmp/go-partner-mobile-evidence';await fs.mkdir(out,{recursive:true});
const report={scope:'MOBILE_REPORTED_DEFECTS_ONLY',real_supplier:'NOT_ACCESSED',deployment:'NOT_RUN',independent_C13:'NOT_RUN',native_device:'NOT_RUN',steps:[],errors:[]};
const base='http://127.0.0.1:4288',draft='http://127.0.0.1:4289';
const day=n=>{const d=new Date();d.setDate(d.getDate()+n);return d.toISOString().slice(0,10)};
async function step(name,p,fn){try{await fn();report.steps.push({name,result:'PASS'})}catch(e){report.steps.push({name,result:'FAIL',error:e.message,body:(await p.locator('body').innerText()).slice(-4000)});throw e}finally{await p.screenshot({path:out+'/'+report.steps.length+'.png',fullPage:true});await fs.writeFile(out+'/results.json',JSON.stringify(report,null,2))}}
async function pick(p,start,end){
 const cal=p.locator('.go-date-range');await cal.waitFor();
 for(const value of [start,end]){
  for(let n=0;n<15&&!(await cal.locator(`[data-day="${value}"]`).count());n++)await cal.locator('[data-next]').click();
  await cal.locator(`[data-day="${value}"]`).click();assert.equal(await p.locator('.go-date-range').count(),1);
 }
 assert.equal(await cal.locator('[data-confirm]').isEnabled(),true);
 await cal.screenshot({path:out+'/calendar-'+(report.steps.length+1)+'.png'});
 await cal.locator('[data-confirm]').click();await cal.waitFor({state:'detached'});
}
for(const [engine,type,width] of [['chromium',chromium,375],['webkit',webkit,430]]){
 const browser=await type.launch({headless:true});
 try{
  const context=await browser.newContext({viewport:{width,height:900},isMobile:true,hasTouch:true,locale:'zh-CN',timezoneId:'Asia/Shanghai'});
  await context.route('**/*',r=>[base,draft].includes(new URL(r.request().url()).origin)?r.continue():r.abort());
  const p=await context.newPage();p.setDefaultTimeout(12000);p.on('pageerror',e=>report.errors.push({engine,message:e.message}));
  await step(engine+'-consumer-single-calendar',p,async()=>{
   await p.goto(base+'/go-app/');await p.locator('[data-home-vertical=HOTEL]').click();
   assert.equal(await p.locator('#cin').getAttribute('type'),'text');await p.locator('#cin').click();
   await pick(p,day(4),day(7));assert.equal(await p.locator('#cin').inputValue(),day(4));assert.equal(await p.locator('#cout').inputValue(),day(7));
   await p.locator('#cout').click();await p.locator('[data-close]').click();assert.equal(await p.locator('#cout').inputValue(),day(7));
  });
  await step(engine+'-direct-hotel-single-calendar',p,async()=>{
   await p.goto(base+'/go-app/direct.html');await p.locator('#checkIn').click();await pick(p,day(5),day(9));
   assert.equal(await p.locator('#checkIn').inputValue(),day(5));assert.equal(await p.locator('#checkOut').inputValue(),day(9));
  });
  await step(engine+'-registration-network-retry-and-success',p,async()=>{
   await p.goto(base+'/go-app/');let failed=false;
   await p.route('**/v1/consumer/auth/registration',r=>{if(!failed){failed=true;return r.abort()}return r.continue()});
   await p.locator('#consumerSignupEntry').click();await p.locator('#retryRegistrationRules:not([hidden])').waitFor();
   const email='mobile-'+engine+'-'+Date.now()+'@example.test';
   await p.locator('#regName').fill('隔离手机验收');await p.locator('#regEmail').fill(email);await p.locator('#regPwd').fill('Isolated-register-password');
   await p.locator('#retryRegistrationRules').click();await p.waitForFunction(()=>!document.querySelector('#doRegister').disabled);
   assert.equal(await p.locator('#regName').inputValue(),'隔离手机验收');await p.locator('#regTerms').check();
   await p.locator('#sendRegistrationCode').click();await p.getByText(/验证码已发送/).waitFor();
   const mailbox=JSON.parse(await fs.readFile(process.env.REGISTRATION_TEST_MAILBOX,'utf8'));await p.locator('#registrationCode').fill(mailbox[email]);
   // An auxiliary wallet failure cannot undo successful registration/session readback.
   await p.route('**/v1/consumer/wallet',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'TEST_WALLET_UNAVAILABLE'})}));
   const [registered,session]=await Promise.all([
    p.waitForResponse(r=>r.url()===base+'/v1/consumer/auth/register'&&r.request().method()==='POST'),
    p.waitForResponse(r=>r.url()===base+'/v1/consumer/me'&&r.request().method()==='GET'),
    p.locator('#doRegister').click(),
   ]);
   assert.equal(registered.status(),200);assert.equal((await registered.json()).data.authenticated,true);assert.equal(session.status(),200);
   assert.equal((await session.json()).data.email,email);
   await p.getByRole('heading',{name:'我的旅行资料',exact:true}).waitFor();
   await p.locator('#vmLogout').waitFor();assert.equal(await p.locator('#consumerRegister').count(),0);
  });
  await step(engine+'-registration-draft-explicit-block',p,async()=>{
   await p.goto(draft+'/go-app/');await p.locator('#consumerSignupEntry').click();await p.getByText('注册尚未开放',{exact:true}).waitFor();
   assert.equal(await p.locator('#doRegister').isDisabled(),true);assert.match(await p.locator('#registrationStatus').innerText(),/条款仍待确认/);
  });
  await step(engine+'-supplier-email-verified-registration',p,async()=>{
   await p.goto(base+'/supplier-console/');await p.locator('#supplierRegisterStart').click();
   const email='supplier-'+engine+'-'+Date.now()+'@example.test';
   await p.locator('#org').fill('隔离注册企业');await p.locator('#hotelName').fill('隔离注册酒店');await p.locator('#contact').fill('测试联系人');
   await p.locator('#regEmail').fill(email);await p.locator('#regPass').fill('Isolated-register-password');await p.locator('#acceptTerms').check();
   await p.locator('#sendRegistrationCode').click();await p.getByText(/验证码已发送/).waitFor();
   const mailbox=JSON.parse(await fs.readFile(process.env.REGISTRATION_TEST_MAILBOX,'utf8'));await p.locator('#registrationCode').fill(mailbox[email]);
   const [result]=await Promise.all([p.waitForResponse(r=>r.url()===base+'/bff/auth/supplier/register'),p.locator('#supplierRegisterSubmit').click()]);
   assert.equal(result.status(),201);assert.equal((await result.json()).data.publication_state,'DRAFT');await p.locator('.supplier-shell').waitFor();
   // Clear only this isolated browser context's cookies before testing the fixture owner.
   await context.clearCookies();
  });
  await step(engine+'-supplier-real-login-and-refunds',p,async()=>{
   await p.goto(base+'/supplier-console/');await p.locator('#user').fill('mobile-owner@example.test');await p.locator('#pass').fill('Isolated-mobile-password');await p.locator('#login button').first().click();await p.locator('.supplier-shell').waitFor();
   await p.locator('#view a[href="#/refunds"]').click();await p.getByText('当前没有取消或退款记录。',{exact:true}).waitFor();
   await p.locator('[data-mobile-route="/operations-hub"]').click();await p.locator('#view a[href="#/refunds"]').click();await p.getByText('当前没有取消或退款记录。',{exact:true}).waitFor();
  });
  await step(engine+'-rights-single-entry-multi-program-room-roundtrip',p,async()=>{
   await p.locator('[data-mobile-route="/marketing-rights"]').click();assert.equal(await p.locator('#view a[href="#/direct-value"]').count(),0);
   await p.locator('#view a[href="#/go-identity"]').click();await p.locator('[data-program-form]').waitFor();
   for(const type of ['STAFF_RATE','OWNER_RATE','OWNER_BENEFITS']){const box=p.locator(`[data-program="${type}"]`);await box.locator('[data-enabled]').check();await box.locator('[data-room]').nth(0).check();await box.locator('[data-room]').nth(1).check()}
   await p.locator('[data-program=OWNER_BENEFITS] [data-benefit][value=BREAKFAST]').check();
   await p.locator('[data-program=OWNER_BENEFITS] [data-benefit][value=LATE_CHECKOUT]').check();
   await p.locator('[data-program-form] [type=submit]').click();await p.getByText('项目与房型已保存。',{exact:true}).waitFor();
   await p.reload();await p.locator('[data-program-form]').waitFor();
   for(const type of ['STAFF_RATE','OWNER_RATE','OWNER_BENEFITS']){const box=p.locator(`[data-program="${type}"]`);assert.equal(await box.locator('[data-enabled]').isChecked(),true);assert.equal(await box.locator('[data-room]:checked').count(),2)}
   assert.equal(await p.locator('[data-program=OWNER_BENEFITS] [data-benefit]:checked').count(),2);
   assert.equal(await p.locator('#identityAuth').count(),0);
  });
  await step(engine+'-six-visible-business-workspaces',p,async()=>{
   for(const [type,label] of Object.entries({hotel:'酒店',flight:'机票',rail:'火车票',ride:'接送用车',rental:'租车',attraction:'景点门票'})){
    await p.locator('#supplierMobileMore').click();await p.locator('[data-mobile-menu-route="/business-management"]').click();
    await p.locator(`#view a[href="#/business-${type}"]`).click();await p.getByText('当前没有'+label+'订单。',{exact:true}).waitFor();
    assert.equal(await p.locator('[data-vertical-filter]').inputValue(),type.toUpperCase());
    assert.equal(await p.locator('#supplierPropertySelect').isVisible(),false);
   }
  });
  await step(engine+'-refund-read-failure-retry',p,async()=>{
   let failed=false;await p.route('**/v1/supplier/refunds?*',r=>{if(!failed){failed=true;return r.abort()}return r.continue()});
   await p.locator('#view a[href="#/refunds"]').click();await p.locator('[data-retry]').click();await p.getByText('当前没有取消或退款记录。',{exact:true}).waitFor();
  });
  await step(engine+'-hotel-association-readable-next-action',p,async()=>{
   await p.locator('#supplierMobileMore').click();await p.locator('[data-mobile-menu-route="/business-management"]').click();
   await p.locator('#view a[href="#/hotel-webpage"]').click();await p.getByText('酒店网页尚未关联',{exact:true}).waitFor();
   assert.equal(await p.locator('#supplierPropertySelect').isVisible(),true);
   assert.ok(!(await p.locator('#view').innerText()).includes('NOT_REGISTERED'));await p.getByText('核对酒店与关联状态',{exact:true}).waitFor();
  });
 }catch(e){report.result='FAIL';report.error=e.message;process.exitCode=1}
 finally{await browser.close()}
}
report.result ||= report.errors.length?'FAIL':'PASS';if(report.result==='FAIL')process.exitCode=1;
await fs.writeFile(out+'/results.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
