/* Shared, explicit traveler and payment confirmation. Source remains the user's vault. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const titles = {HOTEL:'酒店',FLIGHT:'机票',RAIL:'火车票',RENTAL:'租车',RIDE:'接送',ATTRACTION:'门票'};
  const scopes = {HOTEL:['LEGAL_NAME','MOBILE'],FLIGHT:['LEGAL_NAME'],RAIL:['LEGAL_NAME'],RENTAL:['LEGAL_NAME','DRIVER_LICENSE_NUMBER'],RIDE:['LEGAL_NAME','MOBILE'],ATTRACTION:['LEGAL_NAME']};
  const fields = {LEGAL_NAME:'姓名',MOBILE:'联系电话',EMAIL:'邮箱',DRIVER_LICENSE_NUMBER:'驾驶证号',PASSPORT_NUMBER:'护照号',ID_CARD_NUMBER:'身份证号',DATE_OF_BIRTH:'出生日期'};
  const requests = new Map();
  const key = name => {if(!requests.has(name))requests.set(name,crypto.randomUUID());return requests.get(name)};
  const post = (path, body, name) => api(path,{method:'POST',headers:{'Idempotency-Key':key(name||path)},body:JSON.stringify(body)});
  function dialog(title, content, confirmLabel, accept) {
    return new Promise(resolve => {
      const d=document.createElement('dialog'); d.className='go-dialog';
      d.setAttribute('aria-labelledby','goDialogTitle');
      d.innerHTML=`<form><h2 id="goDialogTitle">${esc(title)}</h2>${content}<p role="alert"></p><footer><button type="button" class="btn ghost" data-cancel>暂不继续</button><button type="submit" class="btn primary">${esc(confirmLabel)}</button></footer></form>`;
      const previous=document.activeElement;let settled=false,busy=false;
      const close=result=>{if(settled)return;settled=true;d.close();d.remove();previous?.focus?.();resolve(result)};
      d.addEventListener('cancel',e=>{e.preventDefault();if(!busy)close(null)});
      d.querySelector('[data-cancel]').onclick=()=>{if(!busy)close(null)};
      d.querySelector('form').onsubmit=async e=>{e.preventDefault();if(busy||settled)return;busy=true;const btn=d.querySelector('[type=submit]');btn.disabled=true;d.querySelector('[data-cancel]').disabled=true;d.querySelector('[role=alert]').textContent='';try{close(await accept(d))}catch(err){d.querySelector('[role=alert]').textContent=err.message;btn.disabled=false;d.querySelector('[data-cancel]').disabled=false;busy=false}};
      document.body.append(d);d.showModal();
    });
  }
  async function acceptRide(id) {
    const offer=(state.rideSearch||[]).find(x=>x.offer_id===id), c=offer?.cancellation;
    if(c?.state!=='POLICY_AVAILABLE'||!c.policy_hash||!c.terms?.policy)throw Error('接送取消条款尚待核验，暂不能预订此方案。');
    const t=c.terms,p=t.policy,seconds=p.cutoff_seconds,lead=seconds>0&&seconds%86400===0?`${seconds/86400}天`:seconds>0&&seconds%3600===0?`${seconds/3600}小时`:seconds>0&&seconds%60===0?`${seconds/60}分钟`:`${seconds}秒`;
    return dialog('核对接送取消条款',`<p>本方案为隔离测试条款，不代表真实车队收费。</p><p>${esc(t.pickup)} → ${esc(t.dropoff)} · ${esc(t.booked_pickup_at)}</p><p>总价 ${esc(money(t.total_amount_minor,t.currency))}</p><p>以${p.time_basis==='BOOKED_PICKUP'?'预订时接车时间':'当前已确认接车时间'}为基准，提前 ${esc(lead)} 为费用分界。分界前取消费 ${esc(money(p.before_fee_minor,t.currency))}；分界时及之后取消费 ${esc(money(p.after_fee_minor,t.currency))}。</p><p>条款版本 ${esc(p.version)}；适用报价期间 ${esc(p.effective_from)} 至 ${esc(p.effective_until)}。</p><label class="go-consent"><input type="checkbox" required data-policy-consent><span>我已阅读并同意本次预订的取消条款。</span></label>`,'同意条款并继续',d=>{if(!d.querySelector('[data-policy-consent]').checked)throw Error('请先确认取消条款');return c.policy_hash});
  }
  async function traveler(vertical) {
    const v=await api('/v1/consumer/profile/vault');
    v.travelers=v.travelers.filter(t=>t.booking_permission!==false&&(t.permissions?.USE_FOR_BOOKING??true));
    if(!v.travelers.length){await showAccount();toast('请先添加一位旅行者，再继续预订');return null}
    return dialog(`核对${titles[vertical]}出行资料`,`<p>请选择本次实际出行人。仅为这次${titles[vertical]}预订使用${scopes[vertical].map(f=>fields[f]).join('、')}。</p><div class="field"><label for="goTraveler">旅行者</label><select id="goTraveler" required><option value="">请选择出行人</option>${v.travelers.map(t=>`<option value="${esc(t.traveler_id)}">${esc(t.full_name)} · ${t.relationship_type==='SELF'?'本人':'同行人'}</option>`).join('')}</select></div><label class="go-consent"><input type="checkbox" data-consent required><span>我已核对出行人资料，并确认有权为其预订及使用以上资料。</span></label>`,'确认出行人',async d=>{
      if(!d.querySelector('[data-consent]').checked)throw Error('请先确认本次资料用途');
      const tid=d.querySelector('#goTraveler').value;if(!tid)throw Error('请选择旅行者');
      const selected=v.travelers.find(t=>t.traveler_id===tid);if(!selected)throw Error('请选择已授权的旅行者');
      const sensitive=scopes[vertical].filter(f=>selected.facts.some(x=>x.field_type===f&&x.sensitive));
      if(sensitive.length)await api('/v1/consumer/profile/consents',{method:'POST',body:JSON.stringify({traveler_id:tid,consent_type:'SENSITIVE_DATA_RELEASE',purpose:`${vertical}_BOOKING`,scope:sensitive,expires_at:new Date(Date.now()+15*60000).toISOString()})});
      return tid;
    });
  }
  async function pay(vertical, order) {
    if(vertical==='RIDE'&&order.cancellation?.state!=='BOOKING_ACCEPTED')throw Error('该接送订单缺少已确认的取消条款，暂不能继续支付。');
    const caps=await api('/v1/consumer/checkout-capabilities');
    if(!caps.simulation_available){toast('支付渠道尚未开放，此订单尚未付款');return null}
    return dialog(`确认${titles[vertical]}订单`,`${typeof paymentDeadlineHtml==='function'?paymentDeadlineHtml(order):''}<p>含税应付总额</p><h2>${esc(money(order.total_amount_minor,order.currency))}</h2><div class="go-sim-note">当前为隔离测试：不会扣真实款项，生成的预订与票据不能用于实际出行。</div><label class="go-consent"><input type="checkbox" data-consent required><span>已核对金额，确认完成本次测试支付与预订。</span></label>`,'确认测试支付',async d=>{
      if(!d.querySelector('[data-consent]').checked)throw Error('请确认金额');
      return post(`/v1/consumer/checkout/${vertical}/${order.order_id}`,{mode:'CONTRACT_SIMULATOR',expected_amount_minor:order.total_amount_minor,currency:order.currency},`checkout:${order.order_id}`);
    });
  }
  async function travelers(vertical,count) {
    if(count===1){const tid=await traveler(vertical);return tid?[tid]:null}
    if(!Number.isInteger(count)||count<1||count>9)throw Error('本次请为 1 至 9 位出行人预订。');
    const person=vertical==='FLIGHT'?'成年乘机人':vertical==='RAIL'?'成年乘车人':'参加人';
    const v=await api('/v1/consumer/profile/vault');
    const eligible=v.travelers.filter(t=>t.booking_permission!==false&&(t.permissions?.USE_FOR_BOOKING??true));
    if(eligible.length<count){await showAccount();toast(`请先添加并授权 ${count} 位实际${person}，再继续预订。`);return null}
    return dialog(`核对本次全部${person}`,`<p>本次报价包含 ${count} 位出行人。请按证件姓名选择 ${count} 位不同的实际${person}。</p>${eligible.map(t=>`<label class="go-consent"><input type="checkbox" data-traveler value="${esc(t.traveler_id)}"><span>${esc(t.full_name)} · ${t.relationship_type==='SELF'?'本人':'同行人'}</span></label>`).join('')}<label class="go-consent"><input type="checkbox" data-consent required><span>我已逐一核对${person}与姓名，确认符合所选票种的适用条件，并有权为其预订及为本次${titles[vertical]}使用姓名。</span></label>`,'确认全部出行人',async d=>{
      if(!d.querySelector('[data-consent]').checked)throw Error('请确认本次资料用途。');
      const ids=[...d.querySelectorAll('[data-traveler]:checked')].map(el=>el.value);
      if(ids.length!==count||new Set(ids).size!==count||ids.some(id=>!eligible.some(t=>t.traveler_id===id)))throw Error(`请选择 ${count} 位不同的实际${person}。`);
      for(const tid of ids){
        const selected=eligible.find(t=>t.traveler_id===tid);
        const sensitive=scopes[vertical].filter(f=>(selected.facts||[]).some(x=>x.field_type===f&&x.sensitive));
        if(sensitive.length)await api('/v1/consumer/profile/consents',{method:'POST',body:JSON.stringify({traveler_id:tid,consent_type:'SENSITIVE_DATA_RELEASE',purpose:`${vertical}_BOOKING`,scope:sensitive,expires_at:new Date(Date.now()+15*60000).toISOString()})});
      }
      return ids;
    });
  }
  async function run(fn){try{if(!state.me){showAuth();return}await fn()}catch(e){toast(e.message)}}
  createOrder=()=>run(async()=>{const accepted=await window.GOCatalogFare.accept(state.prebook,{dialog,money});if(!accepted)return;const tid=await traveler('HOTEL');if(!tid)return;state.order=await post('/v1/consumer/orders',{prebook_id:state.prebook.prebook_id,traveler_id:tid,...accepted},`hotel:${state.prebook.prebook_id}:${tid}:${accepted.expected_fare_rule_hash}`);await renderPay()});
  const oldPay=renderPay;
  renderPay=async()=>{const caps=await api('/v1/consumer/checkout-capabilities');if(!caps.simulation_available){oldPay();return}$('#app').innerHTML=shell(`<h1 class="screen-title">确认酒店订单</h1><section class="card"><div class="kv"><span>含税总价</span><b>${esc(money(state.order.total_amount_minor,state.order.currency))}</b></div><div class="go-sim-note">隔离测试订单，不产生真实扣款。</div><button class="btn primary" id="goHotelPay">核对并继续</button></section>`,'trips');bindNav();$('#goHotelPay').onclick=()=>run(async()=>{if(await pay('HOTEL',state.order))await showTrip(state.order.order_id)})};
  createFlightOrderAndCheckout=()=>run(async()=>{const ids=await travelers('FLIGHT',state.flightPrebook.passenger_count||state.flightOffer?.passenger_count||1);if(!ids)return;const o=await post('/v1/flights/orders',{prebook_id:state.flightPrebook.prebook_id,traveler_ids:ids},`flight:${state.flightPrebook.prebook_id}:${ids.join(':')}`);await pay('FLIGHT',o);state.flightOrder=await api(`/v1/flights/orders/${o.order_id}`);renderFlightOrder()});
  mobilityBook=(kind,id)=>run(async()=>{const rental=kind==='RENTAL',accepted=rental?null:await acceptRide(id);if(!rental&&!accepted)return;const tid=await traveler(kind);if(!tid)return;const criteria=rental?state.rentalCriteria:state.rideCriteria;const o=await post(rental?'/v1/mobility/rentals/orders':'/v1/mobility/rides/orders',{...criteria,offer_id:id,traveler_ids:[tid],...(!rental?{cancellation_policy_hash:accepted}:{})},`${kind}:${id}:${tid}:${JSON.stringify(criteria)}:${accepted||''}`);await pay(kind,o);const detail=await api(`/v1/mobility/orders/${o.order_id}`);if(rental)state.rentalOrder=detail;else state.rideOrder=detail;renderMobilityOrder(kind)});
  function resume(vertical,o){if(vertical==='RIDE'&&o?.cancellation?.state!=='BOOKING_ACCEPTED')return;if(!o||!['PAYMENT_PENDING','PAYMENT_AUTHORIZED','PAYMENT_CONFIRMED_AWAITING_SUPPLIER'].includes(o.status))return;const b=document.createElement('button');b.className='btn primary';b.textContent='继续核对与支付';document.querySelector('#app').append(b);b.onclick=()=>run(async()=>{if(await pay(vertical,o)){if(vertical==='FLIGHT'){state.flightOrder=await api(`/v1/flights/orders/${o.order_id}`);renderFlightOrder()}else if(vertical==='RAIL'){state.railOrder=await api(`/v1/rail/orders/${o.order_id}`);renderRailOrder()}else if(vertical==='ATTRACTION')await attractionReload();else await mobilityReload(vertical)}})}
  const oldFlight=renderFlightOrder,oldRail=renderRailOrder,oldMobility=renderMobilityOrder,oldAttraction=renderAttractionOrder;
  renderFlightOrder=()=>{oldFlight();resume('FLIGHT',state.flightOrder)};renderRailOrder=()=>{oldRail();resume('RAIL',state.railOrder)};renderMobilityOrder=k=>{oldMobility(k);resume(k,k==='RENTAL'?state.rentalOrder:state.rideOrder)};renderAttractionOrder=()=>{oldAttraction();resume('ATTRACTION',state.attractionOrder)};
  async function addTraveler(existing=null){
    const result=await dialog(existing?'更新旅行资料':'添加旅行者',`<p>${existing?'输入要补充的资料；已有字段冲突将保留，等待你选择。':'请填写证件上的姓名。账号昵称不会自动成为出行人。'}</p><div class="field"><label for="pvName">姓名</label><input id="pvName" required autocomplete="name" value="${esc(existing?.full_name||'')}" ${existing?'readonly':''}></div><div class="field"><label for="pvRel">关系</label><select id="pvRel"><option value="SELF">本人</option><option value="FAMILY">家人</option><option value="FREQUENT_TRAVELER">其他同行人</option></select></div><div class="field"><label for="pvPhone">联系电话（选填）</label><input id="pvPhone" type="tel" autocomplete="tel"></div><div class="field"><label for="pvLicense">驾驶证号（租车时使用，选填）</label><input id="pvLicense" autocomplete="off"></div><label class="go-consent"><input type="checkbox" required data-confirm><span>我已核对资料，且有权保存、使用本人与所选同行人的资料。</span></label>`,'确认保存',async d=>{
      if(!d.querySelector('[data-confirm]').checked)throw Error('请确认资料');
      const name=d.querySelector('#pvName').value.trim();if(!name)throw Error('请填写姓名');
      const items=[{entity_type:'TRAVELER',traveler_ref:'selected',value:{full_name:name,relationship_type:existing?.relationship_type||d.querySelector('#pvRel').value,...(existing?{existing_traveler_id:existing.traveler_id}:{})},confidence_bps:10000}];
      for(const [id,ft] of [['pvPhone','MOBILE'],['pvLicense','DRIVER_LICENSE_NUMBER']]){const value=d.querySelector(`#${id}`).value.trim();if(value)items.push({entity_type:'PROFILE_FACT',traveler_ref:'selected',field_type:ft,value,confidence_bps:10000})}
      const job=await api('/v1/consumer/profile/imports',{method:'POST',body:JSON.stringify({source_type:'MANUAL',source_provider:'USER',source_reference:'GO_PROFILE_EDITOR',items})});
      for(const item of job.items)if(['NEEDS_REVIEW','EXTRACTED'].includes(item.status))await api(`/v1/consumer/profile/imports/${job.import_job_id}/items/${item.import_item_id}/review`,{method:'POST',body:JSON.stringify({action:'ACCEPT'})});
      return api(`/v1/consumer/profile/imports/${job.import_job_id}/commit`,{method:'POST'});
    });if(result)await showAccount();
  }
  showAccount=async()=>{try{setVerticalVIMode(false);const [v,c]=await Promise.all([api('/v1/consumer/profile/vault'),api('/v1/consumer/profile/consents')]);$('#app').innerHTML=shell(`<h1 class="screen-title">我的旅行资料</h1><p class="sub">一次核对，按需使用。每次预订由你选择实际出行人。</p><div class="vault-actions"><button class="btn primary" id="pvAdd">添加旅行者</button><button class="btn ghost" id="pvExport">导出我的资料</button></div>${v.travelers.map(t=>`<section class="card"><h2>${esc(t.full_name)}</h2><p>${t.relationship_type==='SELF'?'本人':'同行人'} · ${t.booking_permission?'可用于预订':'预订授权已关闭'}</p>${t.facts.map(f=>`<div class="vault-fact"><div><b>${esc(fields[f.field_type]||f.field_type)}</b> ${esc(f.value_masked)}<small>来源 ${esc(f.source_provider||f.source_type)} · ${f.user_confirmed?'已由用户确认':'待核对'}</small></div><button class="btn ghost" data-delete-fact="${esc(f.fact_id)}">删除</button></div>`).join('')}<div class="vault-actions"><button class="btn ghost" data-edit-traveler="${esc(t.traveler_id)}">补充资料</button><button class="btn ghost" data-delete-traveler="${esc(t.traveler_id)}">删除旅行者</button></div></section>`).join('')||'<section class="card"><h2>让下次出发更轻松</h2><p>添加本人或同行人的资料，预订时按需选择。这里不会保存第三方平台密码。</p></section>'}<section class="card"><h2>资料使用授权</h2>${c.items.filter(x=>x.status==='ACTIVE').map(x=>`<div class="vault-fact"><div>${esc(x.purpose)}<small>${x.scope.map(f=>esc(fields[f]||f)).join('、')}</small></div><button class="btn ghost" data-revoke="${esc(x.consent_id)}">撤回授权</button></div>`).join('')||'<p>暂无有效授权。</p>'}</section><button class="btn ghost" id="pvLogout">退出登录</button>`,'profile');bindNav();$('#pvAdd').onclick=()=>run(()=>addTraveler());document.querySelectorAll('[data-edit-traveler]').forEach(b=>b.onclick=()=>run(()=>addTraveler(v.travelers.find(t=>t.traveler_id===b.dataset.editTraveler))));
      const confirmDelete=(title,path)=>run(async()=>{if(await dialog(title,'<p>删除后，这份资料将不再用于新的旅行预订。</p>','确认删除',()=>api(path,{method:'DELETE'})))await showAccount()});
      document.querySelectorAll('[data-delete-fact]').forEach(b=>b.onclick=()=>confirmDelete('删除这项资料',`/v1/consumer/profile/facts/${b.dataset.deleteFact}`));document.querySelectorAll('[data-delete-traveler]').forEach(b=>b.onclick=()=>confirmDelete('删除旅行者与资料',`/v1/consumer/profile/travelers/${b.dataset.deleteTraveler}`));document.querySelectorAll('[data-revoke]').forEach(b=>b.onclick=()=>run(async()=>{await api(`/v1/consumer/profile/consents/${b.dataset.revoke}`,{method:'DELETE'});await showAccount()}));
      $('#pvExport').onclick=()=>run(async()=>{const data=await dialog('导出我的旅行资料','<p>文件会包含你的个人资料。同行人仅导出允许分享的字段，请保存在你信任的设备上。</p>','确认导出',()=>api('/v1/consumer/profile/export',{method:'POST',body:JSON.stringify({confirmed:true})}));if(!data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='GO_Personal_Travel_Vault.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
      $('#pvLogout').onclick=async()=>{await api('/v1/consumer/auth/logout',{method:'POST'});state.me=null;showHome()};
    }catch(e){toast(e.message)}};
  window.GOBooking={dialog,traveler,travelers,pay,addTraveler,acceptRide};
})();
