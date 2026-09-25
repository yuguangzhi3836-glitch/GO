/* Current signed facts only; does not invent check-in or fleet success. */
(() => {
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={CHECK_IN_UNVERIFIED:'等待航空公司信息',CHECK_IN_NOT_OPEN:'值机尚未开放',CHECK_IN_OPEN:'可以办理值机',CHECKED_IN:'已办理值机',BOARDING_PASS_AVAILABLE:'登机牌已就绪'};
  const rideLabels={PENDING:'等待车队处理',DISPATCHED:'车队处理中',UNKNOWN:'正在核对车队结果',CONFIRMED:'车队已确认',REJECTED:'车队未接受调整',SUPERSEDED:'行程已更新，此申请不再执行',HOLD:'需要人工协助核对'};
  function link(url,label){
    try{const u=new URL(url);if(u.protocol!=='https:'||u.username||u.password||u.port||/[\s\\]/.test(url))return '';}
    catch{return '';}
    return `<a class="j-select" href="${esc(url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${label}</a>`;
  }
  function flightHTML(order,result){
    const rows=(result.items||[]).map(cell=>{
      const leg=(order.itinerary||[])[cell.leg_index]||{},person=(order.passengers||[])[cell.passenger_index]||{};
      const state=Object.hasOwn(labels,cell.state)?cell.state:'CHECK_IN_UNVERIFIED';
      return `<article class="go-travel-cell"><h3>第 ${Number(cell.leg_index)+1} 程 · ${esc(leg.origin)} → ${esc(leg.destination)}</h3><p>${esc(leg.departure_date)} · ${esc(person.full_name||`乘机人 ${Number(cell.passenger_index)+1}`)}</p><strong>${labels[state]}</strong>${cell.check_in_opens_at&&state==='CHECK_IN_NOT_OPEN'?`<p>预计开放时间 ${esc(cell.check_in_opens_at)}</p>`:''}<div class="go-travel-actions">${state!=='CHECK_IN_UNVERIFIED'?link(cell.official_check_in_url,'前往航空公司办理'):''}${state==='BOARDING_PASS_AVAILABLE'?link(cell.boarding_pass_reference,'查看这位乘机人的登机牌'):''}</div></article>`;
    }).join('');
    return `<h2>值机与登机牌</h2><p>每位乘机人的每一程，分别核对。</p>${rows||'<p>暂无可核实的客票信息，请稍后刷新订单。</p>'}<p class="muted">当前未连接航空公司实时服务，请勿作为实际出行凭证。信息未核实时不会显示为已值机。</p>`;
  }
  function rideHTML(result){
    const b=result.binding,identity=b?.flight_identity||{};
    return `<h2>航班与接送安排</h2><p>已确认接车时间 <strong>${esc(result.confirmed_pickup_at)}</strong></p>${b?`<p>${esc(identity.flight_no)} · ${esc(identity.departure_date)} · 到达 ${esc(identity.arrival_airport)}</p><p>${b.tracking_enabled?(b.source_current===false?'航班来源暂不可用':'已开启航班跟踪'):'已暂停航班跟踪'} · 包含免费等待 ${Number(b.included_wait_minutes)} 分钟${b.delay_protection_enabled?`；已验证延误时，保护上限 ${Number(b.delay_protection_max_wait_minutes)} 分钟`:''}</p>`:'<p>关联航班后，可跟进抵达时间的变化。</p>'}${(result.events||[]).slice().reverse().map(e=>`<article class="go-travel-cell"><strong>${rideLabels[e.status]||'等待核对'}</strong><p>${e.status==='CONFIRMED'?'该次确认接车时间':'建议接车时间'} ${esc(e.proposed_pickup_at)}</p>${Number.isFinite(e.free_wait_minutes)?`<p>本次规则内免费等待 ${Number(e.free_wait_minutes)} 分钟</p>`:''}${['PENDING','DISPATCHED','UNKNOWN'].includes(e.status)?'<p>请以已确认时间为准，正在与车队核对。</p>':''}${e.status==='HOLD'?'<p>车队结果与当前行程需要重新核对，请联系行程服务。</p>':''}</article>`).join('')}<p class="muted">当前未连接真实车队，服务状态请以承运方确认为准。</p>`;
  }
  async function configure(order,current){
    const options=await api(`/v1/mobility/rides/orders/${order.order_id}/flight-tracking/options`);
    if(!options.available){toast('当前暂无可用的航班跟踪服务，请保留原接送安排。');return null;}
    const b=current.binding,identity=b?.flight_identity||{};
    return GOBooking.dialog('关联抵达航班',`<p>请核对出发日期和到达机场。航班有变化时会向车队申请调整，车队确认后才更新接车时间。</p><label>航班来源<select data-source>${options.sources.map(s=>`<option value="${esc(s.authority_id)}" ${b?.authority_id===s.authority_id?'selected':''}>${esc(s.label)} · ${esc(s.provider_id)}（${esc(s.carriers.join(' / '))}）</option>`).join('')}</select></label><label>航空公司代码<input data-carrier maxlength="3" placeholder="MU" required value="${esc(identity.carrier_code)}"></label><label>航班号<input data-flight maxlength="9" placeholder="MU523" required value="${esc(identity.flight_no)}"></label><label>航班出发日期<input data-day type="date" required value="${esc(identity.departure_date)}"></label><label>到达机场代码<input data-airport maxlength="3" placeholder="NRT" required value="${esc(identity.arrival_airport)}"></label><label class="go-consent"><input data-protection type="checkbox" ${b?.delay_protection_enabled?'checked':''}><span>开启规则内延误保护：额外免费等待 ${Number(options.policy.delay_protection_free_wait_minutes)} 分钟，总等待上限 ${Number(options.policy.max_free_wait_minutes)} 分钟。</span></label><label class="go-consent"><input data-consent type="checkbox" required><span>我已核对航班、日期、机场及等待规则，同意开启航班跟踪。</span></label>`,'确认关联',d=>{
      if(!d.querySelector('[data-consent]').checked)throw Error('请先核对并确认航班安排');
      const value=k=>d.querySelector(`[data-${k}]`).value.trim().toUpperCase();
      return api(`/v1/mobility/rides/orders/${order.order_id}/flight-tracking`,{method:'PUT',body:JSON.stringify({authority_id:d.querySelector('[data-source]').value,expected_revision:b?.revision||0,tracking_enabled:true,delay_protection_enabled:d.querySelector('[data-protection]').checked,flight_identity:{carrier_code:value('carrier'),flight_no:value('flight'),departure_date:value('day'),arrival_airport:value('airport')}})});
    });
  }
  const oldFlight=renderFlightOrder;
  renderFlightOrder=function(){
    oldFlight();const order=state.flightOrder,host=document.createElement('section');host.className='j-panel go-travel-status';host.setAttribute('aria-live','polite');host.innerHTML='<h2>值机与登机牌</h2><p>正在核对航空公司信息…</p>';
    (document.querySelector('.journey-main')||document.querySelector('#app')).append(host);
    const refresh=document.createElement('button');refresh.className='j-select';refresh.textContent='刷新值机状态';
    async function load(){refresh.disabled=true;try{const result=await api(`/v1/flights/orders/${order.order_id}/check-in`);if(host.isConnected&&state.flightOrder?.order_id===order.order_id){host.innerHTML=flightHTML(order,result);host.append(refresh);}}catch{if(host.isConnected){host.innerHTML='<h2>值机与登机牌</h2><p>暂时未能取得航空公司信息，请稍后刷新。</p>';host.append(refresh);}}finally{refresh.disabled=false;}}
    refresh.onclick=load;load();
  };
  const oldRide=renderMobilityOrder;
  renderMobilityOrder=function(kind){
    oldRide(kind);if(kind!=='RIDE')return;
    const order=state.rideOrder,host=document.createElement('section');host.className='card go-travel-status';host.setAttribute('aria-live','polite');host.innerHTML='<h2>航班与接送安排</h2><p>正在核对安排…</p>';document.querySelector('#app').append(host);
    api(`/v1/mobility/rides/orders/${order.order_id}/flight-tracking`).then(result=>{
      if(!host.isConnected||state.rideOrder?.order_id!==order.order_id)return;
      host.innerHTML=rideHTML(result);
      const refresh=document.createElement('button');refresh.className='btn ghost';refresh.textContent='刷新接送安排';host.append(refresh);refresh.onclick=async()=>{refresh.disabled=true;try{await mobilityReload('RIDE')}catch{toast('暂时无法刷新，请稍后重试。')}finally{refresh.disabled=false}};
      if(order.status!=='CONFIRMED')return;
      const edit=document.createElement('button');edit.className='btn ghost';edit.textContent=result.binding?'核对或更换关联航班':'关联抵达航班';host.append(edit);
      edit.onclick=async()=>{try{if(await configure(order,result))await mobilityReload('RIDE')}catch{toast('暂未完成航班关联，请刷新安排后重试。')}};
      if(result.binding?.tracking_enabled){const stop=document.createElement('button');stop.className='btn ghost';stop.textContent='暂停航班跟踪';host.append(stop);stop.onclick=async()=>{try{if(await GOBooking.dialog('暂停航班跟踪','<p>暂停后不再根据航班新信息申请调整接车时间。已经发出的车队申请仍会继续核对。</p>','确认暂停',()=>api(`/v1/mobility/rides/orders/${order.order_id}/flight-tracking`,{method:'PUT',body:JSON.stringify({tracking_enabled:false,expected_revision:result.binding.revision})})))await mobilityReload('RIDE')}catch{toast('暂停结果待核对，请刷新安排。')}};}
    }).catch(()=>{if(host.isConnected)host.innerHTML='<h2>航班与接送安排</h2><p>暂时无法获取跟踪信息，请以订单已确认的接送安排为准。</p>'});
  };
  window.GOTravelStatus={flightHTML,rideHTML,configure};
})();
