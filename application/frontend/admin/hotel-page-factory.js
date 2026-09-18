(function(){
  const STAGE_LABELS={NEEDS_ENRICHMENT:'资料待补齐',WAIT_BUILD:'待建网页',COLLECTING:'采集中',WAIT_MERGE:'待合并',WAIT_MEDIA_REVIEW:'待媒体审核',WAIT_PUBLISH:'待发布',PUBLISHED:'已发布',WAIT_CLAIM:'待酒店认领',CLAIMED:'已认领',GO_DIRECT:'GO Direct'};
  const PAGE_LABELS={PUBLISHED:'已发布',DRAFT:'待发布'};
  const DIRECT_LABELS={NOT_REGISTERED:'待酒店认领',REGISTRATION_PENDING:'已认领 · 待核验',GO_DIRECT_VERIFIED:'GO Direct 已核验',GO_DIRECT_LIVE:'GO Direct'};
  const RIGHTS_LABELS={RIGHTS_UNKNOWN:'待审核',AUTHORIZED:'已授权',HOTEL_SUBMITTED:'酒店提交',DISTRIBUTION_LICENSE:'分销授权',PUBLIC_BUSINESS_FACT:'公开商业事实'};
  const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const valueText=v=>v===null||v===undefined||v===''?'—':String(v);
  function metric(label,value,sub=''){return `<div class="card structured-metric"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(valueText(value))}</div>${sub?`<div class="metric-sub">${esc(sub)}</div>`:''}</div>`}
  function stageTabs(counts){return Object.keys(STAGE_LABELS).map(k=>`<button class="btn factory-stage" data-stage="${k}">${STAGE_LABELS[k]} <b>${Number(counts?.[k]||0)}</b></button>`).join('')}
  function addressText(v){if(!v)return '地址待完善';if(typeof v==='string')return v;return v.formatted||[v.street,v.city,v.region,v.country].filter(Boolean).join(' · ')||'地址待完善'}
  function factoryRow(x){const stage=STAGE_LABELS[x.primary_stage]||'待处理';return `<article class="card factory-hotel-card" data-factory-stage="${esc(x.primary_stage)}" data-name="${esc((x.name||'').toLowerCase())}">
    <div class="factory-hotel-main"><div><div class="factory-card-title">${esc(x.name||'未命名酒店')}</div><div class="factory-card-sub">${esc(addressText(x.address))}</div></div><span class="status ${x.primary_stage==='GO_DIRECT'?'ok':x.primary_stage==='WAIT_MEDIA_REVIEW'?'warn':''}">${esc(stage)}</span></div>
    <div class="factory-mini-grid"><span>资料完整度 <b>${Math.round(Number(x.completeness_bps||0)/100)}%</b></span><span>来源 <b>${Number(x.source_count||0)}</b></span><span>房型 <b>${Number(x.room_count||0)}</b></span><span>图片 <b>${Number(x.image_count||0)}</b></span></div>
    <div class="structured-actions"><button class="btn primary" data-open-hotel="${esc(x.hotel_id)}">查看与处理</button>${x.slug&&x.page_state==='PUBLISHED'?`<a class="btn" href="/v1/hotel-pages/${encodeURIComponent(x.slug)}" target="_blank" rel="noopener">页面预览</a>`:''}</div>
  </article>`}
  function seedRow(x){return `<article class="card factory-hotel-card" data-factory-stage="WAIT_BUILD" data-name="${esc((x.name||'').toLowerCase())}"><div class="factory-hotel-main"><div><div class="factory-card-title">${esc(x.name||'待采集酒店')}</div><div class="factory-card-sub">${esc(addressText(x.address))}</div></div><span class="status warn">待建网页</span></div><p class="metric-sub">种子已登记，尚未形成酒店标准档案。</p><details class="tech-diagnostics"><summary>技术信息</summary><div class="mono">任务编号：${esc(x.job_id||'—')}</div></details></article>`}
  function sourceRows(items){if(!items?.length)return `<div class="structured-empty"><div><h3>暂无来源快照</h3><p>完成采集后，系统会在这里保留来源、观察时间和事实等级。</p></div></div>`;return `<div class="table-wrap"><table><thead><tr><th>来源</th><th>类型</th><th>Rights</th><th>可信度</th><th>最后观察</th></tr></thead><tbody>${items.map(x=>`<tr><td>${x.source_url?`<a href="${esc(x.source_url)}" target="_blank" rel="noopener">${esc(x.source_key)}</a>`:esc(x.source_key)}</td><td>${esc(x.source_type)}</td><td>${esc(RIGHTS_LABELS[x.rights_status]||x.rights_status)}</td><td>${Math.round(Number(x.confidence_bps||0)/100)}%</td><td>${esc(x.observed_at||'—')}</td></tr>`).join('')}</tbody></table></div>`}
  function contactRows(items){if(!items?.length)return '<p class="metric-sub">尚未发现公开联系方式。</p>';return items.slice(0,8).map(x=>`<div class="business-fact"><span>${esc(x.contact_type||'联系')}</span><b>${esc(x.value)}</b></div>`).join('')}
  function detailsHtml(d){const p=d.profile||{},f=d.factory||{},disp=d.display||{},an=d.anomalies||[],media=d.media||{};const canPublish=p.page_state!=='PUBLISHED';return `<div class="productized-admin-head"><div><h2>${esc(disp.name||'酒店网页')}</h2><p>${esc(addressText(disp.address))}</p></div><span class="status ${f.primary_stage==='GO_DIRECT'?'ok':''}">${esc(STAGE_LABELS[f.primary_stage]||f.primary_stage)}</span></div>
    <div class="grid structured-metrics">${metric('资料完整度',Math.round(Number(p.completeness_bps||0)/100)+'%')}${metric('来源数',f.source_count||0)}${metric('房型数',f.room_count||0)}${metric('图片数',media.count||0,media.rights_pending_count?`${media.rights_pending_count} 张待 Rights 审核`:'Rights 已无待审')}</div>
    ${an.length?`<section class="card"><div class="section-head"><h2>待办与异常</h2><span class="status warn">${an.length} 项</span></div>${an.map(x=>`<div class="business-fact"><span>需要处理</span><b>${esc(anomalyLabel(x))}</b></div>`).join('')}</section>`:`<section class="card structured-section"><div><h3>当前无阻断异常</h3><p>页面仍需按来源证据、媒体 Rights 和酒店认领状态持续维护。</p></div><span class="status ok">正常</span></section>`}
    <section class="card"><div class="section-head"><h2>运营动作</h2><span>只执行单酒店受控动作</span></div><div class="structured-actions"><button class="btn" data-factory-action="recollect" ${f.latest_discovery_job_id?'':'disabled'}>重新采集</button><button class="btn" data-factory-action="compose">重新生成</button><button class="btn ${canPublish?'primary':'danger'}" data-factory-action="${canPublish?'publish':'unpublish'}">${canPublish?'发布网页':'下架网页'}</button>${d.preview_url?`<a class="btn" href="${esc(d.preview_url)}" target="_blank" rel="noopener">页面预览</a>`:''}</div></section>
    <div class="split"><section class="card"><div class="section-head"><h2>联系方式</h2><span>${Number(f.contact_count||0)} 条</span></div><div class="business-facts-grid">${contactRows(d.contacts||[])}</div></section><section class="card"><div class="section-head"><h2>媒体 Rights</h2><span>${Number(media.count||0)} 张</span></div>${Object.entries(media.rights_summary||{}).map(([k,v])=>`<div class="business-fact"><span>${esc(RIGHTS_LABELS[k]||k)}</span><b>${Number(v)}</b></div>`).join('')||'<p class="metric-sub">尚未下载媒体资产。</p>'}</section></div>
    <section class="section"><div class="section-head"><h2>来源与事实证据</h2><span>Source Snapshot</span></div>${sourceRows(d.sources||[])}</section>
    <details class="card tech-diagnostics"><summary>技术信息 / 高级信息</summary><div class="business-facts-grid" style="margin-top:12px"><div class="business-fact"><span>Hotel ID</span><b class="mono">${esc(p.hotel_id)}</b></div><div class="business-fact"><span>Slug</span><b class="mono">${esc(p.slug)}</b></div><div class="business-fact"><span>原始页面状态</span><b class="mono">${esc(p.page_state)}</b></div><div class="business-fact"><span>原始 GO Direct 状态</span><b class="mono">${esc(p.go_direct_state)}</b></div><div class="business-fact"><span>最近 Discovery Job</span><b class="mono">${esc(f.latest_discovery_job_id||'—')}</b></div></div></details>`}
  // One reviewed facts-only recovery plan; new plans require a reviewed candidate.
  const IMPORT_HOTEL='hotel_ac72aa53c89d4c3984b72436cb85f617';
  const IMPORT_PROTECTED=[IMPORT_HOTEL,'hotel_d17851be16724affb355375cacc5e58c'];
  const reviewedPlans=new WeakSet();
  function freezeImport(value){if(value&&typeof value==='object'){Object.values(value).forEach(freezeImport);Object.freeze(value)}return value}
  const IMPORT_PLAN_SHA='a78aed8aa3a504a7ab165e3c6e4d9f5b335cd49a7d4d3c0128c7a2f4eae2db66';
  const SOURCE_RANK={HOTEL_OFFICIAL_SUBMISSION:100,OFFICIAL_WEBSITE:95,GROUP_OFFICIAL:94,CRS_PMS:90,CONTENT_PROVIDER:80,AUTHORIZED_DISTRIBUTOR:70,OTA_DISTRIBUTION:68,OTA_DISCOVERY:46,PUBLIC_SOURCE:45};
  const stable=v=>Array.isArray(v)?'['+v.map(stable).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stable(v[k])).join(',')+'}':JSON.stringify(v);
  function requireImport(ok,message){if(!ok)throw new Error(message)}
  async function reviewedPlan(text,hotelId){
    requireImport(typeof text==='string'&&new TextEncoder().encode(text).length<=1048576,'请选择不超过 1 MB 的审定 JSON 文件');
    let plan;try{plan=JSON.parse(text)}catch{throw new Error('文件不是有效的 JSON，请重新选择审定文件')}
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stable(plan)));
    const hash=Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');
    requireImport(hash===IMPORT_PLAN_SHA,'文件内容与已审定版本不一致，请核对文件；未写入资料');
    requireImport(hotelId===IMPORT_HOTEL&&plan.selected_existing_id===hotelId,'该资料包只能导入指定的敖麓谷雅酒店档案');
    const bodies=plan.operations.slice(1).map(op=>{const body=JSON.parse(JSON.stringify(op.body));delete body.payload.recovery_source_manifest_sha256;return body});
    const reviewed=freezeImport({hotelId,hash,bodies,rooms:bodies[2].payload.rooms});reviewedPlans.add(reviewed);return reviewed;
  }
  async function importPreflight(api,plan){
    requireImport(reviewedPlans.has(plan),'请先选择并核对审定文件');
    const identity=(await api.request('/bff/auth/me')).data||{};
    requireImport(identity.actor_type==='GO_ADMIN'&&identity.permissions?.includes('admin:rules'),'当前账号没有资料维护权限，请使用已有授权管理员账号');
    const scope=(await api.request('/internal/v1/hotel-infrastructure/catalog-scope/preview')).data||{};
    requireImport(stable([...(scope.protected_ids||[])].sort())===stable([...IMPORT_PROTECTED].sort())&&scope.physical_deletion===false&&scope.immutable_audit_retained===true,'保护范围未通过核验，请先完成已审核的酒店库整理');
    const overview=(await api.request('/internal/v1/hotel-autopage/factory/overview?limit=1000')).data||{};
    requireImport(overview.total_hotels===2&&stable((overview.items||[]).map(x=>x.hotel_id).sort())===stable([...IMPORT_PROTECTED].sort()),'请先完成敖麓谷雅保护范围内的酒店库整理，再导入资料');
    requireImport(scope.running_queue_count===0,'仍有建库任务处理中，请待当前任务结束后重试');
    const detail=(await api.request(`/internal/v1/hotel-autopage/factory/hotels/${encodeURIComponent(plan.hotelId)}`)).data;
    const other=(await api.request(`/internal/v1/hotel-autopage/factory/hotels/${encodeURIComponent(IMPORT_PROTECTED[1])}`)).data;
    requireImport(!(other.sources||[]).some(s=>plan.bodies.some(b=>b.source_key===s.source_key)),'来源已关联另一条酒店档案，请先核对身份');
    const current=detail.profile?.canonical_json||{},provenance=detail.profile?.field_provenance_json||{};
    for(const body of plan.bodies)for(const [field,value] of Object.entries(body.payload)){
      if(field==='phone'||current[field]===undefined||current[field]===null||stable(current[field])===stable(value)||stable(current[field])==='[]'||current[field]==='')continue;
      const previous=provenance[field],rank=SOURCE_RANK[previous?.source_type],incoming=SOURCE_RANK[body.source_type];
      requireImport(previous&&rank!==undefined,'现有资料来源尚未核准，请先核对冲突');
      requireImport(incoming>rank||(incoming===rank&&body.confidence_bps>=Number(previous.confidence_bps??5000)),'现有资料的来源等级更高，导入已停止；请先核对来源冲突');
    }
    return detail;
  }
  function verifyImported(plan,detail){
    requireImport(detail.profile?.hotel_id===plan.hotelId&&detail.profile.page_state==='DRAFT','资料写入后未保持草稿状态，请核对');
    const canonical=detail.profile.canonical_json||{};
    for(const body of plan.bodies)for(const [field,value] of Object.entries(body.payload)){
      if(field==='phone'){
        const number=String(value).replace(/[^0-9+]/g,'');
        requireImport((detail.contacts||[]).some(c=>c.channel==='PHONE'&&c.normalized_value===number&&c.is_public_business_contact===true&&!c.do_not_contact),'联系电话回读不一致，请核对');
      }else requireImport(stable(canonical[field])===stable(value),'资料回读不一致，可能存在来源冲突；请核对后再继续');
    }
    requireImport(detail.media?.publishable_count===0,'发现可发布图片，请先核对图片授权；本次不发布网页');
  }
  async function executeImport(api,plan,progress=()=>{}){
    // Recheck permission/current facts immediately before every import attempt.
    await importPreflight(api,plan);
    await api.request(`/internal/v1/hotel-autopage/factory/hotels/${encodeURIComponent(plan.hotelId)}/publication`,{method:'POST',body:{action:'UNPUBLISH'}});
    let completed=0;
    for(const body of plan.bodies){
      const response=(await api.request('/internal/v1/hotel-autopage/sources/ingest',{method:'POST',body})).data;
      requireImport(response?.profile?.hotel_id===plan.hotelId,'返回了不同酒店身份，已停止后续导入');
      completed++;progress(completed);
    }
    const detail=(await api.request(`/internal/v1/hotel-autopage/factory/hotels/${encodeURIComponent(plan.hotelId)}`)).data;
    verifyImported(plan,detail);return detail;
  }
  function importPanel(){return `<section class="card" aria-labelledby="catalogImportTitle"><div class="section-head"><h2 id="catalogImportTitle">导入审定资料</h2><span>敖麓谷雅 · 保存为草稿</span></div><p>导入已核准的官网信息、联系方式及 17 个历史房型。图片授权尚待核验，本次不导入图片，不发布网页。</p><label class="business-field"><span>选择审定资料文件</span><input id="catalogImportFile" type="file" accept=".json,application/json"></label><p id="catalogImportStatus" role="status" aria-live="polite">选择 JSON 文件后，先核对资料与来源。</p><div class="structured-actions"><button class="btn" id="catalogImportReview">核对资料</button><button class="btn primary" id="catalogImportApply" disabled>确认导入为草稿</button></div></section>`}
  function bindImport(hotelId,ctx){
    const {api,root,notice}=ctx;const file=root.querySelector('#catalogImportFile');if(!file)return;
    const review=root.querySelector('#catalogImportReview'),apply=root.querySelector('#catalogImportApply'),status=root.querySelector('#catalogImportStatus');let prepared=null,busy=false;
    file.onchange=()=>{prepared=null;apply.disabled=true;status.textContent='文件已变更，请重新核对资料。'};
    review.onclick=async()=>{if(busy)return;busy=true;review.disabled=true;file.disabled=true;apply.disabled=true;prepared=null;try{
      requireImport(file.files?.length===1,'请选择审定 JSON 文件');requireImport(file.files[0].size<=1048576,'文件不能超过 1 MB');
      const candidate=await reviewedPlan(await file.files[0].text(),hotelId);await importPreflight(api,candidate);prepared=candidate;
      status.textContent='核对通过：官网资料 2 组、历史房型 17 个、图片 0 张。将先下架网页，再保存为草稿。';apply.disabled=false;
    }catch(e){status.textContent=catalogError(e);notice(status.textContent,true)}finally{busy=false;review.disabled=false;file.disabled=false}};
    apply.onclick=async()=>{if(busy||!prepared)return;busy=true;file.disabled=true;review.disabled=true;apply.disabled=true;
      root.querySelectorAll('[data-factory-action]').forEach(b=>b.disabled=true);let completed=0;
      try{await executeImport(api,prepared,n=>{completed=n;status.textContent=`已保存 ${n}/3 组来源资料，正在核对…`});notice('17 个房型及官网资料已保存并回读核对，保持草稿；图片仍待授权核验');await openHotel(hotelId,ctx)}
      catch(e){status.textContent=`导入已停止，已返回成功 ${completed}/3 组来源；网页保持待核对。${catalogError(e)}`;notice(status.textContent,true);prepared=null}
      finally{busy=false;file.disabled=false;review.disabled=false}
    };
  }

  const reviewedScopes=new WeakSet();
  function assertScope(scope){
    requireImport(stable([...(scope.protected_ids||[])].sort())===stable([...IMPORT_PROTECTED].sort()),'敖麓谷雅保护范围已变化，请重新核对');
    requireImport(Array.isArray(scope.archived_ids)&&scope.archived_ids.length===112&&new Set(scope.archived_ids).size===112&&!scope.archived_ids.some(id=>IMPORT_PROTECTED.includes(id)),'历史资料范围已变化，请重新核对');
    requireImport(scope.physical_deletion===false&&scope.immutable_audit_retained===true,'当前操作不符合保留审计记录的归档要求');
    requireImport(scope.running_queue_count===0,'仍有建库任务处理中，请待当前任务结束后重试');
    requireImport(/^[a-f0-9]{64}$/.test(scope.scope_sha256||''),'归档范围缺少有效核对标识，请重新读取');
  }
  async function requireCatalogWriter(api){
    const identity=(await api.request('/bff/auth/me')).data||{};
    requireImport(identity.actor_type==='GO_ADMIN'&&identity.permissions?.includes('admin:rules'),'当前账号没有资料维护权限，请使用已有授权管理员账号');
  }
  async function previewScope(api){
    await requireCatalogWriter(api);
    const scope=(await api.request('/internal/v1/hotel-infrastructure/catalog-scope/preview')).data||{};assertScope(scope);
    const overview=(await api.request('/internal/v1/hotel-autopage/factory/overview?limit=1000')).data||{};
    const ids=(overview.items||[]).map(x=>x.hotel_id).sort();
    const active=overview.total_hotels===2&&stable(ids)===stable([...IMPORT_PROTECTED].sort());
    requireImport(active||(overview.total_hotels===114&&stable(ids)===stable([...scope.protected_ids,...scope.archived_ids].sort())),'酒店列表与归档范围不一致，请重新核对');
    const names=Object.fromEntries((overview.items||[]).map(x=>[x.hotel_id,x.name||'未命名酒店']));
    const result=freezeImport({scope:JSON.parse(JSON.stringify(scope)),names,alreadyActive:active});reviewedScopes.add(result);return result;
  }
  async function activateScope(api,reviewed,progress=()=>{}){
    requireImport(reviewedScopes.has(reviewed)&&!reviewed.alreadyActive,'请先读取并核对本次归档范围');
    await requireCatalogWriter(api);
    const fresh=(await api.request('/internal/v1/hotel-infrastructure/catalog-scope/preview')).data||{};assertScope(fresh);
    requireImport(fresh.scope_sha256===reviewed.scope.scope_sha256&&stable([...fresh.archived_ids].sort())===stable([...reviewed.scope.archived_ids].sort()),'核对后资料已变化，请重新预览；尚未归档');
    const activated=(await api.request('/internal/v1/hotel-infrastructure/catalog-scope/activate',{method:'POST',body:{scope_sha256:reviewed.scope.scope_sha256}})).data||{};assertScope(activated);
    requireImport(activated.scope_sha256===reviewed.scope.scope_sha256,'归档返回标识不一致，请核对结果');
    const overview=(await api.request('/internal/v1/hotel-autopage/factory/overview?limit=1000')).data||{};
    requireImport(overview.total_hotels===2&&stable((overview.items||[]).map(x=>x.hotel_id).sort())===stable([...IMPORT_PROTECTED].sort()),'归档后列表核对未通过，请勿继续导入');
    let checked=0;
    for(const id of reviewed.scope.archived_ids){
      let archived=false;
      try{await api.request(`/internal/v1/hotel-autopage/factory/hotels/${encodeURIComponent(id)}`)}
      catch(e){if(e.status===409&&e.payload?.detail==='CATALOG_RECORD_ARCHIVED')archived=true;else throw e}
      requireImport(archived,'仍有历史酒店资料可见，请核对归档结果');checked++;progress(checked);
    }
    // Consume the review after success: another activation needs a fresh preview.
    reviewedScopes.delete(reviewed);return {retained:2,archived:checked,physicalDeletion:false};
  }
  function scopeEntry(){return '<section class="card structured-section"><div><h3>整理历史建库记录</h3><p>保留敖麓谷雅档案，将其他历史酒店资料从当前建库列表归档。来源与审计记录保留。</p></div><button class="btn" id="catalogScopeOpen">预览保留与归档清单</button></section>'}
  function scopeRows(ids,names){return ids.map(id=>`<li><strong>${esc(names[id]||'历史酒店资料')}</strong><small class="mono" style="display:block;overflow-wrap:anywhere">${esc(id)}</small></li>`).join('')}
  async function openScope(ctx){
    const {api,root,notice}=ctx;root.innerHTML='<section class="card"><h2>正在核对历史酒店资料…</h2></section>';
    try{
      const reviewed=await previewScope(api),scope=reviewed.scope;
      root.innerHTML=`<div class="structured-actions"><button class="btn" id="scopeBack">返回酒店建库</button></div><section class="card"><h2>核对保留与归档清单</h2><p>保留敖麓谷雅 ${scope.protected_ids.length} 条档案；归档其他 ${scope.archived_ids.length} 条历史酒店资料。归档保留原始记录，不执行物理删除。</p><h3>保留档案</h3><ul>${scopeRows(scope.protected_ids,reviewed.names)}</ul><details><summary>查看 ${scope.archived_ids.length} 条归档清单</summary><ul>${scopeRows(scope.archived_ids,reviewed.names)}</ul></details><details><summary>本次核对标识</summary><p class="mono" style="overflow-wrap:anywhere">${esc(scope.scope_sha256)}</p></details><p id="scopeStatus" role="status" aria-live="polite">${reviewed.alreadyActive?'当前已完成保护范围内的整理，可返回敖麓谷雅导入资料。':'请核对清单。确认后将归档上述历史资料。'}</p><button class="btn primary" id="scopeActivate" ${reviewed.alreadyActive?'disabled':''}>确认归档 ${scope.archived_ids.length} 条历史资料</button></section>`;
      root.querySelector('#scopeBack').onclick=()=>render(ctx);
      const button=root.querySelector('#scopeActivate'),status=root.querySelector('#scopeStatus'),back=root.querySelector('#scopeBack');
      button.onclick=async()=>{if(button.disabled)return;button.disabled=true;back.disabled=true;
        try{const result=await activateScope(api,reviewed,n=>status.textContent=`归档已提交，正在核对 ${n}/${scope.archived_ids.length} 条资料…`);status.textContent=`已核对：保留 ${result.retained} 条敖麓谷雅档案，${result.archived} 条历史资料已归档。可返回酒店建库继续导入。`;notice('历史建库资料归档及回读核对完成')}
        catch(e){status.textContent='本次操作未完成核验，请重新预览当前状态后处理。'+catalogError(e);notice(status.textContent,true)}
        finally{back.disabled=false}
      };
    }catch(e){root.innerHTML='<section class="card"><h2>暂不能整理历史资料</h2><p id="scopeError"></p><button class="btn" id="scopeBack">返回酒店建库</button></section>';root.querySelector('#scopeError').textContent=catalogError(e);root.querySelector('#scopeBack').onclick=()=>render(ctx);notice(catalogError(e),true)}
  }
  function catalogError(error){const map={PERMISSION_DENIED:'当前账号没有资料维护权限',CATALOG_SCOPE_CHANGED_REVIEW_AGAIN:'资料范围已变化，请重新预览',CATALOG_ACTIVE_BUILD_MUST_FINISH:'建库任务尚未结束，请稍后重试',CATALOG_RECORD_ARCHIVED:'这条历史资料已归档',SOURCE_CANONICAL_IDENTITY_CONFLICT:'来源关联的酒店身份存在冲突，请核对'};return map[error?.message]||(/[\u3400-\u9fff]/.test(error?.message||'')?error.message:'操作未完成，请核对账号权限与当前资料状态后重试。')}
  const ANOMALY_LABELS={CATALOG_STRUCTURE_INVALID:'资料格式需要核对',DECLARED_ROOM_IDENTITIES_REQUIRED:'房型官方目录待核对',ROOM_IDENTITIES_NOT_UNIQUE:'房型唯一身份待核对',DECLARED_ROOM_PARITY_INCOMPLETE:'房型目录尚未完整对齐',FULL_ROOM_TYPE_INVENTORY_NOT_VERIFIED:'完整房型清单尚未核验',INVENTORY_REVIEW_DOCUMENT_MISMATCH:'房型目录核验材料不一致',ROOM_CORE_FACTS_INCOMPLETE:'房型面积、床型或入住人数待补齐',ROOM_DOCUMENT_EVIDENCE_MISMATCH:'房型来源材料待核对',ROOM_OFFICIAL_PHOTO_PARITY_INCOMPLETE:'房型官方图片尚未完整对应',VERIFIED_OFFICIAL_HERO_MISSING:'酒店主图尚未核验',OFFICIAL_WEBSITE_REQUIRED:'酒店官网地址待核验',MEDIA_RIGHTS_PENDING:'图片授权待核验',DISCOVERY_FAILURE:'资料来源采集失败'};
  for(const [field,label] of Object.entries({NAME:'酒店名称',ADDRESS:'酒店地址',WEBSITE:'酒店官网',ROOMS:'房型资料',POLICIES:'酒店政策',FACILITIES:'酒店设施',CATALOG_MANIFEST:'官方房型目录',MEDIA_CANDIDATES:'图片清单'})){
    ANOMALY_LABELS[field+'_MISSING']=label+'待补齐';ANOMALY_LABELS[field+'_OFFICIAL_SOURCE_REQUIRED']=label+'的官方来源待核验';ANOMALY_LABELS[field+'_CONFLICT']=label+'存在来源冲突，待核对';
  }
  function anomalyLabel(item){return ANOMALY_LABELS[item?.code]||(/[\u3400-\u9fff]/.test(item?.label||'')?item.label:'酒店资料需要核对')}

  async function render(ctx){
    const {api,root,notice}=ctx; let overview;
    root.innerHTML='<div class="card"><h2>全国酒店数字基础设施控制台</h2><p>正在读取全国建库与页面生产状态…</p></div>';
    let infra={runs:[],provider_count:0},exceptions={items:[]};
    try{overview=(await api.request('/internal/v1/hotel-autopage/factory/overview?limit=500')).data||{};infra=(await api.request('/internal/v1/hotel-infrastructure/build-runs')).data||infra;exceptions=(await api.request('/internal/v1/hotel-infrastructure/exceptions?limit=100')).data||exceptions}catch(e){notice(e.message,true);return}
    const runs=infra.runs||[],provinceSummary=infra.province_summary||[],latest=runs[0]||{};
    // RC19: do not add historical retry batches into production totals. The previous UI could show
    // 1,342 "generated pages" while only 113 Canonical hotels existed because every retry was summed.
    const totalDiscovered=Number(latest.discovered||0);
    const totalPages=Number(overview.published_pages||0);
    const totalFailures=Number(exceptions.action_required||0);
    const autoRecovering=Number(exceptions.auto_recoverable||0);
    const stateLabel=s=>({QUEUED:'排队中',RUNNING:'自动处理中',COMPLETED:'已完成',NEEDS_ENRICHMENT:'资料待补齐',NEEDS_ATTENTION:'需人工决策'}[s]||s||'—');
    const errorLabel=x=>{
      const code=x.error_code||'';
      if(code==='PROVIDER_TIMEOUT')return '数据源响应较慢，系统自动换源/重试';
      if(code==='PROVIDER_DNS')return '数据源网络解析异常，系统自动重试';
      if(code==='PROVIDER_SCHEMA')return '数据源结构变化，需要技术确认';
      if(x.type==='REGIONAL_BUILD_CONFLICT')return '酒店身份或字段存在冲突，需要确认';
      return x.operator_action_required?'需要人工确认':'系统正在待重试';
    };
    const provider=infra.provider||{configured:false,national_ready:false,harbin_bootstrap_ready:false,production_provider_count:0,bootstrap_provider_count:0};
    const providerBanner=!provider.configured?'<section class="card structured-section warn-card"><div><h3>尚未配置酒店发现数据源</h3><p>暂不能启动建库。请先配置合法/授权的区域发现 Provider。</p></div><details class="tech-diagnostics"><summary>技术信息</summary><div class="mono">REGIONAL_DISCOVERY_PROVIDER_NOT_CONFIGURED</div></details></section>':(!provider.national_ready&&provider.harbin_bootstrap_ready?'<section class="card structured-section"><div><h3>哈尔滨首城发现源已就绪</h3><p>可先运行“黑龙江省 / 哈尔滨市”首城建库。全国模式将在配置正式区域 Provider 后开放。</p></div><span class="status ok">首城可运行</span></section>':'<section class="card structured-section"><div><h3>区域发现数据源已就绪</h3><p>可运行指定区域；正式 Provider 已配置时可启动全国模式。</p></div><span class="status ok">已配置</span></section>');
    const runRows=runs.length?`<div class="table-wrap"><table><thead><tr><th>模式/区域</th><th>城市进度</th><th>本批发现</th><th>Canonical</th><th>已建页</th><th>待重试</th><th>需人工</th><th>状态</th><th></th></tr></thead><tbody>${runs.map(x=>`<tr><td>${esc(x.mode==='NATIONAL_TIERED'?(x.tier_name||'全国分层'):(x.mode==='NATIONAL'?'全国':([x.province,x.city].filter(Boolean).join(' / ')||'指定区域')))}</td><td>${Number(x.cities_finished||0)} / ${Number(x.city_tasks||0)}</td><td>${Number(x.discovered||0)}</td><td>${Number(x.canonical||0)}</td><td>${Number(x.pages||0)}</td><td>${Number(x.auto_recovering||0)}</td><td>${Number(x.failures||0)+Number(x.conflicts||0)}</td><td>${esc(stateLabel(x.state))}</td><td><button class="btn" data-retry-run="${esc(x.run_id)}">重新处理</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="structured-empty"><div><h3>还没有全国建库任务</h3><p>点击“一键全国分层建库”，系统先处理五星级；后续层级按配置与验收结果开放。</p></div></div>';
    const actionable=(exceptions.items||[]).filter(x=>x.severity==='ACTION_REQUIRED');
    const exceptionRows=actionable.slice(0,20).map(x=>`<div class="business-fact"><span>${esc([x.province,x.city,x.name].filter(Boolean).join(' · ')||x.scope||'异常')}</span><b>${esc(errorLabel(x))}${Number(x.occurrences||1)>1?` · ${Number(x.occurrences)}次`:''}</b></div>`).join('')||'<p class="metric-sub">当前没有需要人工处理的异常；请同时检查资料待补齐的酒店；可恢复问题可重新处理。</p>';
    root.innerHTML=`${providerBanner}<div class="productized-admin-head"><div><h2>全国酒店数字基础设施控制台</h2><p>按城市发现酒店、核对身份，再采集官网资料。房型目录、事实与照片逐项通过后发布。</p></div><button class="btn primary" id="nationalBuild" ${provider.national_ready?'':'disabled'}>一键全国分层建库</button></div>
      <div class="grid structured-metrics">${metric('当前批次发现',totalDiscovered)}${metric('Canonical 酒店库',overview.total_hotels||0)}${metric('已发布页面',totalPages)}${metric('资料待补齐',overview.counts?.NEEDS_ENRICHMENT||0)}${metric('需人工处理',totalFailures)}</div>
      <section class="card structured-section"><div><h3>系统自动运行</h3><p>后台处理发现与建档任务。当前有 ${autoRecovering} 项待重试；资料缺失、房型目录待核对及来源冲突会保留在待处理状态。</p></div><span class="status ${totalFailures?'warn':'ok'}">${totalFailures?'有待决策':'查看资料完整性'}</span></section>
      <section class="card"><div class="section-head"><h2>全国建库地图</h2><span>省 → 市 → 区县</span></div><p class="metric-sub">按真实区域批次展示覆盖，不虚构全国酒店数量。点击全国一键建库后，各省会随着城市任务推进自动出现。</p><div class="factory-mini-grid"><span>省任务 <b>${Number(latest.province_tasks||0)}</b></span><span>城市任务 <b>${Number(latest.city_tasks||0)}</b></span><span>已完成城市 <b>${Number(latest.cities_finished||0)}</b></span><span>页面产量 <b>${Number(latest.pages||0)}</b></span></div><div class="province-coverage-grid">${provinceSummary.length?provinceSummary.map(x=>`<div class="province-coverage-card"><strong>${esc(x.province)}</strong><span>已完成城市 ${Number(x.cities_finished||0)}</span><span>发现 ${Number(x.discovered||0)} · Canonical ${Number(x.canonical||0)}</span><span>页面 ${Number(x.pages||0)} · 异常 ${Number(x.conflicts||0)+Number(x.failures||0)}</span></div>`).join(''):'<p class="metric-sub">尚无省级执行证据。启动建库后自动生成。</p>'}</div></section>
      <section class="card business-form-section"><div class="section-head"><h2>指定区域建库</h2><span>省 / 市优先跑</span></div><div class="business-form-grid"><label class="business-field"><span>省 / 自治区 / 直辖市</span><input id="regionProvince" placeholder="例如：黑龙江省" value="${provider.harbin_bootstrap_ready?'黑龙江省':''}"></label><label class="business-field"><span>城市（可选）</span><input id="regionCity" placeholder="例如：哈尔滨市" value="${provider.harbin_bootstrap_ready?'哈尔滨市':''}"></label></div><div class="structured-actions"><button class="btn primary" id="regionBuild">启动指定区域建库</button><span class="metric-sub">运营人员只指定区域，不需要预先填写任何酒店名称或地址。</span></div></section>
      <section class="section"><div class="section-head"><h2>省任务 / 批次进度</h2><span>${runs.length} 个建库批次</span></div>${runRows}</section>
      <section class="card"><div class="section-head"><h2>异常中心摘要</h2><span>${totalFailures} 项需人工 · ${autoRecovering} 项待重试</span></div>${exceptionRows}</section>
      <section class="card"><div class="section-head"><h2>页面产量与酒店档案</h2><span>${Number((overview.items||[]).length)} 家</span></div><div class="toolbar"><input id="factorySearch" placeholder="搜索 Canonical 酒店"><button class="btn factory-stage active" data-stage="ALL">全部</button>${stageTabs(overview.counts||{})}</div><div class="factory-card-grid" id="factoryList">${(overview.items||[]).map(factoryRow).join('')||'<div class="card structured-empty"><div><h3>尚无 Canonical 酒店档案</h3><p>启动全国或指定区域建库后，系统自动发现并建立酒店库。</p></div></div>'}</div></section>
      <section class="card admin-ops-bar"><div><h3>自动化边界</h3><p>自动建库不等于自动 GO Direct；媒体继续受 Rights Gate 控制；内容事实、供给事实与交易路由保持分离。Admin 不再以单店人工录入作为建库主路径。</p></div><div class="structured-actions"><a class="btn" href="#/audit">审计日志</a></div></section>`;
    root.insertAdjacentHTML('afterbegin',scopeEntry());root.querySelector('#catalogScopeOpen').onclick=()=>openScope(ctx);
    const search=root.querySelector('#factorySearch'); let active='ALL';
    const filter=()=>root.querySelectorAll('.factory-hotel-card').forEach(el=>{const stage=el.dataset.factoryStage||'';const q=(search.value||'').trim().toLowerCase();const okStage=active==='ALL'||stage===active;const okQ=!q||(el.dataset.name||'').includes(q);el.style.display=okStage&&okQ?'':'none'});
    search.oninput=filter;root.querySelectorAll('[data-stage]').forEach(b=>b.onclick=()=>{active=b.dataset.stage;root.querySelectorAll('[data-stage]').forEach(x=>x.classList.toggle('active',x===b));filter()});
    root.querySelectorAll('[data-open-hotel]').forEach(b=>b.onclick=()=>openHotel(b.dataset.openHotel,ctx));
    root.querySelector('#nationalBuild').onclick=async()=>{try{const b=root.querySelector('#nationalBuild');b.disabled=true;b.textContent='正在启动…';await api.request('/internal/v1/hotel-infrastructure/build-runs',{method:'POST',body:{mode:'NATIONAL_TIERED',country:'CN'}});notice('全国分层建库已启动；每层完成后按验收结果推进');render(ctx)}catch(e){const msg=e.message.includes('NATIONAL_DISCOVERY_PROVIDER_REQUIRED')?'全国模式尚未配置正式区域发现数据源，请先运行哈尔滨首城建库或配置正式 Provider。':e.message;notice(msg,true);const b=root.querySelector('#nationalBuild');if(b){b.disabled=!provider.national_ready;b.textContent='一键全国分层建库'}}};
    root.querySelector('#regionBuild').onclick=async()=>{const province=root.querySelector('#regionProvince').value.trim(),city=root.querySelector('#regionCity').value.trim();if(!province&&!city){notice('请至少填写省或城市',true);return}try{await api.request('/internal/v1/hotel-infrastructure/build-runs',{method:'POST',body:{mode:'REGION',country:'CN',province:province||null,city:city||null}});notice('指定区域建库已进入队列');render(ctx)}catch(e){const msg=e.message.includes('REGIONAL_DISCOVERY_PROVIDER_NOT_CONFIGURED')?'该区域尚未配置可用的酒店发现数据源。':e.message;notice(msg,true)}};
    root.querySelectorAll('[data-retry-run]').forEach(b=>b.onclick=async()=>{try{await api.request(`/internal/v1/hotel-infrastructure/build-runs/${encodeURIComponent(b.dataset.retryRun)}/retry`,{method:'POST'});notice('已重新进入自动处理队列');render(ctx)}catch(e){notice(e.message,true)}});
  }
  async function openHotel(hotelId,ctx){const {api,root,notice}=ctx;try{const d=(await api.request(`/internal/v1/hotel-autopage/factory/hotels/${encodeURIComponent(hotelId)}`)).data;root.innerHTML=`<div class="structured-actions" style="margin-bottom:14px"><button class="btn" id="factoryBack">← 返回酒店网页工厂</button></div>${detailsHtml(d)}${hotelId===IMPORT_HOTEL?scopeEntry()+importPanel():''}`;bindImport(hotelId,ctx);const scopeButton=root.querySelector('#catalogScopeOpen');if(scopeButton)scopeButton.onclick=()=>openScope(ctx);root.querySelector('#factoryBack').onclick=()=>render(ctx);root.querySelectorAll('[data-factory-action]').forEach(b=>b.onclick=async()=>{try{b.disabled=true;const action=b.dataset.factoryAction;if(action==='compose')await api.request(`/internal/v1/hotel-autopage/hotels/${encodeURIComponent(hotelId)}/compose`,{method:'POST'});if(action==='recollect'){const job=d.factory?.latest_discovery_job_id;if(!job)throw new Error('当前没有可重试的采集任务');await api.request(`/internal/v1/hotel-discovery/jobs/${encodeURIComponent(job)}/retry`,{method:'POST',body:{max_retries:2}})}if(action==='publish'||action==='unpublish')await api.request(`/internal/v1/hotel-autopage/factory/hotels/${encodeURIComponent(hotelId)}/publication`,{method:'POST',body:{action:action==='publish'?'PUBLISH':'UNPUBLISH'}});notice(action==='recollect'?'重新采集完成':action==='compose'?'网页已重新生成':action==='publish'?'网页已发布':'网页已下架');openHotel(hotelId,ctx)}catch(e){notice(e.message,true);b.disabled=false}})}catch(e){notice(e.message,true)}}
  function openCreate(ctx){const {root,api,notice}=ctx;root.innerHTML=`<div class="structured-actions" style="margin-bottom:14px"><button class="btn" id="factoryBack">← 返回酒店网页工厂</button></div><div class="productized-admin-head"><div><h2>采集并建立酒店网页</h2><p>一次只建立一家酒店。至少提供一个可合法访问的公开来源。</p></div><span class="status">单酒店受控采集</span></div><section class="card business-form-section"><div class="business-form-grid"><label class="business-field"><span>酒店名称<b>*</b></span><input id="factoryName" placeholder="例如：哈尔滨某酒店"></label><label class="business-field"><span>酒店地址</span><input id="factoryAddress" placeholder="城市 / 区域 / 详细地址"></label><label class="business-field"><span>酒店官网<b>*</b></span><input id="factoryOfficial" type="url" placeholder="https://..."><small>优先使用酒店或集团官方公开页面。</small></label><label class="business-field"><span>补充公开来源</span><input id="factoryPublic" type="url" placeholder="https://..."><small>仅用于公开商业事实；媒体仍需独立 Rights Gate。</small></label></div><div class="structured-actions"><button class="btn primary" id="factoryRun">开始采集并建立网页</button></div></section><section class="card structured-section"><div><h3>安全与发布边界</h3><p>Discovery 会阻断私网、metadata、非 HTTP(S) 与异常跳转；抓取到的图片候选不会自动公开，酒店也不会因此自动成为 GO Direct。</p></div></section>`;root.querySelector('#factoryBack').onclick=()=>render(ctx);root.querySelector('#factoryRun').onclick=async()=>{const name=root.querySelector('#factoryName').value.trim(),address=root.querySelector('#factoryAddress').value.trim(),official=root.querySelector('#factoryOfficial').value.trim(),pub=root.querySelector('#factoryPublic').value.trim();if(!name||!official){notice('请填写酒店名称和酒店官网',true);return}const hints=[{kind:'OFFICIAL_WEBSITE',url:official}];if(pub)hints.push({kind:'PUBLIC_SOURCE',url:pub});try{const btn=root.querySelector('#factoryRun');btn.disabled=true;btn.textContent='采集中…';const reg=(await api.request('/internal/v1/hotel-discovery/seeds',{method:'POST',body:{name,address,source_hints:hints}})).data;const run=(await api.request(`/internal/v1/hotel-discovery/jobs/${encodeURIComponent(reg.job_id)}/run`,{method:'POST',body:{max_retries:2}})).data;if(run.hotel_id){notice('采集完成，已进入酒店网页生产流程');return openHotel(run.hotel_id,ctx)}notice('采集任务已完成，但尚未形成酒店档案');render(ctx)}catch(e){notice(e.message,true);const btn=root.querySelector('#factoryRun');if(btn){btn.disabled=false;btn.textContent='开始采集并建立网页'}}}}
  window.GO_HOTEL_PAGE_FACTORY={render,reviewedImport:{reviewedPlan,importPreflight,executeImport,verifyImported},reviewedScope:{previewScope,activateScope},anomalyLabel};
})();

