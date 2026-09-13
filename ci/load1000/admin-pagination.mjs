import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

export async function auditAdminPagination(browser, fixtures, binding, root, users){
  const origin='http://127.0.0.1:4186', out=path.join(root,'admin-pagination');
  await fs.mkdir(out,{recursive:true});
  const context=await browser.newContext({viewport:{width:1440,height:940},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
  await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort('blockedbyclient'));
  const page=await context.newPage();page.setDefaultTimeout(12000);
  const report={candidate_commit:binding.candidate_commit,source_tree_sha256:binding.source_tree_sha256,
    started_at:new Date().toISOString(),environment:'ISOLATED_SQLITE_CHROMIUM',checks:[],responses:[],screenshots:[],result:'HOLD'};
  const pending=[];
  page.on('response',r=>{const u=new URL(r.url());if(u.pathname.startsWith('/internal/v1/admin/operations/verticals/')){
    pending.push(r.json().then(body=>report.responses.push({time:new Date().toISOString(),path:u.pathname,query:u.search,status:r.status(),binding:r.headers()['x-go-source-tree'],body})));}});
  async function capture(name){const file=name+'.png';await page.screenshot({path:path.join(out,file),fullPage:true});report.screenshots.push(file);}
  async function check(name,fn){const r={name,started_at:new Date().toISOString()};report.checks.push(r);try{await fn();r.result='PASS';}catch(e){r.result='FAIL';r.error=e.message;throw e;}finally{r.finished_at=new Date().toISOString();await capture(name);}}
  async function search(oid){
    await page.locator('#adminOrderId').fill(oid);
    const response=page.waitForResponse(r=>new URL(r.url()).pathname.startsWith('/internal/v1/admin/operations/verticals/')&&new URL(r.url()).searchParams.get('order_id')===oid);
    await page.getByRole('button',{name:'查询订单',exact:true}).click();
    const r=await response;assert.equal(r.status(),200);assert.equal(r.headers()['x-go-source-tree'],binding.source_tree_sha256);
    await page.waitForFunction(q=>document.querySelector('#adminOrderId')?.value===q&&document.querySelector('#adminOrderSearch button[type="submit"]')?.disabled===false,oid);
  }
  try{
    await page.goto(origin+'/go-admin/');
    await page.locator('#user').fill(fixtures.credentials.admin.username);await page.locator('#pass').fill(fixtures.credentials.admin.password);
    await page.locator('form#login button[type=submit], form#login button.primary').first().click();await page.locator('.shell').waitFor();
    for(const v of ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']){
      const expected=users.filter(x=>x.vertical===v).flatMap(x=>x.order_checks.map(c=>c.order_id));
      await page.goto(origin+'/go-admin/#/vertical-'+v.toLowerCase());await page.locator('#adminOrderId').waitFor();
      await check(v+'-all-order-pages',async()=>{
        const seen=[];
        for(let n=1;n<=Math.ceil(expected.length/50);n++){
          await page.waitForFunction(n=>document.querySelector('[data-page-summary="orders"]')?.textContent.includes(`第 ${n} /`),n);
          seen.push(...await page.locator('#adminOrders tbody tr td:first-child').allTextContents());
          await capture(v+'-orders-page-'+n);
          if(n<Math.ceil(expected.length/50))await page.locator('[data-page-kind="orders"][data-direction="1"]').click();
        }
        assert.deepEqual([...seen].sort(),[...expected].sort());assert.equal(new Set(seen).size,expected.length);
        assert.ok(await page.locator('[data-page-kind="orders"][data-direction="1"]').isDisabled());
        if(expected.length>50){
          await page.locator('[data-page-kind="orders"][data-direction="-1"]').click();
          await page.waitForFunction(n=>document.querySelector('[data-page-summary="orders"]')?.textContent.includes(`第 ${n} /`),Math.ceil(expected.length/50)-1);
        }
      });
      await check(v+'-all-refund-pages',async()=>{
        const seen=[];
        for(let n=1;n<=Math.ceil(expected.length/50);n++){
          await page.waitForFunction(n=>document.querySelector('[data-page-summary="refunds"]')?.textContent.includes(`第 ${n} /`),n);
          // refund_id is first, order_id second, in the retained public projection.
          seen.push(...await page.locator('#adminRefunds tbody tr td:nth-child(2)').allTextContents());
          if(n<Math.ceil(expected.length/50))await page.locator('[data-page-kind="refunds"][data-direction="1"]').click();
        }
        assert.deepEqual([...seen].sort(),[...expected].sort());assert.equal(new Set(seen).size,expected.length);
        assert.ok(await page.locator('[data-page-kind="refunds"][data-direction="1"]').isDisabled());
      });
      for(const [label,oid] of [['oldest-user',expected[0]],['last-user',expected.at(-1)]])await check(v+'-'+label+'-exact-query',async()=>{
        await search(oid);await page.locator('#adminOrders').getByText(oid,{exact:true}).waitFor();
        assert.equal(await page.locator('#adminOrders tbody tr').count(),1);
        assert.equal(await page.locator('#adminRefunds tbody tr').count(),1);
        for(const width of [375,390,430,1440]){
          await page.setViewportSize({width,height:940});
          assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'horizontal overflow');
          await capture(v+'-'+label+'-'+width);
        }
      });
      await check(v+'-missing-query-clear',async()=>{
        await search('missing-order');await page.getByText('未找到该订单',{exact:true}).waitFor();
        assert.equal(await page.locator('#adminOrders tbody tr').count(),0);
        await page.locator('#adminOrderReset').click();
        await page.waitForFunction(total=>document.querySelector('[data-page-summary="orders"]')?.textContent.includes(`共 ${total} 条`),expected.length);
        assert.equal(await page.locator('#adminOrderId').inputValue(),'');
      });
    }
    await check('failed-query-preserves-controls-and-retries',async()=>{
      const target='missing-after-error';
      await page.route('**/internal/v1/admin/operations/verticals/ATTRACTION?**',r=>{
        if(new URL(r.request().url()).searchParams.get('order_id')===target)return r.fulfill({status:503,contentType:'application/json',body:'{"detail":"ISOLATED_TEST_FAULT"}'});
        return r.continue();
      },{times:1});
      await page.locator('#adminOrderId').fill(target);await page.getByRole('button',{name:'查询订单',exact:true}).click();
      await page.getByText(/订单加载失败，请重试/).waitFor();
      await page.waitForFunction(()=>document.querySelector('#adminOrderSearch button[type="submit"]')?.disabled===false);
      await search(target);await page.getByText('未找到该订单',{exact:true}).waitFor();
    });
    report.result='PASS';
  }catch(error){report.error=String(error.stack||error);report.page_url=page.url();report.visible_text=(await page.locator('body').innerText().catch(()=>'' )).slice(-12000);await capture('failure');}
  finally{await Promise.allSettled(pending);report.finished_at=new Date().toISOString();await fs.writeFile(path.join(out,'result.json'),JSON.stringify(report,null,2)+'\n');await context.close();}
  return report;
}
