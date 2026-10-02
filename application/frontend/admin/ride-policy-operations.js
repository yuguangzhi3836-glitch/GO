(() => {
 'use strict';
 const base='/internal/v1/ride-policy-operations';
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const unwrap=x=>x?.data??x;
 const money=n=>Number.isSafeInteger(n)?'¥'+(n/100).toFixed(2):'待核验';
 const state={DRAFT:'待另一管理员审核',ACTIVE:'隔离工程使用中',SUPERSEDED:'已被新版本替代',REVOKED:'已撤销'};
 const duration=n=>n%86400===0?n/86400+'天':n%3600===0?n/3600+'小时':n%60===0?n/60+'分钟':n+'秒';
 function summary(p){return `提前${duration(p.cutoff_seconds)}，此前取消费用${money(p.before_fee_minor)}，此后${money(p.after_fee_minor)}；按${p.time_basis==='BOOKED_PICKUP'?'原预订时间':'当前已确认时间'}计算。有效期 ${p.effective_from} 至 ${p.effective_until}`;}
 function difference(previous,next){if(!previous)return '首个版本，尚无旧版可比较。';const names={cutoff_seconds:'取消截止间隔',before_fee_minor:'截止前费用（分）',after_fee_minor:'截止后费用（分）',time_basis:'适用时间基准',effective_from:'生效时间',effective_until:'失效时间'};return Object.entries(names).filter(([k])=>previous[k]!==next[k]).map(([k,n])=>`${n}：${previous[k]} → ${next[k]}`).join('；')||'收费与适用条件不变。';}
 async function render({container,request}){
  if(!container||typeof request!=='function')throw Error('政策工作区参数不完整');
  const generation=(container.__ridePolicyGeneration||0)+1;container.__ridePolicyGeneration=generation;
  let data=null,busy=false,message='';
  const live=()=>container.isConnected!==false&&container.__ridePolicyGeneration===generation;
  function draw(){if(!live())return;
   container.innerHTML=`<section class="card"><h2>用车取消政策运营</h2><p>仅管理隔离工程版本。真实商业政策仍待核验；此处的激活不代表法律或供应商批准。</p><p>新版本与撤销仅影响新预订，已接受订单保留原条款。</p><p role="status">${esc(message)}</p><button data-refresh ${busy?'disabled':''}>刷新诊断</button>${data?.registry_enabled?'':'<p>隔离政策注册未开启或当前环境不允许写入。</p>'}${data&&!data.can_create?'<p>当前角色无提交草稿权限；激活需要另一位有审核权限的管理员。</p>':''}${(data?.offers||[]).map(offer=>{
    const current=offer.versions.find(v=>v.state==='ACTIVE');
    return `<article><h3>${offer.offer_id==='ride_standard'?'舒适用车':'高端用车'}</h3><p>${offer.state==='ISOLATED_READY'?'当前工程版本可用于新预订':'暂停新预订：没有可用且已核验的当前工程版本'}</p>${offer.versions.map(v=>`<div class="card"><h4>${esc(v.policy.version)} · ${esc(state[v.state]||'待核验')}</h4><p>${esc(summary(v.policy))}</p>${v.hold_reason?'<p>此版本需要核对，不能启用。</p>':''}${v.state==='DRAFT'?'<p>'+esc(difference(current?.policy,v.policy))+'</p>':''}${(v.can_activate||v.can_revoke)?`<form data-version="${esc(v.policy_id)}"><label><input type="checkbox" data-confirm>我已核对当前版本、差异及影响</label>${v.can_activate?'<button value="activate">由另一管理员激活工程版本</button>':''}${v.can_revoke?'<button value="revoke">撤销此版本</button>':''}</form>`:''}</div>`).join('')}${data.can_create?`<form data-draft="${offer.offer_id}"><h4>提交新工程版本</h4><label>版本名称 <input name="version" required maxlength="80"></label><label>提前几小时截止 <input name="hours" type="number" min="0" step="1" required></label><label>截止前费用（元） <input name="before" type="number" min="0" step="0.01" required></label><label>截止后费用（元） <input name="after" type="number" min="0" step="0.01" required></label><label>时间基准 <select name="basis"><option value="BOOKED_PICKUP">原预订时间</option><option value="CURRENT_CONFIRMED_PICKUP">当前确认时间</option></select></label><label>生效时间（本地） <input name="from" type="datetime-local" required></label><label>失效时间（本地） <input name="until" type="datetime-local" required></label><label><input type="checkbox" name="consent" required>仅提交隔离工程草稿，等待另一管理员审核</label><button>提交草稿</button></form>`:''}</article>`;}).join('')}</section>`;
   container.querySelector('[data-refresh]').onclick=load;
   container.querySelectorAll('[data-version]').forEach(form=>{form.onsubmit=async event=>{event.preventDefault();if(busy||!form.querySelector('[data-confirm]').checked)return;const row=data.offers.flatMap(o=>o.versions).find(v=>v.policy_id===form.dataset.version);const action=event.submitter?.value;if(!row||!['activate','revoke'].includes(action)||!row['can_'+action])return;await send(base+'/'+encodeURIComponent(row.policy_id)+'/'+action,{revision:row.revision});};});
   container.querySelectorAll('[data-draft]').forEach(form=>{form.onsubmit=async event=>{event.preventDefault();if(busy||!data.can_create||!form.elements.consent.checked)return;try{const f=form.elements;const policy={offer_id:form.dataset.draft,version:f.version.value.trim(),currency:'CNY',data_mode:'ISOLATED_SYNTHETIC',source_reference:'isolated://admin-engineering-registry',effective_from:new Date(f.from.value).toISOString(),effective_until:new Date(f.until.value).toISOString(),cutoff_seconds:Number(f.hours.value)*3600,before_fee_minor:Math.round(Number(f.before.value)*100),after_fee_minor:Math.round(Number(f.after.value)*100),time_basis:f.basis.value};await send(base+'/drafts',{policy});}catch(error){message=error.message;draw();}};});
  }
  async function load(){if(busy||!live())return;busy=true;draw();try{const next=unwrap(await request(base));if(live()){data=next;message='已读取当前权威版本与诊断。';}}catch(error){if(live()){data=null;message='读取失败：'+error.message;}}finally{busy=false;draw();}}
  async function send(url,body){if(busy||!live())return;busy=true;draw();try{await request(url,{method:'POST',body});if(live())message='操作已记录。';}catch(error){if(live())message='操作未确认，请刷新核对后再操作：'+error.message;}finally{busy=false;if(live()){const saved=message;await load();message=saved;draw();}}}
  await load();
 }
 window.GORidePolicyOperations={render,summary,difference};
})();
