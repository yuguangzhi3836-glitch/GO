(() => {
 'use strict';
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 async function mount(root,api,vertical,id,admin){
  const endpoint=(admin?'/internal/v1/admin':'/v1/supplier')+'/ticket-operations/'+encodeURIComponent(vertical)+'/'+encodeURIComponent(id);
  const identity=await api.me(),userId=(identity.data||identity).user_id;
  if(!userId)throw Error('无法核对当前账号');
  let busy=false,revision=0,command=null;const route=location.hash;
  const active=()=>root.isConnected&&location.hash===route;
  const request=async(method,body)=>{if(!active())throw Error('订单页面已切换');const r=await api.request(endpoint,{method,body,headers:{'X-GO-User':userId}});if(!active())throw Error('订单页面已切换');return r.data||r;};
  async function load(){
   const d=await request('GET');revision=d.workflow.revision;
   root.innerHTML=`<h2>票务处理工作台</h2><p>订单 ${esc(id)} · ${esc(d.order.status)} · 工作流 ${esc(d.workflow.stage)}</p>
    ${Number.isSafeInteger(d.order.refunded_amount_minor)?`<p>累计实付 ${esc(d.order.currency)} ${(d.order.total_amount_minor/100).toFixed(2)} · 累计已退 ${(d.order.refunded_amount_minor/100).toFixed(2)} · 净实付 ${((d.order.total_amount_minor-d.order.refunded_amount_minor)/100).toFixed(2)}</p>`:''}
    <p>当前处理人 ${esc(d.workflow.assignee||'待领取')}</p>
    ${(d.order.coupons||[]).map(c=>`<p>${esc(c.passenger_name)} · 第 ${c.leg_index+1} 程 · ${esc(c.leg.departure_date)} · ${esc(c.state)} · 票号 ${esc(c.ticket_number)}</p>`).join('')}
    ${(d.order.change_quotes||[]).filter(q=>['AUTHORIZATION_PENDING','PENDING_SUPPLIER'].includes(q.status)).map(q=>`<p>待处理改签 ${esc(q.quote_id)}：${esc(JSON.stringify(q.changes))}</p>`).join('')}
    <form data-ticket-form data-ticket-revision="${revision}"><label>操作<select name="action"><option value="REGISTER">登记问题</option><option value="CLAIM">领取 / 管理员接管</option><option value="RECEIPT">提交供应商处理回执</option>${d.can_apply?'<option value="APPLY">按已登记回执处理订单</option><option value="VERIFY">独立复核处理结果</option><option value="FOLLOW_UP">记录跟进并关闭</option>':''}</select></label>
    <label>处理说明<input name="note" required maxlength="1000"></label>
    <fieldset><legend>提交回执时填写</legend><label>回执结果<select name="state"><option value="TICKETED">出票 / 改签成功</option><option value="FAILED">处理失败</option><option value="UNKNOWN_EXTERNAL_STATE">结果待核实</option></select></label>
    <label>回执证据编号<input name="evidence_reference" maxlength="256"></label><label>供应商预订编号<input name="supplier_reference" maxlength="64"></label>
    <label>票号（每行一个，与所选票券顺序一致）<textarea name="ticket_numbers"></textarea></label><label>改签报价编号（改签回执必填）<input name="quote_id" maxlength="64"></label></fieldset>
    <button class="btn primary" type="submit" ${d.can_operate?'':'disabled'}>提交处理</button><button class="btn" type="button" data-ticket-reload>刷新状态</button></form>
    <p role="status" data-ticket-message></p><h3>处理与复核记录</h3>${d.events.map(e=>`<p>${esc(e.action)} · ${esc(e.actor_id)} · ${esc(e.note)}</p>`).join('')||'<p>尚无处理记录</p>'}`;
   root.querySelector('[data-ticket-reload]').onclick=()=>load().catch(show);
   root.querySelector('form').onsubmit=async e=>{
    e.preventDefault();if(busy)return;busy=true;const form=e.currentTarget,button=form.querySelector('[type=submit]');button.disabled=true;
    try{
     const f=new FormData(form),action=f.get('action');
     const payload={expected_revision:revision,action,note:f.get('note')};
     if(action==='RECEIPT'){payload.receipt={state:f.get('state'),evidence_reference:f.get('evidence_reference')};
      for(const k of ['supplier_reference','quote_id'])if(f.get(k))payload.receipt[k]=f.get(k);
      const tickets=String(f.get('ticket_numbers')||'').split(/\r?\n/).map(x=>x.trim()).filter(Boolean);if(tickets.length)payload.receipt.ticket_numbers=tickets;}
     const fingerprint=JSON.stringify(payload);if(!command||command.fingerprint!==fingerprint)command={fingerprint,id:crypto.randomUUID()};
     await request('POST',{...payload,command_id:command.id});command=null;await load();
    }catch(error){show(error)}finally{busy=false;if(button.isConnected)button.disabled=!d.can_operate;}
   };
  }
  function show(e){if(active()){const node=root.querySelector('[data-ticket-message]');if(node)node.textContent=e.message||'处理结果待核实，请刷新';else root.textContent=e.message;}}
  await load().catch(show);
 }
 window.GOTicketOperations={mount};
})();
