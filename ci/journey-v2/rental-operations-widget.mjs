import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const source=fs.readFileSync(new URL('../../application/frontend/shared/rental-operations.js',import.meta.url),'utf8');
const executablePath=process.env.GO_CHROMIUM_EXECUTABLE;
const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
const fixture={order_id:'order1',order_status:'COMPLETED',currency:'CNY',actor_type:'CONSUMER',actor_id:'owner',writes_enabled:true,actions:[],obligation:null,release:null,receipts:[],cases:[{case:{case_id:'case1',version:1,status:'AWAITING_CUSTOMER',claimed_minor:10000,currency:'CNY',awarded_minor:null,appeals:[],decision_reason:'',money_instruction_state:'BLOCKED_PENDING_DECISION'},actions:['RESPONSE']}]};
async function setup(behavior='normal'){
  const page=await browser.newPage({viewport:{width:390,height:844}});
  page.on('pageerror',error=>console.error('widget pageerror:',error.message));
  await page.route('**/*',r=>r.fulfill({contentType:'text/html',body:'<main><section id="widget"></section></main>'}));
  // Match the secure browser context of HTTPS deployments and loopback HTTP.
  // Every request is still intercepted above; this never contacts rental.test.
  await page.goto('https://rental.test/');
  const context=await page.evaluate(()=>({secure:window.isSecureContext,uuid:typeof crypto.randomUUID}));
  assert.deepEqual(context,{secure:true,uuid:'function'},'widget fixture requires native secure-context UUID support');
  await page.evaluate(({fixture,behavior})=>{
    window.state=fixture;window.calls=[];window.behavior=behavior;
    window.request=async(path,options)=>{
      if(!options){return structuredClone(window.state);}
      window.calls.push({path,key:options.headers['Idempotency-Key'],body:structuredClone(options.body)});
      if(window.behavior==='unknown'){throw Error('network lost');}
      if(window.behavior==='stale'){throw Object.assign(Error('conflict'),{status:409});}
      window.state.receipts.push({key:options.headers['Idempotency-Key'],case_id:'case1',version:2});
      window.state.cases[0].case.version=2;window.state.cases[0].case.status='REVIEW_REQUIRED';window.state.cases[0].actions=[];
      return {data:{status:'REVIEW_REQUIRED'}};
    };
  },{fixture:structuredClone(fixture),behavior});
  await page.addScriptTag({content:source});
  await page.evaluate(()=>window.GORentalOperations.render({container:document.querySelector('#widget'),orderId:'order1',request:window.request}));
  return page;
}
async function submit(page){
  await page.locator('[name=statement]').fill('请重新核对取车时已有的划痕。');
  await page.locator('[name=confirmed]').check();
  await page.locator('[data-rental-command=RESPONSE] button').click();
}
try{
 await test('consumer submits current version and authenticated statement then reads current state',async()=>{
   const page=await setup();await submit(page);
   await page.getByText('上次请求已记录。',{exact:false}).waitFor();
   const calls=await page.evaluate(()=>window.calls);assert.equal(calls.length,1);
   assert.equal(calls[0].body.expected_version,1);assert.equal(calls[0].body.response,'DISPUTE');
   assert.equal('actor_id' in calls[0].body,false);assert.equal('sha256' in calls[0].body,false);
   assert.equal(await page.locator('[data-rental-command]').count(),0);
   assert.match(await page.locator('#widget').innerText(),/等待独立审核/);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.close();
 });
 await test('unknown result retains exact command and key across remount and retry',async()=>{
   const page=await setup('unknown');await submit(page);
   await page.locator('[data-retry-operation]').waitFor();
   assert.equal(await page.locator('[data-rental-command]').count(),0);
   await page.evaluate(()=>window.GORentalOperations.render({container:document.querySelector('#widget'),orderId:'order1',request:window.request}));
   await page.locator('[data-retry-operation]').click();
   const calls=await page.evaluate(()=>window.calls);assert.equal(calls.length,2);assert.deepEqual(calls[1],calls[0]);
   assert.match(await page.locator('#widget').innerText(),/结果尚未确认/);
   await page.close();
 });
 await test('stale rejection requires fresh confirmation instead of claiming success',async()=>{
   const page=await setup('stale');await submit(page);
   await page.getByText('本次请求未通过当前权限或版本检查。',{exact:false}).waitFor();
   assert.equal(await page.locator('[data-retry-operation]').count(),0);
   assert.equal(await page.locator('[name=confirmed]').isChecked(),false);
   assert.equal(await page.evaluate(()=>window.calls.length),1);
   await page.close();
 });
 await test('untrusted reason is rendered as text, permissions come from server action list',async()=>{
   const page=await setup();
   await page.evaluate(()=>{window.state.cases[0].case.decision_reason='<img src=x onerror="window.injected=1">';window.state.cases[0].actions=[];});
   await page.locator('[data-refresh-operations]').click();
   assert.equal(await page.locator('#widget img').count(),0);
   assert.equal(await page.locator('[data-rental-command]').count(),0);
   assert.equal(await page.evaluate(()=>window.injected),undefined);
   await page.close();
 });
 await test('disabled browser storage blocks dispatch before unknown retry identity can be lost',async()=>{
   const page=await setup();
   await page.evaluate(()=>{Storage.prototype.setItem=function(){throw Error('quota');};});
   await submit(page);assert.equal(await page.evaluate(()=>window.calls.length),0);
   assert.match(await page.locator('[data-form-error]').innerText(),/尚未提交/);
   await page.close();
 });
}finally{await browser.close();}
