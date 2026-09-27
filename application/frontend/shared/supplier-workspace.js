// Tenant-scoped partner workspaces. Never infer permissions from a visible tile.
export const VERTICALS={HOTEL:'酒店',FLIGHT:'机票',RAIL:'火车票',RIDE:'接送用车',RENTAL:'租车',ATTRACTION:'景点门票'};
const BENEFITS={UPGRADE_PRIORITY:'升房优先',BREAKFAST:'早餐',LATE_CHECKOUT:'延迟退房'};
const PROGRAMS={STAFF_RATE:'GO Staff 员工价',OWNER_RATE:'GO Owner 业主价',OWNER_BENEFITS:'GO Owner 业主礼遇',FRIENDS_FAMILY:'Friends & Family 亲友权益'};
function guard(ctx){
 const route=location.hash,token=Symbol('partner-read'),node=ctx.root;
 node.partnerRead=token;
 return ()=>node.isConnected&&location.hash===route&&node.partnerRead===token;
}
function pager(data,offset){return `<div class="actionbar"><button class="btn" data-prev ${offset?'':'disabled'}>上一页</button><span>第 ${Math.floor(offset/20)+1} 页</span><button class="btn" data-next ${data.has_more?'':'disabled'}>下一页</button></div>`}
export async function renderRecords(ctx,{refunds=false,vertical='',offset=0}={}){
 const {root,request,esc,table,openOrder}=ctx,current=guard(ctx);
 const title=refunds?'取消与退款':(vertical?VERTICALS[vertical]+'工作台':'全部品类订单');
 root.innerHTML=`<section class="card"><h2>${esc(title)}</h2><p role="status">正在读取…</p></section>`;
 const query=new URLSearchParams({limit:'20',offset:String(offset)});if(vertical)query.set('vertical',vertical);
 try{
  const d=await request((refunds?'/v1/supplier/refunds':'/v1/supplier/transaction-orders')+'?'+query);
  if(!current())return;
  const rows=d.items||[];
  root.innerHTML=`<section class="card"><h2>${esc(title)}</h2><label class="business-field"><span>业务品类</span><select data-vertical-filter><option value="">全部品类</option>${Object.entries(VERTICALS).map(([key,label])=>`<option value="${key}" ${key===vertical?'selected':''}>${label}</option>`).join('')}</select></label><p>${refunds?'查看取消申请及实际退款进度，点击记录核对订单。':'查看当前主体的订单、履约与售后。点击订单进入处理。'}</p><div class="actionbar"><a class="btn" href="#/business-management">全部业务</a><a class="btn" href="#/refunds">取消与退款</a><a class="btn" href="#/vertical-capabilities">供给接入状态</a></div><div data-records>${rows.length?table(rows,true):`<p role="status">当前没有${esc(vertical?VERTICALS[vertical]:'')}${refunds?'取消或退款记录':'订单'}。</p>`}</div>${pager(d,offset)}</section>`;
  root.querySelector('[data-vertical-filter]').onchange=e=>renderRecords(ctx,{refunds,vertical:e.target.value});
  root.querySelector('[data-prev]').onclick=()=>renderRecords(ctx,{refunds,vertical,offset:Math.max(0,offset-20)});
  root.querySelector('[data-next]').onclick=()=>renderRecords(ctx,{refunds,vertical,offset:offset+20});
  root.querySelectorAll('tr[data-i]').forEach(tr=>tr.onclick=()=>{const row=rows[Number(tr.dataset.i)];openOrder(row.vertical||'HOTEL',row.order_id)});
 }catch(e){if(current()){root.innerHTML=`<section class="card"><h2>${esc(title)}</h2><p role="alert">读取未完成，请重试。${esc(e.status===403?'当前账号没有查看权限。':'')}</p><button class="btn" data-retry>重新加载</button></section>`;root.querySelector('[data-retry]').onclick=()=>renderRecords(ctx,{refunds,vertical,offset})}}
}
export async function renderIdentity(ctx){
 const {root,request,esc}=ctx,current=guard(ctx);
 root.innerHTML='<section class="card"><h2>员工优价 / 业主权益</h2><p role="status">正在读取项目和房型…</p></section>';
 const d=await request('/v1/supplier/go-identity/configuration');if(!current())return;
 const rooms=d.rooms||[],programs=d.programs||[],writable=ctx.permissions.includes('supplier:fare-rules');
 root.innerHTML=`<form class="card" data-program-form><h2>员工优价 / 业主权益</h2><p>可同时启用多个项目；每个项目可选择多个适用房型。不同身份价格按现有规则核算，不叠加折扣。</p>${Object.entries(PROGRAMS).map(([type,label])=>{
  const saved=programs.find(p=>p.program_type===type),ids=saved?.eligible_room_ids_json||[],benefits=saved?.benefits_json||[];
  const choices={...BENEFITS,...Object.fromEntries(benefits.filter(b=>!BENEFITS[b]).map(b=>[b,b]))};
  return `<fieldset class="partner-program" data-program="${type}"><legend><label><input type="checkbox" data-enabled ${saved?.enabled?'checked':''} ${writable?'':'disabled'}> ${label}</label></legend><div data-room-options ${saved?.enabled?'':'hidden'}><p>适用房型（可多选）</p>${rooms.length?rooms.map(r=>`<label class="partner-room"><input type="checkbox" value="${esc(r.room_type_id)}" data-room ${saved?.enabled&&(!ids.length||ids.includes(r.room_type_id))?'checked':''} ${writable?'':'disabled'}><span>${esc(r.name)}<small>${esc(r.property_name)}</small></span></label>`).join(''):'<p>暂无可选房型，请先在房型管理中添加。</p>'}${type==='OWNER_BENEFITS'?`<p>业主礼遇内容（可多选）</p>${Object.entries(choices).map(([key,name])=>`<label class="partner-room"><input type="checkbox" data-benefit value="${esc(key)}" ${benefits.includes(key)?'checked':''} ${writable?'':'disabled'}><span>${esc(name)}</span></label>`).join('')}`:''}</div></fieldset>`;
 }).join('')}<p data-save-message role="status" aria-live="polite"></p><button class="btn primary" type="submit" ${writable?'':'disabled'}>保存项目与房型</button>${writable?'':'<p>当前账号仅可查看，请由收益管理人员或管理员配置。</p>'}<a class="btn" href="#/rooms">管理房型</a></form>`;
 const form=root.querySelector('form'),button=form.querySelector('[type=submit]'),message=form.querySelector('[data-save-message]');let busy=false;
 form.querySelectorAll('[data-enabled]').forEach(b=>b.onchange=()=>b.closest('fieldset').querySelector('[data-room-options]').hidden=!b.checked);
 form.onsubmit=async e=>{
  e.preventDefault();if(busy||!current()||!writable)return;
  const selections=[...form.querySelectorAll('[data-program]')].map(f=>({program_type:f.dataset.program,enabled:f.querySelector('[data-enabled]').checked,eligible_room_ids:[...f.querySelectorAll('[data-room]:checked')].map(x=>x.value),...(f.dataset.program==='OWNER_BENEFITS'?{benefits:[...f.querySelectorAll('[data-benefit]:checked')].map(x=>x.value)}:{})}));
  const empty=selections.find(p=>p.enabled&&!p.eligible_room_ids.length);
  if(empty){message.textContent='请为'+PROGRAMS[empty.program_type]+'选择至少一个房型。';return}
  if(selections.some(p=>p.program_type==='OWNER_BENEFITS'&&p.enabled&&!p.benefits.length)){message.textContent='请选择至少一项业主礼遇内容。';return}
  busy=true;form.querySelectorAll('input').forEach(input=>input.disabled=true);button.disabled=true;button.textContent='正在保存…';message.textContent='';
  try{const saved=await request('/v1/supplier/go-identity/configuration',{method:'PUT',body:{programs:selections,revision:d.revision}});if(!current())return;d.revision=saved.revision;message.textContent='项目与房型已保存。'}
  catch(error){if(current())message.textContent=error.message==='PROGRAM_CONFIGURATION_CHANGED'?'配置已被其他人员更新，请重新进入核对后保存。':'保存未完成，请重新核对房型或重试。'}
  finally{busy=false;if(current()){form.querySelectorAll('input').forEach(input=>input.disabled=false);button.disabled=false;button.textContent='保存项目与房型'}}
 };
}
export async function renderCapabilities(ctx){
 const {root,request,esc}=ctx,current=guard(ctx);root.innerHTML='<p role="status">正在读取业务接入状态…</p>';
 const d=await request('/v1/supplier/verticals');if(!current())return;
 const capabilityNames={SEARCH:'查询',DETAIL:'详情',QUOTE:'报价',REVALIDATE:'复核',ORDER:'下单',CANCEL:'取消',REFUND:'退款',RECONCILIATION:'对账'};
 root.innerHTML=`<section class="card"><h2>业务接入状态</h2><p>各业务的订单与售后入口独立展示；外部供给是否可用以已核验的连接状态为准。</p></section><div class="grid">${Object.entries(VERTICALS).map(([key,label])=>{
  const caps=(d.capabilities||[]).filter(c=>c.vertical===key);
  return `<section class="card"><h3>${label}</h3><p>${caps.length?'已配置能力：'+caps.map(c=>esc(capabilityNames[c.capability]||'其他能力')).join('、'):'尚未配置供给连接。'}</p><p>${d.external_live?'外部连接状态须逐项核验':'尚未开放真实外部交易'}</p><a class="btn" href="#/business-${key.toLowerCase()}">进入${label}工作台</a><a class="btn" href="#/connectors">查看供给连接</a></section>`;
 }).join('')}</div>`;
}
