import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
const source=fs.readFileSync(new URL('../../application/frontend/shared/app.js',import.meta.url),'utf8');
const helper=source.split('/* RENTAL_OPERATIONS_HOST_BEGIN */')[1]?.split('/* RENTAL_OPERATIONS_HOST_END */')[0];
assert.ok(helper,'test must execute the exact product mount helper');
const browser=await chromium.launch({headless:true});
async function setup(){
  const page=await browser.newPage();
  await page.route('**/*',r=>r.fulfill({contentType:'text/html',body:'<section id="workspace"><div data-rental-order-links><button data-rental-order-id="A">A</button><button data-rental-order-id="B">B</button></div><div data-rental-business><form id="old-form"><button>旧订单操作</button></form></div><div data-rental-finance></div></section>'}));
  await page.goto('https://operations-host.test/');
  await page.addScriptTag({content:helper+'\nwindow.makeRentalMount=rentalOperationsMount;'});
  await page.evaluate(()=>{
    const section=document.querySelector('#workspace');window.reads=[];window.releases=[];window.rejects=[];window.oldNodes=[];window.errors=[];window.disposals=0;
    const render=kind=>async({container,orderId})=>{
      window.reads.push({kind,orderId});window.oldNodes.push(container);
      await new Promise((resolve,reject)=>{window.releases.push(resolve);window.rejects.push(reject);});
      // Deliberately no live guard: host isolation alone must protect new DOM.
      container.innerHTML=`<form data-visible-order="${orderId}"><input name="reason" value="${orderId}"><button>${orderId} action</button></form>`;
      return kind==='finance'?()=>window.disposals++:undefined;
    };
    window.mount=window.makeRentalMount({section,isCurrent:()=>section.isConnected,request:()=>{},renderBusiness:render('business'),renderFinance:render('finance')});
    section.querySelectorAll('button[data-rental-order-id]').forEach(button=>button.onclick=()=>window.activeMount=window.mount(button.dataset.rentalOrderId).catch(e=>window.errors.push(e.message)));
  });return page;
}
async function release(page,from=0){await page.evaluate(from=>window.releases.slice(from).forEach(r=>r()),from);await page.locator('[data-rental-mount-state=ready]').waitFor();}
try{
  await test('repeated real clicks during one mount dispatch only one pair of reads and detach old form immediately',async()=>{
    const p=await setup();await p.getByRole('button',{name:'A',exact:true}).dblclick();
    assert.equal(await p.locator('#old-form').count(),0);assert.equal(await p.locator('form').count(),0);
    assert.equal(await p.getByRole('button',{name:'A',exact:true}).isDisabled(),true);
    assert.equal(await p.getByRole('button',{name:'B',exact:true}).isDisabled(),true);
    assert.deepEqual(await p.evaluate(()=>window.reads),[{kind:'business',orderId:'A'},{kind:'finance',orderId:'A'}]);
    await release(p);assert.equal(await p.locator('[data-visible-order=A]').count(),2);await p.close();
  });
  await test('new order uses detached containers and delayed old render cannot overwrite current inputs',async()=>{
    const p=await setup();await p.getByRole('button',{name:'A',exact:true}).click();await release(p);
    await p.getByRole('button',{name:'B',exact:true}).click();assert.equal(await p.locator('[data-visible-order=A]').count(),0);
    await p.evaluate(()=>window.oldNodes.slice(0,2).forEach(node=>node.innerHTML='<form data-stale>late A response</form>'));
    assert.equal(await p.locator('[data-stale]').count(),0);
    await release(p,2);await p.locator('[data-rental-business] input').fill('B operator input');
    await p.evaluate(()=>window.oldNodes[0].innerHTML='<form data-stale>later A response</form>');
    assert.equal(await p.locator('[data-stale]').count(),0);assert.equal(await p.locator('[data-rental-business] input').inputValue(),'B operator input');
    assert.equal(await p.evaluate(()=>window.disposals),1);await p.close();
  });
  await test('query replacement detaches in-flight workspace so late results cannot regain actions',async()=>{
    const p=await setup();await p.getByRole('button',{name:'A',exact:true}).click();
    await p.evaluate(()=>{
      document.querySelector('#workspace').remove();
      const next=document.createElement('section');next.id='replacement';next.textContent='查询下一订单中';document.body.append(next);
      window.releases.forEach(resolve=>resolve());
    });
    await p.evaluate(()=>window.activeMount);
    assert.equal(await p.locator('form').count(),0);assert.equal(await p.locator('#replacement').innerText(),'查询下一订单中');
    assert.equal(await p.evaluate(()=>window.disposals),1);await p.close();
  });
  await test('partial read failure removes actionable forms and late companion completion stays detached',async()=>{
    const p=await setup();await p.getByRole('button',{name:'A',exact:true}).click();
    await p.evaluate(()=>window.rejects[1](Error('synthetic finance read failed')));
    await p.locator('[data-rental-mount-state=error]').waitFor();
    await p.evaluate(()=>window.releases[0]());
    assert.equal(await p.locator('form').count(),0);assert.equal(await p.getByRole('button',{name:'A',exact:true}).isDisabled(),false);
    assert.deepEqual(await p.evaluate(()=>window.errors),['synthetic finance read failed']);await p.close();
  });
}finally{await browser.close();}
