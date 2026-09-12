(() => {
  'use strict';
  function minor(text){
    if(!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(String(text).trim()))throw Error('请填写正数金额，最多两位小数。');
    const [whole,part='']=String(text).trim().split('.'),amount=Number(whole)*100+Number(part.padEnd(2,'0'));
    if(!Number.isSafeInteger(amount)||amount<=0)throw Error('金额必须大于零，并在可精确处理的范围内。');
    return amount;
  }
  async function render(ctx,container,hotel){
    const {request,unwrap,esc,notice}=ctx,base=(ctx.catalog?'/internal/v1/suppliers/':'/internal/v1/hosted-direct/hotels/')+encodeURIComponent(hotel);
    const cash=n=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY'}).format(n/100);
    const get=async()=>unwrap(await request(base+'/fault-finance'));
    const send=async(path,body,key)=>unwrap(await request(path,{method:'POST',body,...(key?{headers:{'Idempotency-Key':key}}:{})}));
    async function run(button,fn){if(button.disabled)return;button.disabled=true;try{await fn()}catch(e){notice(e.message,true)}finally{button.disabled=false}}
    async function load(){
      const d=await get(),a=d.account;
      container.innerHTML=`<section class="card"><h3>${esc(d.hotel_name)} · 赔付资金与授权</h3><p>这里只管理隔离账本中的专项授权与已确认结算回收。资金不足会保持待赔付；客户原款退款单独执行。</p>${a?`<div class="business-facts-grid">${[['待结算可用',a.settlement_available_minor],['保证金可用',a.reserve_available_minor],['银行可用余额',a.bank_available_minor],['待追偿金额',a.negative_balance_minor],['有限保护金可用',d.protection_available_minor]].map(([label,n])=>`<p>${label}<br><b>${cash(n)}</b></p>`).join('')}</div><p>银行通道：${a.debit_mandate_active?'已启用，还须有有效专项授权':'未启用，有专项授权也不会扣款'}</p>`:'<p role="status">尚未配置该酒店的隔离资金账户。当前不会记录赔付成功。</p>'}<h4>最近 20 份专项授权</h4>${d.mandates.map(m=>`<article class="hosted-fault-row"><div><b>${m.effective?'有效授权':({REVOKED:'已撤销',SUPERSEDED:'已替换'})[m.state]||'已过期'}</b><p>每次责任事件最高 ${cash(m.maximum_per_case_minor)} · 到期 ${esc(new Date(m.expires_at).toLocaleString('zh-CN'))}</p><p>${esc(m.authority_reference)}</p></div>${m.state==='ACTIVE'?`<form data-revoke="${esc(m.mandate_id)}"><label><input name="confirmed" type="checkbox" required>确认撤销此授权</label><button class="btn" type="submit">撤销</button></form>`:''}</article>`).join('')||'<p>尚无专项授权。</p>'}<form id="hfMandate"><h4>登记新的专项授权</h4><p>仅用于独立判定的酒店责任取消。新授权生效后，旧授权不再使用。</p><label>单次最高金额（人民币元）<input name="maximum" inputmode="decimal" required></label><label>到期时间（当前设备时区）<input name="expires" type="datetime-local" required></label><label>签署授权的归档引用<input name="reference" required maxlength="512"></label><label>授权文件 SHA256<input name="hash" required pattern="[a-f0-9]{64}" minlength="64" maxlength="64"></label><label><input name="confirmed" type="checkbox" required>已核对授权文件、范围、限额和有效期。</label><button class="btn primary" type="submit">保存专项授权</button></form><form id="hfRecovery"><h4>登记已确认的后续结算</h4><p>先归还本酒店的保护金垫付，再将剩余部分记入待结算可用余额。同一流水只入账一次。</p><label>结算到账金额（人民币元）<input name="amount" inputmode="decimal" required></label><label>唯一结算流水引用<input name="reference" required maxlength="512"></label><label><input name="confirmed" type="checkbox" required>已核验该笔隔离结算记录，金额与流水相符。</label><button class="btn primary" type="submit">登记并回收垫付</button></form><h4>最近 20 笔结算回收</h4>${d.recent_recoveries.map(x=>`<p>${esc(x.settlement_reference)}<br>到账 ${cash(x.incoming_settlement_minor)} · 回收 ${cash(x.recovered_minor)} · 新增可用 ${cash(x.new_available_minor)}</p>`).join('')||'<p>暂无结算回收。</p>'}</section>`;
      container.querySelectorAll('[data-revoke]').forEach(f=>f.onsubmit=e=>{e.preventDefault();if(!f.elements.confirmed.checked)return;run(f.querySelector('button'),async()=>{await send((ctx.catalog?'/internal/v1/supplier-fault-mandates/':'/internal/v1/hosted-direct/fault-mandates/')+encodeURIComponent(f.dataset.revoke)+'/revoke');await load()})});
      const m=container.querySelector('#hfMandate');m.onsubmit=e=>{e.preventDefault();if(!m.elements.confirmed.checked)return;run(m.querySelector('button'),async()=>{const expires=new Date(m.elements.expires.value);if(!Number.isFinite(expires.getTime())||expires<=new Date())throw Error('请选择未来的授权到期时间。');await send(base+'/fault-mandates',{currency:'CNY',maximum_per_case_minor:minor(m.elements.maximum.value),expires_at:expires.toISOString(),authority_reference:m.elements.reference.value.trim(),authority_hash:m.elements.hash.value.trim()});await load()})};
      const r=container.querySelector('#hfRecovery'),key=crypto.randomUUID();r.onsubmit=e=>{e.preventDefault();if(!r.elements.confirmed.checked)return;run(r.querySelector('button'),async()=>{await send(base+(ctx.catalog?'/future-settlement':'/fault-recoveries'),{amount_minor:minor(r.elements.amount.value),settlement_reference:r.elements.reference.value.trim()},key);await load()})};
    }
    try{await load()}catch(e){container.innerHTML='<section class="card"><p>暂时无法加载赔付资金记录，请重试。</p></section>';notice(e.message,true)}
  }
  window.GOHostedFaultFinance={render,minor};
})();
