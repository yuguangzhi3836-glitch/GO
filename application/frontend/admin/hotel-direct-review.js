(function(global){
  'use strict';
  const BASE='/internal/v1/hotel-autopage/direct-submission-reviews';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const STATES={SUBMITTED:'待审核',APPROVED:'已批准',REVOKED:'已撤销'};
  const ROLES={HERO:'酒店首图',GALLERY:'酒店公区',ROOM:'客房图片',ROOM_TYPE:'房型图片'};
  const LABELS={approve:'批准绑定',publish:'发布酒店页面',revoke:'撤销审核'};
  const FACT_LABELS={physical_room_count:'客房数量',sale_unit:'销售单位',state:'状态',occupancy_json:'入住人数',bed_configurations_json:'床型配置',attributes_json:'房型属性',room_type_id:'房型编号',name:'名称',name_zh:'中文名称',name_en:'英文名称',max_occupancy:'最多入住人数',adults:'成人',children:'儿童',bed_type:'床型',bed_count:'床数',width_cm:'宽度（厘米）',area_sqm:'面积（平方米）',area:'面积',floor:'楼层',window:'窗户',city:'城市',region:'地区',street:'街道',formatted:'完整地址',country:'国家',check_in:'入住',check_out:'退房',smoking:'吸烟政策',breakfast:'早餐'};
  function fact(value){if(value===null||value===undefined||value==='')return '待补充';if(Array.isArray(value))return value.map(fact).join('；');if(typeof value==='object')return Object.entries(value).map(([k,v])=>(FACT_LABELS[k]||k)+'：'+fact(v)).join('；');return ({WHOLE_ROOM:'整间客房',ACTIVE:'启用',INACTIVE:'停用'}[value]||String(value))}
  const name=x=>x?.name_zh||x?.name||x?.name_en||'未命名酒店';
  function conflictText(c){
    const fieldLabels={name:'酒店名称',address:'酒店地址',rooms:'房型目录',policies:'酒店政策',facilities:'酒店设施',website:'官方网站',direct_submission:'提交资料'};
    if(c.field)return (fieldLabels[c.field]||'酒店资料')+'存在来源冲突，须先核对';
    const code=String(c.code||c);
    if(/RIGHTS|AUTHORIZ|LICENSE/.test(code))return '图片授权待核验或已失效';
    if(/ROOM|INVENTORY/.test(code))return '房型对应或完整房型目录需要核对';
    if(/REGISTRATION|ASSOCIATION|IDENTITY/.test(code))return '酒店身份及官方关联需要核对';
    if(/MEDIA|ASSET|ORIGINAL|HASH|IMAGE/.test(code))return '原图文件或清单一致性需要核对';
    if(/STALE|CHANGED|FINGERPRINT/.test(code))return '资料在审核后发生变化，需要重新提交';
    return '存在未通过的核验项目，请核对资料与来源';
  }
  function inspectionHtml(d){
    const r=d.review||{},p=d.property||{},h=d.canonical_hotel||{},a=d.actions||{};
    return `<section class="card"><h3>${esc(name(p))} → ${esc(name(h))}</h3><p>审核状态：${esc(STATES[r.state]||'待核对')} · 页面状态：${d.publication?.publicly_available?'当前可公开读取':'尚未通过公开回读'}</p><div class="business-facts-grid"><p>酒店编号：${esc(p.property_id)}<br>正式酒店编号：${esc(h.hotel_id)}</p><p>供应商：${esc(p.supplier_id)}<br>官方登记：${esc(STATES[d.registration?.state]||'待核验')}</p><p>酒店英文名称：${esc(p.name_en||'待补充')}<br>正式英文名称：${esc(h.name_en||'待补充')}<br>官网：${esc(h.website||'待补充')}</p><p>酒店地址：${esc(fact(p.address_json))}<br>正式地址：${esc(fact(h.address))}</p></div><details><summary>审核来源与清单标识</summary><p>提交人：${esc(r.requested_by)} · 审核人：${esc(r.reviewed_by||'待审核')} · ${esc(r.reviewed_at||'')}</p><p style="overflow-wrap:anywhere">清单：${esc(r.manifest_sha256)}<br>酒店与房型资料：${esc(d.facts_sha256||'尚未通过核验')}</p></details></section>
    <section class="card"><h3>房型对应（${(d.room_mappings||[]).length} 项）</h3><div class="table-wrap"><table><thead><tr><th>酒店房型</th><th>正式房型</th><th>核对</th></tr></thead><tbody>${(d.room_mappings||[]).map(x=>`<tr><td>${esc(x.partner_name||x.partner_room_id)}${x.partner_details?'<details><summary>房型详情</summary><p>'+esc(fact(x.partner_details))+'</p></details>':''}</td><td>${esc(x.canonical_name||x.canonical_room_id)}${x.canonical_details?'<details><summary>正式房型详情</summary><p>'+esc(fact(x.canonical_details))+'</p></details>':''}</td><td>${x.partner_exists===false||x.canonical_exists===false?'对应缺失':'已记录对应，按清单审核'}</td></tr>`).join('')}</tbody></table></div></section>
    <section class="card"><h3>资料与发布冲突</h3>${(d.conflicts||[]).length?d.conflicts.map(x=>`<p>${esc(conflictText(x))}${x.asset_id?' · 图片 '+esc(x.asset_id):''}${x.current_value!==undefined?'<br>当前资料：'+esc(fact(x.current_value)):''}</p>`).join(''):'<p>本次服务端检查未发现阻断项。</p>'}<details><summary>正式酒店资料</summary><p>政策：${esc(fact(h.policies))}</p><p>设施：${esc(fact(h.facilities))}</p><p>介绍：${esc(fact(h.description))}</p></details></section>
    <section class="card"><h3>原图与使用授权（${(d.assets||[]).length} 张）</h3><p>按需查看原图；未打开图片不下载原图文件。</p>${(d.assets||[]).map((x,i)=>`<article class="card"><h4>${esc(ROLES[x.role]||'酒店图片')} · ${esc(x.partner_room_id||'酒店公区')}</h4><p>${Number(x.width)||0} × ${Number(x.height)||0} · ${(Number(x.byte_size||0)/1048576).toFixed(2)} MB · ${x.verification?.original_verified?'原图已核验':'原图待核验'}</p><p>权利人：${esc(x.rights?.rights_holder)} · ${x.verification?.current_rights_verified?'当前授权已核验':'当前授权未通过'}</p><p>授权依据：${esc(x.rights?.evidence_reference)}<br>审核依据：${esc(x.rights?.review_evidence_reference)}<br>授权期限：${esc(x.rights?.expires_at||'未指定期限')}<br>使用范围：${esc((x.rights?.usage_scope||[]).map(scope=>scope==='DISTRIBUTE_ON_GO'?'GO 平台展示与分发':scope).join('、'))}</p><button class="btn" data-preview="${i}">查看原图</button><div data-image="${i}"></div></article>`).join('')}</section>
    <section class="card"><h3>审核与发布</h3><p>批准绑定后仍需单独发布。撤销后，使用此审核的页面及图片停止公开访问。</p><div class="structured-actions">${Object.entries(LABELS).map(([action,label])=>`<button class="btn ${action==='revoke'?'danger':'primary'}" data-action="${action}" ${a['can_'+action]===true&&(action!=='approve'||/^[a-f0-9]{64}$/.test(d.facts_sha256||''))?'':'disabled'}>${label}</button>`).join('')}</div><div data-confirm></div></section>`;
  }
  function createController(api,changed,active=()=>true){
    let epoch=0,busy=false,detail=null,reviewId=null,pending=null;
    const state=()=>({busy,detail,reviewId,pending});
    const emit=()=>{if(active())changed(state())};
    async function open(id){const ticket=++epoch;reviewId=id;detail=null;pending=null;emit();const value=(await api.request(BASE+'/'+encodeURIComponent(id)+'/inspection')).data;if(ticket!==epoch||!active())return false;if(value?.review?.review_id!==id)throw new Error('REVIEW_CHANGED');detail=value;emit();return true}
    function prepare(action){if(busy||!detail||detail.actions?.['can_'+action]!==true)return false;if(action==='approve'&&!/^[a-f0-9]{64}$/.test(detail.facts_sha256||''))return false;pending={action,reviewId,hash:detail.review.manifest_sha256,factsHash:detail.facts_sha256,state:detail.review.state};emit();return true}
    async function confirm(){
      if(busy||!pending||!active())return false;
      const intent=pending,ticket=epoch;pending=null;busy=true;emit();
      try{
        const current=(await api.request(BASE+'/'+encodeURIComponent(intent.reviewId)+'/inspection')).data;
        if(ticket!==epoch||!active())return false;
        if(current.review?.review_id!==intent.reviewId){detail=null;throw new Error('REVIEW_CHANGED')}
        if((intent.action==='approve'&&current.facts_sha256!==intent.factsHash)||current.review?.manifest_sha256!==intent.hash||current.review?.state!==intent.state||current.actions?.['can_'+intent.action]!==true){detail=current;throw new Error('REVIEW_CHANGED')}
        await api.request(BASE+'/'+encodeURIComponent(intent.reviewId)+'/'+intent.action,{method:'POST',...(intent.action==='approve'?{body:{expected_sha256:intent.hash,expected_facts_sha256:intent.factsHash}}:{})});
        if(ticket!==epoch||!active())return false;
        const refreshed=(await api.request(BASE+'/'+encodeURIComponent(intent.reviewId)+'/inspection')).data;
        if(ticket!==epoch||!active())return false;if(refreshed?.review?.review_id!==intent.reviewId)throw new Error('REVIEW_CHANGED');detail=refreshed;return true;
      }finally{busy=false;emit()}
    }
    return {state,open,prepare,confirm,cancel(){pending=null;emit()},dispose(){epoch++;detail=null;pending=null}};
  }
  function mount(ctx){
    const {root,api,notice}=ctx;
    root.innerHTML='<section class="card"><h2>酒店资料审核与图片发布</h2><p>核对酒店身份、正式房型和原图授权，再批准绑定及发布。</p><button class="btn" data-back>返回酒店网页工厂</button></section><section class="card"><label>酒店编号筛选 <input data-property placeholder="全部酒店"></label><label> 审核状态 <select data-state><option value="">全部</option><option value="SUBMITTED">待审核</option><option value="APPROVED">已批准</option><option value="REVOKED">已撤销</option></select></label><button class="btn" data-search>查询</button><p data-status role="status" aria-live="polite"></p><div data-list></div><button class="btn" data-prev>上一页</button><button class="btn" data-next>下一页</button></section><div data-detail></div>';
    const panel=root.querySelector('[data-detail]'),status=root.querySelector('[data-status]'),list=root.querySelector('[data-list]');
    let listEpoch=0,offset=0,total=0,urls=[];
    const sessionAtMount=api.csrf?.();
    const active=()=>{if(!root.contains(panel)||!panel.isConnected)return false;if(api.csrf?.()!==sessionAtMount){panel.innerHTML='';list.innerHTML='';status.textContent='登录会话已变化，请重新打开审核页面。';return false}return true};
    const release=()=>{urls.forEach(url=>URL.revokeObjectURL(url));urls=[]};
    const error=e=>e?.message==='REVIEW_CHANGED'?'资料或状态已变化，请重新核对后确认。':'操作未完成，请刷新核对当前状态；请勿据此认定已批准或已发布。';
    const controller=createController(api,s=>{
      if(!active())return;release();panel.innerHTML=s.detail?inspectionHtml(s.detail):'<p>正在读取审核资料…</p>';
      panel.querySelectorAll('button').forEach(b=>{if(s.busy)b.disabled=true});
      if(s.pending)panel.querySelector('[data-confirm]').innerHTML=`<p>请确认对“${esc(name(s.detail.property))}”执行“${LABELS[s.pending.action]}”。</p><button class="btn primary" data-commit>确认执行</button><button class="btn" data-cancel>返回核对</button>`;
    },active);
    async function load(){
      const ticket=++listEpoch;controller.dispose();release();panel.innerHTML='';status.textContent='正在查询…';
      const property=root.querySelector('[data-property]').value.trim(),state=root.querySelector('[data-state]').value;
      const filters={offset,limit:25};if(property)filters.property_id=property;if(state)filters.state=state;
      try{const d=(await api.request(BASE+'?'+new URLSearchParams(filters))).data;
        if(ticket!==listEpoch||!active())return;total=d.total||0;
        list.innerHTML=(d.items||[]).map(x=>`<article class="business-fact"><span>${esc(x.property_name||x.property_id)} · ${esc(STATES[x.state]||'待核对')}</span><button class="btn" data-review="${esc(x.review_id)}">查看审核资料</button></article>`).join('')||'<p>没有匹配的审核记录。</p>';
        status.textContent=`共 ${total} 条，当前第 ${Math.floor(offset/25)+1} 页`;root.querySelector('[data-prev]').disabled=offset===0;root.querySelector('[data-next]').disabled=offset+25>=total;
      }catch(e){if(ticket===listEpoch&&active())status.textContent=error(e)}
    }
    root.onclick=async event=>{
      const b=event.target.closest('button');if(!active()||!b||!root.contains(b)||b.disabled)return;
      if(controller.state().busy)return;
      try{
        if(b.hasAttribute('data-back')){controller.dispose();listEpoch++;release();root.onclick=null;return ctx.back?.()}
        if(b.hasAttribute('data-search')){offset=0;return load()}
        if(b.hasAttribute('data-prev')){offset=Math.max(0,offset-25);return load()}
        if(b.hasAttribute('data-next')){offset+=25;return load()}
        if(b.hasAttribute('data-review'))return await controller.open(b.dataset.review);
        if(b.hasAttribute('data-action'))return controller.prepare(b.dataset.action);
        if(b.hasAttribute('data-cancel'))return controller.cancel();
        if(b.hasAttribute('data-commit')){if(await controller.confirm()){status.textContent='操作已提交并重新读取状态，请查看审核及页面回读结果。';notice(status.textContent)}return}
        if(b.hasAttribute('data-preview')){
          const snapshot=controller.state(),asset=snapshot.detail.assets[Number(b.dataset.preview)];b.disabled=true;
          const blob=await api.requestBlob(BASE+'/'+encodeURIComponent(snapshot.reviewId)+'/media/'+encodeURIComponent(asset.asset_id));
          if(!active()||controller.state().detail!==snapshot.detail)return;
          const url=URL.createObjectURL(blob);urls.push(url);const target=panel.querySelector('[data-image="'+b.dataset.preview+'"]');
          if(target)target.innerHTML=`<img src="${esc(url)}" alt="酒店提交原图" style="max-width:100%;height:auto" loading="lazy">`;b.textContent='原图已加载';
        }
      }catch(e){if(active()){status.textContent=error(e);notice(status.textContent,true);if(b.hasAttribute('data-preview'))b.disabled=false}}
    };
    void load();return {dispose(){controller.dispose();listEpoch++;release();root.onclick=null}};
  }
  global.GO_HOTEL_DIRECT_REVIEW={mount,createController,inspectionHtml,conflictText};
})(typeof window==='undefined'?globalThis:window);
