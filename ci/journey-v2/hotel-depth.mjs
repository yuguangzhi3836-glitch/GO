import assert from 'node:assert/strict';

// This module runs only inside the existing disposable, same-origin CI browser.
// It never fabricates a business response, edits the database or uses live money.
export async function hotelDepth(h) {
  const {consumer:p,admin,unrelatedSupplier,report,origin,read,scenario,home,dialog,day,
    noOverflow,pageFor,login,suppliers,capture}=h;
  report.depth44={scope:'GO_TRIP_SEARCH_AND_HOTEL_TWO_CHANGES',search_viewports:[],
    fault_injections:[],checkpoints:[],payment_viewports:[],complete:false,
    limitations:['Same-price hotel changes with separately charged fees; no high/low fare browser coverage',
      'Capture failure uses the existing simulator token in one outgoing request',
      'Refund response loss occurs after server success; not a partial internal refund failure',
      'Supplier/admin browser inspection and authenticated reads; their money mutations are not exercised']};
  report.cash_journeys=[];
  const extra=report.depth44;
  async function trips(query='') {
    await p.goto(origin+'/go-app/');
    await p.locator('[data-nav=trips]').first().click();
    await p.locator('#tripQuery').waitFor();
    await p.locator('#tripQuery').fill(query);
  }
  async function open(oid) {
    await trips(oid);
    assert.equal(await p.locator('[data-go-trip-index]').count(),1);
    assert.ok((await p.locator('#allTripOrders').innerText()).includes(oid));
    await p.locator('[data-go-trip-index]').click();
    await p.locator('#tripDetailLoading').waitFor({state:'detached'});
    await p.locator('#change').waitFor();
  }
  const requestAt=(r,pathname,method='POST')=>r.request().method()===method&&new URL(r.url()).pathname===pathname;
  async function value(response) {
    assert.ok(response.ok(),`HTTP ${response.status()}: ${await response.text()}`);
    const body=await response.json();return body.data||body;
  }
  async function kv(container,label,expected) {
    const row=container.locator('.kv').filter({has:container.page().getByText(label,{exact:true})});
    assert.equal(await row.count(),1,`one visible ${label} row required`);
    assert.ok((await row.innerText()).includes(String(expected)),`${label}: ${await row.innerText()}`);
  }
  // All six original refunded orders remain available while filtering, clearing
  // and navigating. A filtered card must open its own ID, not an unfiltered index.
  for(const width of [375,390,430,1440]) {
    const ok=await scenario(p,`DEPTH44-trip-search-${width}`,async()=>{
      await p.setViewportSize({width,height:940});await trips();
      const rows=(await read(p,'/v1/consumer/unified-trips')).items;
      assert.ok(rows.length>=6);
      for(const [vertical,oid] of h.expectedOrders) {
        await p.locator('#tripQuery').fill('  '+oid.toUpperCase()+'  ');
        assert.equal(await p.locator('[data-go-trip-index]').count(),1,vertical);
        assert.ok((await p.locator('#allTripOrders').innerText()).includes(oid));
      }
      const title=rows.find(x=>x.vertical==='HOTEL').title;
      await p.locator('#tripQuery').fill(title);
      assert.equal(await p.locator('[data-go-trip-index]').count(),rows.filter(x=>x.title.includes(title)).length);
      await p.locator('#tripQuery').fill('酒店');
      assert.equal(await p.locator('[data-go-trip-index]').count(),rows.filter(x=>x.vertical==='HOTEL').length);
      await p.locator('#tripQuery').fill('no-such-order-depth44');
      assert.equal(await p.locator('[data-go-trip-index]').count(),0);
      await p.getByText('没有找到匹配订单',{exact:true}).waitFor();
      await p.locator('#tripQuery').fill('');
      assert.equal(await p.locator('[data-go-trip-index]').count(),rows.length);
      const oid=h.expectedOrders.get('FLIGHT');
      await p.locator('#tripQuery').fill(oid);
      const response=p.waitForResponse(r=>requestAt(r,'/v1/flights/orders/'+oid,'GET'));
      await p.locator('[data-go-trip-index]').click();
      assert.equal((await value(await response)).order_id,oid);
      await p.locator('#tripDetailLoading').waitFor({state:'detached'});await noOverflow(p);
      extra.search_viewports.push({width,orders:rows.length,result:'PASS'});
    });
    if(!ok)return;
  }
  await p.setViewportSize({width:390,height:940});
  let oid,initial,first,second,final,owner;
  const orderPath=()=>'/v1/consumer/transaction-orders/HOTEL/'+oid;
  const fixture={vertical:'HOTEL',change_quotes:[],stages:[],complete:false};
  report.cash_journeys.push(fixture);
  const record=(name,snapshot)=>{
    extra.checkpoints.push({name,order_id:oid,snapshot});fixture.stages.push(name);
  };
  if(!await scenario(p,'DEPTH44-unpaid-order-search-and-resume',async()=>{
    await home(p,'HOTEL');await p.locator('#city').fill('TYO');
    await p.locator('#cin').fill(day(40));await p.locator('#cout').fill(day(42));
    await p.locator('#searchBtn').click();await p.locator('[data-hotel]').first().click();
    await p.locator('[data-offer]').first().click();await p.locator('#continue').click();
    const response=p.waitForResponse(r=>requestAt(r,'/v1/consumer/orders'));
    await p.locator('#create').click();await dialog(p);await dialog(p);
    const order=await value(await response);oid=order.order_id;fixture.order_id=oid;
    assert.equal(order.status,'PAYMENT_PENDING');await p.locator('#goHotelPay').waitFor();
    await open(oid);
    const pending=await read(p,orderPath());assert.equal(pending.order.status,'PAYMENT_PENDING');
    const detail=await read(p,'/v1/consumer/orders/'+oid+'/detail');
    assert.equal(detail.stay.check_in,day(40));assert.equal(detail.stay.check_out,day(42));
    assert.equal(pending.original_payment.capture_count,0);record('UNPAID_QUERYABLE',pending);
    const resume=p.getByRole('button',{name:'核对金额并继续付款',exact:true});
    for(const width of [375,390,430,1440]){
      await p.setViewportSize({width,height:940});await resume.click({trial:true});await noOverflow(p);
      extra.payment_viewports.push({width,result:'PASS',screenshot:await capture(p,'depth44-unpaid-resume-'+width)});
    }
    await p.setViewportSize({width:390,height:940});await resume.click();
    await dialog(p);await p.locator('#change').waitFor();
    initial=await read(p,orderPath());assert.equal(initial.order.status,'CONFIRMED');
    assert.equal(initial.original_payment.capture_count,1);
    fixture.original_capture_minor=initial.original_payment.captured_minor;
    const matching=(await read(p,'/v1/consumer/unified-trips')).items.filter(x=>x.order_id===oid);
    assert.equal(matching.length,1,'resuming must not create another order');record('PAID_SAME_ORDER',initial);
  },'journeys'))return;

  owner=await pageFor('supplier-depth44',390);
  try {
    if(!await scenario(owner,'DEPTH44-hotel-owner-login',async()=>login(owner,'supplier',suppliers.HOTEL)))return;
    async function sameOrder(name,expectedState,dates,paid,refunded=0,requested) {
      const snapshot=await read(p,orderPath()),cash=snapshot.cash_after_sales;
      assert.equal(cash.state,expectedState);assert.equal(cash.check_in,dates[0]);assert.equal(cash.check_out,dates[1]);
      assert.equal(cash.gross_paid_minor,paid);assert.equal(cash.refunded_minor,refunded);
      assert.equal(cash.net_paid_minor,paid-refunded);
      await trips(oid);
      const list=p.locator('#allTripOrders');
      await kv(list,'入住日期',dates[0]);await kv(list,'退房日期',dates[1]);
      // Match digits independently of the product's currency-prefix typography.
      const amount=n=>(n/100).toFixed(2);
      for(const [label,n]of [['累计实付（含补款）',paid],['累计已退',refunded],['当前净实付',paid-refunded]]){
        const row=list.locator('.kv').filter({has:p.getByText(label,{exact:true})});
        assert.equal(await row.count(),1);
        assert.ok((await row.innerText()).replaceAll(',','').includes(amount(n)),label+': '+await row.innerText());
      }
      if(requested){await kv(list,'申请入住日期',requested[0]);await kv(list,'申请退房日期',requested[1]);}
      await noOverflow(p);extra.checkpoints.push({name:name+'-consumer-list',screenshot:await capture(p,name+'-consumer-list')});
      // Workbench keeps the #/orders hash. Navigating to that same URL does
      // not re-render the list; use the customer's visible return action.
      const back=owner.getByRole('button',{name:'← 返回订单',exact:true});
      if(await back.isVisible())await back.click();
      else await owner.goto(origin+'/supplier-console/#/orders');
      const tr=owner.locator('tr[data-i]').filter({hasText:oid});await tr.waitFor();await tr.click();
      await owner.getByRole('heading',{name:'当前退改与付款摘要',exact:true}).waitFor();
      const supplierSnapshot=await read(owner,'/v1/supplier/transaction-orders/HOTEL/'+oid);
      assert.deepEqual(supplierSnapshot,snapshot);
      const workbench=await read(owner,'/v1/supplier/orders/'+oid+'/workbench');assert.deepEqual(workbench.cash_after_sales,cash);
      const card=owner.locator('section,div.card').filter({has:owner.getByRole('heading',{name:'当前退改与付款摘要',exact:true})}).last();
      assert.ok((await card.innerText()).includes(dates[0]));
      assert.ok((await card.innerText()).replaceAll(',','').includes(amount(paid)));
      await noOverflow(owner);extra.checkpoints.push({name:name+'-supplier-detail',screenshot:await capture(owner,name+'-supplier-detail')});
      const adminUrl=origin+'/go-admin/#/vertical-hotel';
      if(admin.url()===adminUrl)await admin.reload();else await admin.goto(adminUrl);
      await admin.locator('#view').getByText(oid,{exact:true}).first().waitFor();
      assert.deepEqual(await read(admin,'/internal/v1/admin/transaction-orders/HOTEL/'+oid),snapshot);
      const operations=await read(admin,'/internal/v1/admin/operations/verticals/HOTEL');
      assert.equal(operations.orders.find(x=>x.order_id===oid).status,snapshot.order.status);
      await noOverflow(admin);extra.checkpoints.push({name:name+'-admin-detail',screenshot:await capture(admin,name+'-admin-detail')});
      const denied=await unrelatedSupplier.evaluate(async url=>(await fetch(url)).status,'/v1/supplier/transaction-orders/HOTEL/'+oid);
      assert.equal(denied,404);record(name,snapshot);return snapshot;
    }
    async function change(days,failCapture=false) {
      await open(oid);await p.locator('#change').click();
      const dates=p.locator('dialog[open]');await dates.locator('[name=cashIn]').fill(day(days));
      await dates.locator('[name=cashOut]').fill(day(days+2));
      const quoteResponse=p.waitForResponse(r=>requestAt(r,'/v1/orders/'+oid+'/change-quote'));
      await dates.locator('[type=submit]').click();
      const quote=await value(await quoteResponse);fixture.change_quotes.push(quote);
      assert.equal(quote.new_check_in,day(days));assert.equal(quote.new_check_out,day(days+2));
      assert.equal(quote.fare_difference_minor,0);assert.ok(quote.change_fee_minor>0);
      assert.equal(quote.amount_due_minor,quote.change_fee_minor);
      const confirmation=p.locator('dialog[open]');await confirmation.locator('[name=cashConfirmed]').waitFor();
      assert.equal(await confirmation.locator('[name=cashConfirmed]').isChecked(),false);
      await confirmation.locator('[type=submit]').click();assert.equal(await confirmation.count(),1);
      const endpoint=origin+'/v1/orders/'+oid+'/change';let injected=false;
      const fault=async route=>{
        const body=route.request().postDataJSON();assert.equal(body.payment_method_token,'pm_success');
        body.payment_method_token='pm_capture_fail';injected=true;
        extra.fault_injections.push({kind:'EXISTING_SIMULATOR_CAPTURE_FAILURE',order_id:oid,at:new Date().toISOString()});
        await route.continue({postData:JSON.stringify(body)});
      };
      if(failCapture)await p.route(endpoint,fault,{times:1});
      try {
        const response=p.waitForResponse(r=>requestAt(r,'/v1/orders/'+oid+'/change'));
        await dialog(p);const operation=await value(await response);await p.locator('#change').waitFor();
        assert.equal(operation.state,failCapture?'CAPTURE_PENDING':'COMPLETED');
        if(failCapture)assert.ok(injected);return {quote,operation};
      }finally{if(failCapture)await p.unroute(endpoint,fault);}
    }
    if(!await scenario(p,'DEPTH44-capture-failure-keeps-original-trip',async()=>{
      first=await change(50,true);
      await sameOrder('CAPTURE_PENDING','CAPTURE_PENDING',[day(40),day(42)],fixture.original_capture_minor,0,[day(50),day(52)]);
    },'journeys'))return;
    if(!await scenario(p,'DEPTH44-retry-payment-from-same-order',async()=>{
      await open(oid);await p.locator('#cashRetryPayment').click();
      const d=p.locator('dialog[open]');await d.locator('[name=cashConfirmed]').waitFor();
      await d.locator('[type=submit]').click();assert.equal(await d.count(),1,'payment consent remains mandatory');
      const response=p.waitForResponse(r=>requestAt(r,'/v1/orders/'+oid+'/cash-after-sales/'+first.operation.operation_id+'/retry-payment'));
      await dialog(p);const resumed=await value(await response);assert.equal(resumed.operation_id,first.operation.operation_id);
      assert.equal(resumed.state,'COMPLETED');
      await sameOrder('FIRST_CHANGE_COMPLETED','COMPLETED',[day(50),day(52)],fixture.original_capture_minor+first.quote.amount_due_minor);
    },'journeys'))return;
    if(!await scenario(p,'DEPTH44-second-change-only-charges-new-fee',async()=>{
      second=await change(60);
      assert.notEqual(second.operation.operation_id,first.operation.operation_id);
      await sameOrder('SECOND_CHANGE_COMPLETED','COMPLETED',[day(60),day(62)],fixture.original_capture_minor+first.quote.amount_due_minor+second.quote.amount_due_minor);
    },'journeys'))return;
    if(!await scenario(p,'DEPTH44-refund-response-loss-refresh-and-replay',async()=>{
      await open(oid);
      const quoteResponse=p.waitForResponse(r=>requestAt(r,'/v1/orders/'+oid+'/cancellation-quote'));
      await p.locator('#cancel').click();const quote=await value(await quoteResponse);fixture.cancel_quote=quote;
      const gross=fixture.original_capture_minor+first.quote.amount_due_minor+second.quote.amount_due_minor;
      assert.equal(quote.gross_paid_minor,gross);assert.equal(quote.refund_amount_minor,gross);
      const d=p.locator('dialog[open]');await d.locator('[name=cashConfirmed]').check();
      let request,serverResult;const endpoint=origin+'/v1/orders/'+oid+'/cancel';
      let faultResolve,faultReject;const faultDone=new Promise((resolve,reject)=>{faultResolve=resolve;faultReject=reject;});
      const loseResponse=async route=>{
        try {
          const req=route.request();const headers=req.headers();
          request={path:'/v1/orders/'+oid+'/cancel',body:req.postData(),headers:Object.fromEntries(Object.entries(headers).filter(([k])=>['content-type','x-csrf-token','x-go-actor','idempotency-key'].includes(k)))};
          const response=await route.fetch();serverResult=await value(response);
          assert.equal(serverResult.state,'COMPLETED');
          extra.fault_injections.push({kind:'RESPONSE_LOST_AFTER_SERVER_COMMIT',order_id:oid,server_status:response.status(),at:new Date().toISOString()});
          await route.abort('failed');faultResolve();
        }catch(e){faultReject(e);await route.abort('failed').catch(()=>{});}
      };
      await p.route(endpoint,loseResponse,{times:1});
      try {
        await d.locator('[type=submit]').click();await faultDone;
        await p.waitForFunction(()=>Boolean(document.querySelector('dialog[open] [role=alert]')?.textContent));
        extra.checkpoints.push({name:'REFUND_RESPONSE_UNKNOWN_IN_BROWSER',screenshot:await capture(p,'depth44-refund-response-unknown')});
      }finally{await p.unroute(endpoint,loseResponse);}
      final=await sameOrder('CANCELLED_REFRESHED','COMPLETED',[day(60),day(62)],gross,gross);
      assert.equal(final.order.status,'CANCELLED');assert.equal(final.cash_after_sales.action,'CANCEL');
      assert.equal(final.original_payment.captured_minor,fixture.original_capture_minor);
      assert.equal(final.original_payment.refunded_minor,fixture.original_capture_minor);
      const replay=await p.evaluate(async req=>{const r=await fetch(req.path,{method:'POST',headers:req.headers,body:req.body,credentials:'same-origin'});return {status:r.status,body:await r.json()}},request);
      assert.equal(replay.status,200);assert.equal((replay.body.data||replay.body).operation_id,serverResult.operation_id);
      assert.deepEqual(await read(p,orderPath()),final,'replay cannot add a refund or change final state');
      await open(oid);assert.ok(await p.locator('#cancel').isDisabled());assert.ok(await p.locator('#change').isDisabled());
      await p.getByText('原路退款已完成',{exact:true}).waitFor();await noOverflow(p);
      fixture.final=final;fixture.refund_replay='NO_DUPLICATE';fixture.complete=true;extra.complete=true;
    },'journeys'))return;
  }finally{await owner.context().close();}
}
