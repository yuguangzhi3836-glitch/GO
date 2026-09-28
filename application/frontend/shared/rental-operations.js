/* Rental business actions. Financial outcomes are exclusively displayed by C11. */
(() => {
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const unwrap=x=>x&&Object.prototype.hasOwnProperty.call(x,'data')?x.data:x;
  const labels={AWAITING_CUSTOMER:'等待你的回应',REVIEW_REQUIRED:'等待独立审核',ADJUDICATED:'裁决已记录',APPEAL_REVIEW_REQUIRED:'申诉审核中'};
  const money=(v,c)=>`${(v/100).toFixed(2)} ${c}`;
  async function render({container,orderId,request}) {
    const mount=Symbol('rental-operations');container.rentalOperationsMount=mount;
    let seq=0,view=null,pending=null,note='',storageHealthy=true;
    const live=()=>container.isConnected&&container.rentalOperationsMount===mount;
    const base=`/v1/mobility/rentals/orders/${encodeURIComponent(orderId)}`;
    const admin=`/internal/v1/admin/mobility/rentals/orders/${encodeURIComponent(orderId)}/operations`;
    const storageKey=()=>`go:rental-op:${view.actor_id}:${orderId}`;
    const setPending=op=>{
      if(op)sessionStorage.setItem(storageKey(),JSON.stringify(op));else sessionStorage.removeItem(storageKey());
      pending=op;
    };
    const changed=()=>window.dispatchEvent(new CustomEvent('go:rental-operation-changed',{detail:{orderId}}));
    function form(action,item){
      const c=item?.case,decision=['DECISION','APPEAL_DECISION'].includes(action);
      let fields='';
      if(action==='OPEN')fields=`<label>申报金额（分）<input name="amount_minor" type="number" min="1" step="1" required></label><label>取车时的观察陈述<textarea name="pickup_statement" maxlength="4000" required></textarea></label><label>还车时的观察陈述<textarea name="return_statement" maxlength="4000" required></textarea></label>`;
      else fields=`${action==='RESPONSE'?'<label>你的回应<select name="response"><option value="DISPUTE">提出异议</option><option value="ACCEPT">认可申报事实，仍交独立审核</option></select></label>':''}${decision?`<label>裁决金额（分，上限 ${esc(c.claimed_minor)}）<input name="award_minor" type="number" min="0" max="${esc(c.claimed_minor)}" step="1" required></label>`:''}<label>${action==='RETURN_REVIEW'?'最终还车／取消检查说明':'陈述与理由'}<textarea name="statement" maxlength="${decision||action==='APPEAL'?2000:4000}" required></textarea></label>`;
      const names={OPEN:'登记车损申报',RESPONSE:'提交回应',APPEAL:'提交申诉',DECISION:'记录独立裁决',APPEAL_DECISION:'记录独立复核',RETURN_REVIEW:'确认最终检查并建立释放依据'};
      return `<form data-rental-command="${action}" data-case-id="${esc(c?.case_id||'')}" style="display:grid;gap:12px;max-width:640px"><h4>${names[action]}</h4>${fields}<p>文字记录仅代表提交人的陈述，不是照片认证或供应商独立查证。该操作不会执行扣款、退款或释放押金。</p>${action==='RETURN_REVIEW'?'<p>请确认已完成最终无损检查，或核对已完成的取消退款事实。确认后不能再以该押金新开车损申报。</p>':''}<label><input name="confirmed" type="checkbox" required> 我已核对当前订单、内容和金额，明确提交本次操作。</label><button class="btn primary" type="submit">${names[action]}</button><span data-form-error role="alert"></span></form>`;
    }
    function paint(){
      if(!live())return;
      container.innerHTML=`<h2>租车争议与运营处理</h2><p>隔离测试流程。押金是否扣收、退回或释放，以资金记录为准。</p><p role="status" data-operation-note>${esc(note)}</p>`;
      if(pending){
        container.insertAdjacentHTML('beforeend','<p role="alert">上次请求结果尚未确认。请先核对状态；重试将保留同一请求和内容，不会创建另一笔操作。</p><button class="btn" data-retry-operation>重试原请求</button>');
        container.querySelector('[data-retry-operation]').onclick=()=>send(pending);
      }
      for(const item of view.cases){
        const c=item.case;
        const decisions=c.decision_history||[],last=decisions.at(-1),prior=decisions.at(-2);
        const revisionNote=prior&&last?`<p data-liability-revision>前次裁决 ${esc(money(prior.award_minor,c.currency))} · 当前复核 ${esc(money(last.award_minor,c.currency))}。</p><p>${last.award_minor<prior.award_minor?'复核减收仅形成差额核对依据。若原费用已经结算，须由资金流程另行确认补偿；这条复核记录不表示已退款。':last.award_minor>prior.award_minor?'本次复核金额上调，本入口不会据此再次扣收，须另行处理。':'责任金额未变，不会因重复复核自动新增退款或扣款。'}</p>`:'';
        container.insertAdjacentHTML('beforeend',`<article class="card"><h3>车损记录</h3><p>${esc((c.status==='AWAITING_CUSTOMER'&&view.actor_type!=='CONSUMER'?'等待消费者回应':labels[c.status])||'状态待核验')} · 版本 ${esc(c.version)}</p><p>申报 ${esc(money(c.claimed_minor,c.currency))}${c.awarded_minor!==null?` · 裁决 ${esc(money(c.awarded_minor,c.currency))}`:''}</p>${c.money_instruction_state==='DISPUTE_HOLD'?'<p>申诉未闭合，暂停新的费用指令；已有资金记录不会在此自动撤销。</p>':''}<p>${esc(c.decision_reason||'')}</p>${(c.appeals||[]).map(a=>`<blockquote>申诉：${esc(a.reason)}</blockquote>`).join('')}<div data-case-actions="${esc(c.case_id)}"></div></article>`);
        const node=[...container.querySelectorAll('[data-case-actions]')].find(n=>n.dataset.caseActions===c.case_id);
        node.insertAdjacentHTML('beforebegin',revisionNote);
        if(!pending&&storageHealthy)for(const action of item.actions)node.insertAdjacentHTML('beforeend',form(action,item));
      }
      if(!view.cases.length)container.insertAdjacentHTML('beforeend','<p>当前没有车损争议记录。</p>');
      if(view.release)container.insertAdjacentHTML('beforeend','<p>最终检查和释放依据已记录。资金是否已释放，请查看资金记录。</p>');
      if(!pending&&storageHealthy)for(const action of view.actions)container.insertAdjacentHTML('beforeend',form(action));
      if(!view.writes_enabled)container.insertAdjacentHTML('beforeend','<p>当前环境仅可查看这些隔离流程记录。</p>');
      container.insertAdjacentHTML('beforeend','<button class="btn" data-refresh-operations>核对最新状态</button>');
      container.querySelector('[data-refresh-operations]').onclick=()=>load();
      container.querySelectorAll('[data-rental-command]').forEach(f=>{f.onsubmit=e=>{e.preventDefault();submit(f)};});
    }
    async function load(){
      const id=++seq;
      try{
        const result=unwrap(await request(`${base}/operations`));
        if(!live()||id!==seq)return;
        view=result;
        try{pending=JSON.parse(sessionStorage.getItem(storageKey())||'null');}
        catch(_){note='无法读取本次会话的操作记录，已暂停新操作。请保留当前页面并联系支持核对。';pending=null;storageHealthy=false;}
        if(pending&&(view.receipts||[]).some(r=>r.key===pending.key)){
          setPending(null);note='上次请求已记录。以下显示当前最新业务状态，资金结果仍以资金记录为准。';changed();
        }
        paint();
      }catch(_){if(live()&&id===seq){container.innerHTML='<h2>租车运营处理</h2><p role="alert">暂时无法核对记录，不能据此判断操作成功或资金已处理。</p><button class="btn" data-load-retry>重新核对</button>';container.querySelector('[data-load-retry]').onclick=()=>load();}}
    }
    async function send(op){
      if(!live()||!view||op.actor!==view.actor_id)return;
      container.querySelectorAll('button').forEach(b=>b.disabled=true);
      try{
        await request(op.path,{method:'POST',headers:{'Idempotency-Key':op.key},body:op.body});
        if(!live())return;
        // Even a 200 response may be a historical idempotent reply. Read current
        // workspace/receipt before describing the current state to the operator.
        note='请求已返回，正在核对最新业务记录…';await load();
      }catch(error){
        if(!live())return;
        if([403,404,409,422].includes(error.status)){
          setPending(null);note='本次请求未通过当前权限或版本检查。请核对最新记录后重新确认。';
        }else note='连接中断或结果尚未确认。已保留原请求，请核对状态或重试原请求。';
        await load();
      }
    }
    function submit(f){
      if(pending||!storageHealthy||!view||!live())return;
      const action=f.dataset.rentalCommand,c=view.cases.find(i=>i.case.case_id===f.dataset.caseId)?.case;
      const value=name=>f.elements.namedItem(name)?.value||'';
      const error=f.querySelector('[data-form-error]');
      if(!f.elements.namedItem('confirmed')?.checked){error.textContent='请先明确确认本次操作。';return;}
      let path,body;
      if(action==='OPEN'){
        body={amount_minor:Number(value('amount_minor')),currency:view.currency,pickup_statement:value('pickup_statement'),return_statement:value('return_statement')};path=view.actor_type==='SUPPLIER_USER'?`/v1/supplier/mobility/rentals/orders/${encodeURIComponent(orderId)}/operations/cases`:`${admin}/cases`;
        if(!Number.isSafeInteger(body.amount_minor)||body.amount_minor<=0||!body.pickup_statement.trim()||!body.return_statement.trim()){error.textContent='请填写有效金额和取还车陈述。';return;}
      }else{
        body={statement:value('statement')};if(!body.statement.trim()){error.textContent='请填写明确的陈述和理由。';return;}
        if(action==='RETURN_REVIEW'){
          const o=view.obligation;body.expected_revision=o.revision;body.expected_source_hash=o.source_hash;path=`${admin}/obligations/${encodeURIComponent(o.obligation_id)}/return-review`;
        }else{
          body.expected_version=c.version;
          const suffix={RESPONSE:'response',APPEAL:'appeal',DECISION:'decision',APPEAL_DECISION:'appeal-decision'}[action];
          path=`${['RESPONSE','APPEAL'].includes(action)?base+'/operations':admin}/cases/${encodeURIComponent(c.case_id)}/${suffix}`;
          if(action==='RESPONSE')body.response=value('response');
          if(['DECISION','APPEAL_DECISION'].includes(action)){body.award_minor=Number(value('award_minor'));if(!value('award_minor').trim()||!Number.isSafeInteger(body.award_minor)||body.award_minor<0||body.award_minor>c.claimed_minor){error.textContent='裁决金额必须在申报范围内。';return;}}
        }
      }
      const op={actor:view.actor_id,key:crypto.randomUUID(),path,body};
      try{setPending(op);}catch(_){error.textContent='浏览器无法保存本次操作，请恢复会话存储后重试；尚未提交。';return;}
      void send(op);
    }
    await load();
    return {refresh:load};
  }
  window.GORentalOperations={render};
})();
