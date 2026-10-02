/* Owner-controlled revisions, import review and permission management. */
(() => {
  const base = '/v1/consumer/profile';
  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {LEGAL_NAME:'证件姓名',DATE_OF_BIRTH:'出生日期',NATIONALITY:'国籍（地区）',MOBILE:'联系电话',EMAIL:'邮箱',PASSPORT_NUMBER:'护照号',ID_CARD_NUMBER:'身份证号',DRIVER_LICENSE_NUMBER:'驾驶证号',ADDRESS:'地址',VISA_NUMBER:'签证号'};
  const permissions = {USE_FOR_BOOKING:'用于旅行预订',EDIT:'修改旅行资料',SENSITIVE_DATA:'使用敏感资料',SHARE:'导出分享资料'};
  const errors = {PROFILE_CHANGED_RELOAD_REQUIRED:'资料已更新，请关闭窗口并刷新后重新核对。',TRAVELER_EDIT_PERMISSION_REQUIRED:'这位旅行者尚未允许修改资料，请先核对授权。',TRAVELER_SENSITIVE_PERMISSION_REQUIRED:'这位旅行者的敏感资料授权尚未开启。',PROFILE_SOURCE_DISCONNECTED:'此来源已停止导入，请先在来源管理中确认是否恢复。',PROFILE_BIRTH_DATE_INVALID:'请填写有效的出生日期。',PROFILE_NATIONALITY_INVALID:'国籍（地区）请填写三位字母代码，例如 CHN。',PROFILE_VALUE_INVALID:'资料格式不正确，请重新核对。',PROFILE_VALIDITY_RANGE_INVALID:'有效期不正确，请核对起止日期。',PROFILE_IMPORT_ITEM_FINALIZED:'这项导入已完成，请刷新后在旅行者资料中修改。'};
  const confirmation = text => `<label class="go-consent"><input type="checkbox" data-confirm required><span>${escape(text)}</span></label>`;
  const checked = d => {if(!d.querySelector('[data-confirm]').checked)throw Error('请先勾选确认。')};
  const send = async (path, method, body) => {
    try {return await api(base + path,{method,body:JSON.stringify(body)})}
    catch(e){throw Error(errors[e.message] || e.message)}
  };
  const run = fn => Promise.resolve().then(fn).catch(e=>toast(errors[e.message]||e.message));
  const fieldLabel = f => labels[f] || '其他旅行资料';
  const sourceName = s => ({USER:'本人填写',MANUAL:'本人填写',GO_ACCOUNT_REGISTRATION:'GO 账号',USER_DATA_PACKAGE:'用户资料包',OFFICIAL_API:'官方接口',TEXT_IMPORT:'文本导入',FILE_IMPORT:'文件导入'}[s.source_provider||s.source_type] || s.source_provider || '导入资料');
  const can = (t,p) => t.permissions?.[p] ?? (t.relationship_type==='SELF');
  const {dialog} = window.GOBooking;

  async function editTraveler(t) {
    const result=await dialog('修改旅行者资料',`<p>姓名须与出行证件一致。修改后需在下一次预订时重新核对。</p>
      <div class="field"><label for="vmName">证件姓名</label><input id="vmName" value="${escape(t.full_name)}" required maxlength="160" autocomplete="name"></div>
      <div class="field"><label for="vmNationality">国籍（地区）代码</label><input id="vmNationality" value="${escape(t.nationality)}" placeholder="例如 CHN" maxlength="3" autocomplete="off"></div>
      <div class="field"><label for="vmBirth">新出生日期（留空保留原值）</label><input id="vmBirth" type="date" autocomplete="off"></div>
      ${confirmation('已核对修改内容，并有权为这位旅行者更新资料。')}`,'保存修改',d=>{
        checked(d);const body={confirmed:true,expected_revision:t.revision,full_name:d.querySelector('#vmName').value.trim(),nationality:d.querySelector('#vmNationality').value.trim().toUpperCase()||null};
        if(d.querySelector('#vmBirth').value)body.date_of_birth=d.querySelector('#vmBirth').value;
        return send(`/travelers/${t.traveler_id}`,'PATCH',body);
      });
    if(result)await showAccount();
  }

  async function editFact(f) {
    const structured=['COMPANY_INVOICE','PERSONAL_INVOICE','EMERGENCY_CONTACT_DETAIL','ADDRESS'].includes(f.field_type);
    const result=await dialog(`修改${fieldLabel(f.field_type)}`,`<p>当前：${escape(f.value_masked)}。新值需重新核对；原有官方认证不会自动沿用。</p>
      <div class="field"><label for="vmValue">新资料${structured?'（文本或 JSON）':''}</label><input id="vmValue" autocomplete="off" type="${f.field_type==='DATE_OF_BIRTH'?'date':'text'}" required></div>
      <div class="field"><label for="vmExpiry">有效期至（留空保留原值）</label><input id="vmExpiry" type="date"></div>
      ${confirmation('我已核对新资料，并确认保存。')}`,'确认修改',d=>{
        checked(d);let value=d.querySelector('#vmValue').value.trim();
        if(structured && /^[\[{]/.test(value)){try{value=JSON.parse(value)}catch{throw Error('JSON 格式不正确，请重新核对。')}}
        const body={value,confirmed:true,expected_revision:f.revision};
        if(d.querySelector('#vmExpiry').value)body.valid_until=d.querySelector('#vmExpiry').value;
        return send(`/facts/${f.fact_id}`,'PATCH',body);
      });
    if(result)await showAccount();
  }

  async function addFact(t) {
    const result=await dialog('补充旅行资料',`<p>旅行者：${escape(t.full_name)}。只填写需要保存的资料。</p><div class="field"><label for="vmField">资料类型</label><select id="vmField">${Object.entries(labels).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></div><div class="field"><label for="vmNewValue">资料内容</label><input id="vmNewValue" required autocomplete="off"><small>出生日期使用 YYYY-MM-DD；国籍（地区）使用三位字母代码。</small></div>${confirmation('我已核对资料内容与旅行者归属，并有权保存。')}`,'确认保存',async d=>{
      checked(d);const field_type=d.querySelector('#vmField').value,value=d.querySelector('#vmNewValue').value.trim();
      if(!labels[field_type]||!value)throw Error('请选择资料类型并填写内容。');
      const job=await send('/imports','POST',{source_type:'MANUAL',source_provider:'USER',source_reference:'GO_PROFILE_EDITOR',items:[{entity_type:'TRAVELER',traveler_ref:'selected',value:{existing_traveler_id:t.traveler_id},confidence_bps:10000},{traveler_ref:'selected',field_type,value,confidence_bps:10000}]});
      for(const item of job.items)if(['NEEDS_REVIEW','EXTRACTED'].includes(item.status))await send(`/imports/${job.import_job_id}/items/${item.import_item_id}/review`,'POST',{action:'ACCEPT'});
      return send(`/imports/${job.import_job_id}/commit`,'POST',{});
    });
    if(result){if(result.status==='COMMITTED')await showAccount();else await showImport(result.import_job_id)}
  }

  async function permissionDialog(t,p) {
    const allowed=can(t,p);
    const result=await dialog(`${allowed?'关闭':'开启'}${permissions[p]}`,`<p>旅行者：${escape(t.full_name)}</p><p>${p==='SENSITIVE_DATA'?'敏感资料还需在每次预订时按用途确认。':p==='SHARE'?'开启后，资料可以随本人发起的导出操作下载。':p==='USE_FOR_BOOKING'?'关闭后，此旅行者不能用于新的预订；已有订单需在订单页管理。':'此权限控制现有资料的修改及后续导入。'}</p>${confirmation(`我确认${allowed?'撤回':'具有并授予'}这项权限。`)}`,allowed?'确认关闭':'确认开启',d=>{
      checked(d);return send(`/travelers/${t.traveler_id}/permissions/${p}`,'PUT',{allowed:!allowed});
    });
    if(result)await showAccount();
  }

  async function reviewItem(job,item) {
    const value=await dialog('查看并核对导入内容',`<p>${fieldLabel(item.field_type)}：${escape(item.preview_masked)}</p><p>下一步将在此设备显示原始资料，供你核对。请确认周围环境适合查看个人信息。</p>${confirmation('确认查看这项资料用于本次导入核对。')}`,'查看资料',d=>{
      checked(d);return send(`/imports/${job.import_job_id}/items/${item.import_item_id}/inspect`,'POST',{confirmed:true});
    });
    if(!value)return;
    const format=v=>escape(typeof v==='object'?JSON.stringify(v,null,2):v);
    const choices=item.conflict_fact_id?[['USE_EXISTING','保留已有资料'],['REPLACE_EXISTING','采用此次导入资料'],['REJECT','不导入此项']]:[['ACCEPT','确认导入此项'],['REJECT','不导入此项']];
    const reviewed=await dialog('核对后选择',`<p>此次导入</p><pre class="vault-value">${format(value.value)}</pre>${item.conflict_fact_id?`<p>已有资料</p><pre class="vault-value">${value.existing_value==null?'资料已变化，请刷新后重新核对。':format(value.existing_value)}</pre>`:''}<div class="field"><label for="vmDecision">处理方式</label><select id="vmDecision" required><option value="">请选择</option>${choices.map(([v,t])=>`<option value="${v}">${t}</option>`).join('')}</select></div>${confirmation('我已核对资料内容及归属，确认以上处理。')}`,'保存选择',d=>{
      checked(d);const action=d.querySelector('#vmDecision').value;if(!choices.some(x=>x[0]===action))throw Error('请选择处理方式。');
      return send(`/imports/${job.import_job_id}/items/${item.import_item_id}/review`,'POST',{action});
    });
    if(reviewed)await showImport(job.import_job_id);
  }

  async function assignTraveler(job,item,travelers) {
    const result=await dialog('确认资料归属',`<p>选择这项${fieldLabel(item.field_type)}实际属于的旅行者。选择后仍需核对内容。</p><div class="field"><label for="vmOwner">旅行者</label><select id="vmOwner" required><option value="">请选择</option>${travelers.filter(t=>can(t,'EDIT')).map(t=>`<option value="${escape(t.traveler_id)}">${escape(t.full_name)}</option>`).join('')}</select></div>${confirmation('我确认这项资料属于所选旅行者。')}`,'确认归属',d=>{
      checked(d);const traveler_id=d.querySelector('#vmOwner').value;if(!traveler_id)throw Error('请选择旅行者。');
      return send(`/imports/${job.import_job_id}/items/${item.import_item_id}/traveler`,'POST',{traveler_id,confirmed:true,expected_revision:item.revision});
    });
    if(result)await showImport(job.import_job_id);
  }

  async function showImport(id) {
    const [job,vault]=await Promise.all([api(base+`/imports/${id}`),api(base+'/vault')]);
    const status={COMMITTED:'已保存',REJECTED:'不导入',CONFLICT:'需要处理冲突',ACCEPTED:'已核对，待保存',NEEDS_REVIEW:'待核对',EXTRACTED:'待核对'};
    $('#app').innerHTML=shell(`<button class="btn ghost" id="vmBack">返回旅行资料</button><h1 class="screen-title">核对导入资料</h1><p class="sub">${escape(sourceName(job))} · 逐项确认归属与内容，再保存到个人库。</p>${job.items.map(i=>`<section class="card"><h2>${i.entity_type==='TRAVELER'?'旅行者':fieldLabel(i.field_type)}</h2><p class="vault-value">${escape(i.preview_masked)}</p><p>${status[i.status]||'待核对'}${i.resolution_traveler_id?' · '+escape(vault.travelers.find(t=>t.traveler_id===i.resolution_traveler_id)?.full_name||'原旅行者已移除'):''}</p>${i.status!=='COMMITTED'&&job.status!=='COMMITTED'?`<div class="vault-actions"><button class="btn primary" data-review="${escape(i.import_item_id)}">查看并核对</button>${i.entity_type==='PROFILE_FACT'?`<button class="btn ghost" data-assign="${escape(i.import_item_id)}">确认归属</button>`:''}</div>`:''}</section>`).join('')}${job.status!=='COMMITTED'?'<button class="btn primary" id="vmCommit">保存已核对的资料</button>':'<p>本次导入已完成。资料可在旅行者名下继续管理。</p>'}`,'profile');bindNav();$('#vmBack').onclick=()=>run(showAccount);
    document.querySelectorAll('[data-review]').forEach(b=>b.onclick=()=>run(()=>reviewItem(job,job.items.find(i=>i.import_item_id===b.dataset.review))));
    document.querySelectorAll('[data-assign]').forEach(b=>b.onclick=()=>run(()=>assignTraveler(job,job.items.find(i=>i.import_item_id===b.dataset.assign),vault.travelers)));
    if($('#vmCommit'))$('#vmCommit').onclick=()=>run(async()=>{
      const result=await dialog('保存已核对的资料','<p>未核对的敏感资料、归属不明的资料及未解决的冲突会继续等待处理。</p>','确认保存',()=>send(`/imports/${id}/commit`,'POST',{}));
      if(result){toast(result.status==='COMMITTED'?'本次资料已保存':'仍有资料需要核对，请继续处理。');await showImport(id)}
    });
  }

  async function sourceAction(source,remove=false) {
    const enabled=source.status==='DISCONNECTED';
    const result=await dialog(remove?'删除此来源资料':enabled?'恢复此来源导入':'停止此来源导入',`<p>${escape(sourceName(source))}</p><p>${remove?'将删除此来源保存的资料及导入副本，并停止继续导入。已独立修改的资料保留。':enabled?'允许继续处理此来源的导入，已有待核对资料仍需逐项确认。':'停止此来源继续导入；已经保存的资料仍可查看、编辑或删除。'}</p><p class="sub">此操作管理 GO 内的导入来源；不代表连接或断开第三方平台账号。</p>${confirmation('我确认以上处理。')}`,remove?'确认删除':enabled?'确认恢复':'确认停止',d=>{
      checked(d);return send(`/sources/${encodeURIComponent(source.source_fingerprint)}${remove?'':'/connection'}`,remove?'DELETE':'POST',remove?undefined:{allowed:enabled});
    });
    if(result)await showAccount();
  }

  async function remove(title,path) {
    if(await dialog(title,`<p>删除后，相关资料及其修订历史将从可复用的个人库中移除；历史订单需在订单页管理。</p>${confirmation('我确认删除。')}`,'确认删除',d=>{checked(d);return send(path,'DELETE')}))await showAccount();
  }

  async function exportVault() {
    const data=await dialog('导出我的旅行资料',`<p>文件含有个人信息。仅导出允许分享的旅行者和字段，请妥善保存。</p>${confirmation('确认将资料下载到此设备。')}`,'确认导出',d=>{checked(d);return send('/export','POST',{confirmed:true})});
    if(!data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='GO_Personal_Travel_Vault.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  showAccount=async()=>{
    try {
      if(!state.me){showAuth();return}setVerticalVIMode(false);
      const [vault,consents,jobs,sources]=await Promise.all(['/vault','/consents','/imports','/sources'].map(p=>api(base+p)));
      const pending=jobs.items.filter(j=>j.status!=='COMMITTED');
      $('#app').innerHTML=shell(`<h1 class="screen-title">我的旅行资料</h1><p class="sub">资料由你掌握。出发时选择旅行者，按本次用途确认使用。</p>
        <div class="vault-actions"><button class="btn primary" id="vmAdd">添加旅行者</button><button class="btn ghost" id="vmExport">导出我的资料</button></div>
        ${pending.length?`<section class="card"><h2>有 ${pending.length} 份导入待核对</h2><p>尚未确认的资料不会自动替换现有内容。</p>${pending.map(j=>`<div class="vault-fact"><span>${escape(sourceName(j))} · ${j.item_count} 项${j.source_disconnected?' · 已停止导入':''}</span><button class="btn ghost" data-job="${escape(j.import_job_id)}">继续核对</button></div>`).join('')}</section>`:''}
        ${vault.travelers.map(t=>`<section class="card"><div class="vault-heading"><div><h2>${escape(t.full_name)}</h2><p>${t.relationship_type==='SELF'?'本人':'同行人'} · ${t.booking_permission?'可用于预订':'预订授权已关闭'}</p></div><button class="btn ghost" data-edit-person="${escape(t.traveler_id)}">修改资料</button></div>
          ${t.facts.map(f=>`<div class="vault-fact"><div><b>${fieldLabel(f.field_type)}</b><p>${escape(f.value_masked)}</p><small>${escape(sourceName(f))} · ${f.user_confirmed?'已由用户核对':'待核对'}${f.valid_until?' · 有效至 '+escape(f.valid_until):''}</small></div><div class="vault-actions"><button class="btn ghost" data-edit-fact="${escape(f.fact_id)}">修改</button><button class="btn ghost" data-delete-fact="${escape(f.fact_id)}">删除</button></div></div>`).join('')}
          <details class="vault-permissions"><summary>管理资料权限</summary>${Object.entries(permissions).map(([p,l])=>`<div class="vault-fact"><span>${l} · ${can(t,p)?'已开启':'已关闭'}</span><button class="btn ghost" data-permission="${p}" data-person="${escape(t.traveler_id)}">${can(t,p)?'关闭':'开启'}</button></div>`).join('')}</details>
          <div class="vault-actions"><button class="btn ghost" data-add-fact="${escape(t.traveler_id)}">补充资料</button><button class="btn ghost" data-delete-person="${escape(t.traveler_id)}">删除旅行者</button></div></section>`).join('')||'<section class="card"><h2>让下次出发更轻松</h2><p>先添加证件姓名，再按出行需要补充资料。账号昵称不会自动作为出行人。</p></section>'}
        <section class="card"><h2>本次用途授权</h2>${consents.items.filter(c=>c.status==='ACTIVE'&&(!c.expires_at||Date.parse(c.expires_at)>Date.now())).map(c=>`<div class="vault-fact"><div>${escape(vault.travelers.find(t=>t.traveler_id===c.traveler_id)?.full_name||'已授权旅行者')}<small>${c.scope.map(fieldLabel).join('、')}</small></div><button class="btn ghost" data-revoke="${escape(c.consent_id)}">撤回授权</button></div>`).join('')||'<p>暂无有效授权。</p>'}</section>
        <section class="card"><h2>导入来源</h2><p>管理已提交的导入来源与资料副本。</p>${sources.items.map((s,index)=>`<div class="vault-fact"><div>${escape(sourceName(s))}<small>${s.active_facts} 项资料 · ${s.status==='DISCONNECTED'?'已停止导入':'允许继续导入'}</small></div><div class="vault-actions"><button class="btn ghost" data-source="${index}">${s.status==='DISCONNECTED'?'恢复导入':'停止导入'}</button><button class="btn ghost" data-remove-source="${index}">删除资料</button></div></div>`).join('')||'<p>还没有导入来源。</p>'}</section><a class="btn ghost" href="/console-assets/privacy.html?audience=consumer">隐私与数据权利</a><button class="btn ghost" id="vmLogout">退出登录</button>`,'profile');bindNav();
      const person=id=>vault.travelers.find(t=>t.traveler_id===id),fact=id=>vault.travelers.flatMap(t=>t.facts).find(f=>f.fact_id===id);
      const bind=(selector,fn)=>document.querySelectorAll(selector).forEach(b=>b.onclick=()=>run(()=>fn(b)));
      $('#vmAdd').onclick=()=>run(()=>window.GOBooking.addTraveler());$('#vmExport').onclick=()=>run(exportVault);
      bind('[data-edit-person]',b=>editTraveler(person(b.dataset.editPerson)));bind('[data-edit-fact]',b=>editFact(fact(b.dataset.editFact)));
      bind('[data-add-fact]',b=>addFact(person(b.dataset.addFact)));bind('[data-job]',b=>showImport(b.dataset.job));
      bind('[data-permission]',b=>permissionDialog(person(b.dataset.person),b.dataset.permission));
      bind('[data-delete-fact]',b=>remove('删除这项资料',`/facts/${b.dataset.deleteFact}`));bind('[data-delete-person]',b=>remove('删除旅行者',`/travelers/${b.dataset.deletePerson}`));
      bind('[data-source]',b=>sourceAction(sources.items[Number(b.dataset.source)]));bind('[data-remove-source]',b=>sourceAction(sources.items[Number(b.dataset.removeSource)],true));
      bind('[data-revoke]',async b=>{await send(`/consents/${b.dataset.revoke}`,'DELETE');await showAccount()});
      $('#vmLogout').onclick=()=>run(async()=>{await api('/v1/consumer/auth/logout',{method:'POST'});state.me=null;showHome()});
    }catch(e){toast(errors[e.message]||e.message)}
  };
  window.GOVault={editTraveler,editFact,addFact,permissionDialog,reviewItem,assignTraveler,showImport,sourceAction};
})();
