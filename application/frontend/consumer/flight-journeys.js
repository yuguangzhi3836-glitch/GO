/* Reference-bound journey revision. Uses the existing GO identity and booking API. */
(() => {
  const kinds = {ONE_WAY:'单程', ROUND_TRIP:'往返', MULTI_CITY:'多程'};
  const emptyLeg = () => ({origin:'', destination:'', departure_date:''});
  let draft = {trip_type:'ROUND_TRIP', adults:1, legs:[emptyLeg(), emptyLeg()]};
  let result = null, selected = [], activeLeg = 0, sort = 'price', refundable = false;
  const esc = uxEsc;
  const dateInput = () => {const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  function leave(fn) { document.body.classList.remove('go-journey'); fn(); }
  function frame(content, aside='') {
    document.body.classList.add('go-journey');
    $('#app').innerHTML = `<div class="journey-frame"><header class="journey-header"><img src="/go-app/assets/go-compact-lockup-v14.svg?v=20260909-depth28" alt="GO AI DIRECT+"><button class="j-text" id="jHome">返回首页</button></header><main class="journey-layout"><div class="journey-main">${content}</div><aside class="journey-aside">${aside || `<span class="j-eyebrow">GO 旅行</span><h2>每一段，<br>都心中有数。</h2><p>逐段选航班，统一核对总价。行李和退改规则，随行程一起看清。</p><div class="j-rule"></div><b>服务状态</b><p>当前未连接航空公司实时库存与价格，无法实际出行。此版本支持 1–9 位成人、经济舱、人民币。</p>`}</aside></main><footer class="journey-footer">GO · 让旅行回归清晰与从容</footer></div>`;
    $('#jHome').onclick=()=>leave(showHome);
  }
  function capture() {
    if($('#jAdults'))draft.adults=Number($('#jAdults').value);
    document.querySelectorAll('[data-j-field]').forEach(el=>{draft.legs[Number(el.dataset.leg)][el.dataset.jField]=el.value.trim().toUpperCase();});
    if(draft.trip_type==='ROUND_TRIP') {
      draft.legs[1].origin=draft.legs[0].destination;
      draft.legs[1].destination=draft.legs[0].origin;
    }
  }
  function legForm(leg, i) {
    const back = draft.trip_type==='ROUND_TRIP' && i===1;
    return `<fieldset class="j-leg-form"><legend>${draft.trip_type==='ROUND_TRIP'?(i?'返程':'去程'):`第 ${i+1} 程`}</legend><div class="j-route-fields">${['origin','destination'].map((key,n)=>`<label>${n?'到达机场':'出发机场'}<input aria-label="第 ${i+1} 程${n?'到达':'出发'}机场" data-j-field="${key}" data-leg="${i}" value="${esc(leg[key])}" placeholder="${n?'东京成田 / NRT':'上海浦东 / PVG'}" maxlength="120" ${back?'readonly':''} required></label>`).join('')}<label>出发日期<input aria-label="第 ${i+1} 程出发日期" type="date" min="${dateInput()}" data-j-field="departure_date" data-leg="${i}" value="${esc(leg.departure_date)}" required></label></div>${draft.trip_type==='MULTI_CITY'&&draft.legs.length>2?`<button type="button" class="j-text j-remove" data-remove="${i}">移除第 ${i+1} 程</button>`:''}</fieldset>`;
  }
  showFlightSearch = function() {
    state.screen='flight';
    frame(`<span class="j-eyebrow">机票 · ${kinds[draft.trip_type]}</span><h1>下一站，由你安排。</h1><p class="j-intro">从一次往返，到一段自由展开的旅程。</p><form id="jSearch" class="j-panel"><div class="j-tabs" role="group" aria-label="行程类型">${Object.entries(kinds).map(([key,label])=>`<button type="button" aria-pressed="${draft.trip_type===key}" data-kind="${key}">${label}</button>`).join('')}</div><label class="j-adults">成人乘机人数<select id="jAdults" required>${Array.from({length:9},(_,i)=>`<option value="${i+1}" ${draft.adults===i+1?'selected':''}>${i+1} 位成人</option>`).join('')}</select></label>${draft.legs.map(legForm).join('')}${draft.trip_type==='MULTI_CITY'?`<button type="button" class="j-text" id="jAdd" ${draft.legs.length===6?'disabled':''}>＋ 添加行程（${draft.legs.length}/6）</button>`:''}<p class="j-help">可输入城市、机场名称或三字码，支持中文及多语言，例如上海浦东、東京成田、PVG。组合行程暂仅支持不同日期出发。</p><div id="jError" class="j-error" role="alert"></div><button class="j-primary" id="jSubmit" type="submit">搜索${kinds[draft.trip_type]}航班 <span aria-hidden="true">→</span></button></form>`);
    document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>{capture();const first=draft.legs[0];draft.trip_type=b.dataset.kind;if(draft.trip_type==='ONE_WAY')draft.legs=[first];else if(draft.legs.length<2)draft.legs.push(emptyLeg());if(draft.trip_type==='ROUND_TRIP'){draft.legs=draft.legs.slice(0,2);draft.legs[1].origin=first.destination;draft.legs[1].destination=first.origin;}showFlightSearch();});
    document.querySelectorAll('[data-j-field]').forEach(el=>el.oninput=()=>{capture();if(draft.trip_type==='ROUND_TRIP'){for(const key of ['origin','destination'])document.querySelector(`[data-leg="1"][data-j-field="${key}"]`).value=draft.legs[1][key];}});
    document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{capture();draft.legs.splice(Number(b.dataset.remove),1);showFlightSearch();});
    if($('#jAdd'))$('#jAdd').onclick=()=>{capture();draft.legs.push({...emptyLeg(),origin:draft.legs.at(-1).destination});showFlightSearch();};
    $('#jSearch').onsubmit=async e=>{
      e.preventDefault();capture();const btn=$('#jSubmit');btn.disabled=true;btn.textContent='正在查找航班…';
      try {
        for(let i=1;i<draft.legs.length;i++)if(draft.legs[i].departure_date<=draft.legs[i-1].departure_date)throw new Error('后续行程请选前一段的次日或之后。');
        if(draft.legs.some(l=>l.origin===l.destination))throw new Error('出发与到达机场不能相同。');
        result=await api('/v1/flights/journeys/search',{method:'POST',body:JSON.stringify({...draft,cabin:'ECONOMY',currency:'CNY'})});
        selected=Array(result.legs.length).fill(null);activeLeg=0;sort='price';refundable=false;renderJourneyResults();
      } catch(err) {$('#jError').textContent=err.message;btn.disabled=false;btn.textContent=`搜索${kinds[draft.trip_type]}航班 →`;}
    };
  };
  function itineraryHTML(segments) {
    return segments.map((s,i)=>`<section class="j-segment"><div class="j-segment-heading"><span class="j-index">${String(i+1).padStart(2,'0')}</span><b>${esc(s.origin)} → ${esc(s.destination)}</b><time>${s.split_party?'各乘机人日期见下方票券':esc(s.departure_date)}</time></div><p>${esc(s.carrier_code)} ${esc(s.flight_number)} · ${esc(s.departure_time)}–${esc(s.arrival_time)} · ${minutesLabel(s.duration_minutes)}</p><div class="j-facts"><span>托运 ${s.baggage?.checked_bag_kg!=null?s.baggage.checked_bag_kg+' kg':'待确认'}</span><span>${s.refund_policy?(s.refund_policy.allowed?`可退 · 费用 ${money(s.refund_policy.fee_minor,s.currency)}`:'不可退'):'退票规则待确认'}</span><span>${s.change_policy?(s.change_policy.allowed?'票价规则允许改签':'不可改签'):'改签规则待确认'}</span></div>${s.total_amount_minor!=null?`<div class="j-segment-price">该程含税 ${money(s.total_amount_minor,s.currency)}</div>`:''}</section>`).join('');
  }
  function cart() {
    const count=selected.filter(Boolean).length,total=selected.reduce((sum,x)=>sum+(x?.total_amount_minor||0),0);
    return `<span class="j-eyebrow">你的${kinds[result.trip_type]}行程</span><h2>每段选择，<br>尽在掌握。</h2><ol class="j-progress">${result.legs.map((leg,i)=>`<li><button class="j-text ${i===activeLeg?'is-current':''}" data-step="${i}"><span class="j-index">${i+1}</span>${esc(leg.criteria.origin)} → ${esc(leg.criteria.destination)}<small>${selected[i]?money(selected[i].total_amount_minor,selected[i].currency):'待选择'}</small></button></li>`).join('')}</ol><div class="j-rule"></div><p>${result.passenger_count||1} 位成人 · 已选 ${count}/${selected.length} 程 · 含税小计</p><strong class="j-cart-price">${money(total)}</strong><p class="j-help">各程按独立机票组合，非航司联程运价，不含联程保护。当前价格未连接航空公司实时库存。</p><div id="jComposeError" role="alert" class="j-error"></div><button id="jCompose" class="j-primary" ${count!==selected.length?'disabled':''}>核对完整行程</button>`;
  }
  function renderJourneyResults() {
    const leg=result.legs[activeLeg];
    let items=leg.items.filter(x=>!refundable||x.refund_policy.allowed);
    items=[...items].sort((a,b)=>sort==='price'?a.total_amount_minor-b.total_amount_minor:a.segments[0].departure_time.localeCompare(b.segments[0].departure_time));
    frame(`<button class="j-text" id="jEdit">← 修改搜索</button><span class="j-eyebrow">第 ${activeLeg+1}/${result.legs.length} 程 · ${esc(leg.criteria.departure_date)}</span><h1>${esc(leg.criteria.origin)} <span class="j-arrow">→</span> ${esc(leg.criteria.destination)}</h1><p class="j-intro">先看完整票价，再决定如何出发。</p><div class="j-toolbar"><label>排序 <select id="jSort"><option value="price" ${sort==='price'?'selected':''}>总价从低到高</option><option value="time" ${sort==='time'?'selected':''}>起飞时间</option></select></label><label><input id="jRefundFilter" type="checkbox" ${refundable?'checked':''}> 只看可退票</label></div><div class="j-flight-list">${items.map(x=>{const s=x.segments[0];return `<article class="j-flight-card ${selected[activeLeg]?.offer_id===x.offer_id?'is-selected':''}"><div class="j-flight-top"><b>${esc(x.fare_family)}</b><span>${esc(x.carrier_code)} ${esc(x.flight_number)}</span></div><div class="j-flight-times"><div><strong>${esc(s.departure_time)}</strong><span>${esc(s.origin)}</span></div><div class="j-flight-duration">${minutesLabel(s.duration_minutes)}<div class="j-airline"></div><small>直飞</small></div><div><strong>${esc(s.arrival_time)}</strong><span>${esc(s.destination)}</span></div></div><div class="j-facts"><span>托运 ${x.baggage.checked_bag_kg} kg</span><span>${x.change_policy.allowed?'可改签':'不可改签'}</span><span>${x.refund_policy.allowed?`可退 · ${money(x.refund_policy.fee_minor)}手续费`:'不可退'}</span></div><div class="j-flight-bottom"><div><small>该程含税总价</small><strong>${money(x.total_amount_minor,x.currency)}</strong></div><button class="j-select" data-select="${esc(x.offer_id)}">${selected[activeLeg]?.offer_id===x.offer_id?'已选择':'选择此程'}</button></div></article>`;}).join('')||'<div class="j-panel">暂无符合筛选的航班，请调整筛选或修改搜索。</div>'}</div>`,cart());
    $('#jEdit').onclick=showFlightSearch;$('#jSort').onchange=e=>{sort=e.target.value;renderJourneyResults();};$('#jRefundFilter').onchange=e=>{refundable=e.target.checked;renderJourneyResults();};
    document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>{activeLeg=Number(b.dataset.step);renderJourneyResults();});
    document.querySelectorAll('[data-select]').forEach(b=>b.onclick=()=>{selected[activeLeg]=leg.items.find(x=>x.offer_id===b.dataset.select);const next=selected.findIndex(x=>!x);if(next>=0)activeLeg=next;renderJourneyResults();});
    $('#jCompose').onclick=async()=>{const b=$('#jCompose');b.disabled=true;b.textContent='正在核对报价…';try{state.flightOffer=await api('/v1/flights/journeys/compose',{method:'POST',body:JSON.stringify({trip_type:result.trip_type,offer_ids:selected.map(x=>x.offer_id)})});state.flightSearch=[state.flightOffer];renderJourneyOffer();}catch(err){$('#jComposeError').textContent=err.message.includes('EXPIRED')?'报价已过期，请修改搜索并重新查询。':err.message;b.disabled=false;b.textContent='重新核对行程';}};
  }
  function renderJourneyOffer() {
    const o=state.flightOffer;
    frame(`<button class="j-text" id="jBack">← 返回选航班</button><span class="j-eyebrow">${kinds[o.trip_type]} · ${o.segments.length} 程</span><h1>把旅程，看完整。</h1><p class="j-intro">逐段核对机场、日期、行李与票价条件。</p><div class="j-panel">${itineraryHTML(o.segments)}</div>`,`<span class="j-eyebrow">行程总价</span><strong class="j-cart-price">${money(o.total_amount_minor,o.currency)}</strong><p>已含税费 ${money(o.tax_amount_minor,o.currency)} · ${o.passenger_count||1} 位成人</p><div class="j-rule"></div><p>${o.refund_policy.allowed?`全程退票手续费合计 ${money(o.refund_policy.fee_minor,o.currency)}`:'包含不可退票价，全程退款当前不可申请。'}</p><p class="j-help">各程独立出票。支持按乘机人和航段选择改签、退票；同日衔接、儿童婴儿与联程保护待补齐。</p><button id="jPrebook" class="j-primary">核验并继续</button><p class="j-help">当前报价未连接航空公司实时库存，不可实际出行。报价可能过期。</p>`);
    $('#jBack').onclick=renderJourneyResults;$('#jPrebook').onclick=()=>{if(!state.me){toast('请登录后继续');leave(showAuth);return;}prebookFlight();};
  }
  renderFlightReview=function() {
    const o=state.flightOffer,p=state.flightPrebook;
    frame(`<button class="j-text" id="jReviewBack">← 返回行程</button><span class="j-eyebrow">下单前核对</span><h1>确认你的每一程。</h1><div class="j-panel">${itineraryHTML(o.segments)}</div>`,`<span class="j-eyebrow">含税应付总额</span><strong class="j-cart-price">${money(p.total_amount_minor,p.currency)}</strong><p>${p.passenger_count||o.passenger_count||1} 位成人 · 经济舱</p><p>报价有效至 ${new Date(p.expires_at).toLocaleString()}</p><p class="j-help">下一步核对乘机人资料并确认支付渠道状态。当前尚未付款或出票。</p><button id="jCreate" class="j-primary">核对乘机人并继续</button>`);
    $('#jReviewBack').onclick=renderJourneyOffer;$('#jCreate').onclick=createFlightOrderAndCheckout;
  };
  renderFlightOrder=function() {
    const o=state.flightOrder, multi=(o.itinerary||[]).length>1;
    const interruptedChange=(o.change_quotes||[]).find(q=>q.status==='AUTHORIZATION_PENDING');
    frame(`<span class="j-eyebrow">机票订单</span><h1>你的完整行程。</h1><div class="j-panel">${itineraryHTML(o.itinerary||[])}</div>${window.GOFlightCoupons.cards(o)}${window.GOFlightCoupons.moneySummary(o)}`,`<span class="j-eyebrow">订单状态</span><h2>${consumerLabel(o.status)}</h2><strong class="j-cart-price">${money(o.total_amount_minor,o.currency)}</strong><p>预订编号 ${esc(o.pnr||'等待出票确认')}</p><p>乘机人 ${esc((o.passengers||[]).map(p=>p.full_name).join('、'))}</p>${o.ticket_assignments?.length?o.ticket_assignments.map(t=>`<p>第 ${t.leg_index+1} 程 · ${esc(t.passenger_name)}<br>票号 ${esc(t.ticket_number)}</p>`).join(''):`<p>票号 ${esc((o.ticket_numbers||[]).join(' / ')||'尚未出票')}</p>`}<p class="j-help">当前订单未连接航空公司出票服务，不可实际出行。</p><div class="j-order-actions">${interruptedChange?'<button class="j-select" id="jResumeChange">继续核对原改签申请</button>':''}<button class="j-select" id="jChange" ${o.status!=='TICKETED'?'disabled':''}>选择乘客与航段改签</button><button class="j-select" id="jRefund" ${!['TICKETED','REFUND_PENDING'].includes(o.status)?'disabled':''}>${o.status==='REFUND_PENDING'?'继续查看退款进度':'查看全程退票费用'}</button>${o.coupons?.length?`<button class="j-select" id="jCouponRefund" ${!['TICKETED','REFUND_PENDING'].includes(o.status)?'disabled':''}>选择乘客退票 / 查看原申请</button>`:''}<button class="j-text" id="jTrips">查看全部行程</button></div>`);
    if($('#jCouponRefund'))$('#jCouponRefund').onclick=()=>window.GOFlightCoupons.refund(o,api,flightReload,()=>state.flightOrder?.order_id===o.order_id);
    $('#jChange').onclick=flightChange;$('#jRefund').onclick=o.status==='REFUND_PENDING'?async()=>{
      try{const refund=(o.refunds||[]).find(r=>r.status==='REFUND_PENDING');const value=await window.GOBooking.dialog('继续核对原退款',`<p>原退款申请已受理，尚未全部完成。应退金额 ${money(refund?.refund_amount_minor,o.currency)}。继续操作会核对同一笔退款。</p>`,'继续核对',()=>api(`/v1/flights/orders/${o.order_id}/refund`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}}));if(value){state.flightOrder=await api(`/v1/flights/orders/${o.order_id}`);renderFlightOrder()}}
      catch(e){toast('退款结果仍在核对中，请稍后查看订单。')}
    }:flightRefund;$('#jTrips').onclick=()=>leave(showUnifiedTrips);
    if($('#jResumeChange'))$('#jResumeChange').onclick=async()=>{
      try{const result=await window.GOBooking.dialog('继续核对原改签申请',`<p>原改签申请的支付确认尚未完成。应付差额 ${money(interruptedChange.total_due_minor,o.currency)}，新出发日期 ${esc(interruptedChange.new_departure_date)}。</p>`,'继续核对',()=>api(`/v1/flights/orders/${o.order_id}/execute-change/${interruptedChange.quote_id}`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:interruptedChange.quote_hash?JSON.stringify(window.GOFlightChanges.confirmation(interruptedChange)):undefined}));if(result){state.flightOrder=await api(`/v1/flights/orders/${o.order_id}`);renderFlightOrder()}}
      catch(e){toast('原改签申请仍在核对中，请稍后查看订单。')}
    };
  };
})();
