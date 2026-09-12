(() => {
  'use strict';
  function minor(value){
    if(!/^\d+(?:\.\d{1,2})?$/.test(value))throw Error('金额最多保留两位小数。');
    const [whole,cents='']=value.split('.');const amount=Number(whole)*100+Number(cents.padEnd(2,'0'));
    if(!Number.isSafeInteger(amount)||amount>100000000)throw Error('请填写有效的改期手续费。');
    return amount;
  }
  async function render(ctx){
    const {container,esc}=ctx,get=async path=>ctx.unwrap(await ctx.request(path));
    const run=async(button,fn)=>{if(button.disabled)return;button.disabled=true;try{await fn()}catch(e){ctx.notice(e.message,true)}finally{button.disabled=false}};
    const data=await get('/v1/supplier/catalog-fare/offers');
    container.innerHTML=`<section class="card"><h2>酒店退改规则</h2><p>为不同方案发布可计算的退改规则。已有报价和订单保留当时的版本；发布新版本不会修改旧订单。</p><label>选择酒店方案<select id="cfOffer"><option value="">请选择</option>${data.items.map((x,i)=>`<option value="${i}">${esc(x.property_id)} · ${esc(x.fare_rule_id)} · ${esc(x.currency)}</option>`).join('')}</select></label>${data.items.length?'':'<p>目前没有可管理的酒店报价。请先完成酒店及方案配置。</p>'}</section><section id="cfEdit"></section>`;
    container.querySelector('#cfOffer').onchange=e=>{const selected=e.target.value;if(selected===''){container.querySelector('#cfEdit').innerHTML='';return}paint(data.items[Number(selected)])};
    let activeItem=null;
    function paint(item){
      activeItem=item;
      const current=item.published_rule,r=current?.rules||{},node=container.querySelector('#cfEdit');
      const number=(label,name,max)=>`<label>${label}<input name="${name}" type="number" min="0" max="${max}" step="1" required value="${esc(r[name]??'')}"></label>`;
      const participation=(label,name)=>`<label>${label}<select name="${name}" required><option value="">请选择</option><option value="true" ${r[name]===true?'selected':''}>参加</option><option value="false" ${r[name]===false?'selected':''}>不参加</option></select></label>`;
      node.innerHTML=`<form class="card" id="cfForm"><h3>${current?`发布第 ${current.version+1} 版`:'发布首个规则版本'}</h3><p>币种：${esc(item.currency)}。规则适用于此酒店、供应商、来源和方案。</p><label>方案名称<input name="fare_family" maxlength="64" required value="${esc(r.fare_family||'')}"></label><label>酒店时区<input name="timezone" required placeholder="例如 Asia/Shanghai" value="${esc(r.timezone||'')}"></label>${number('入住时刻（小时）','check_in_hour',23)}${number('预订后免费撤销（分钟；0 表示不提供）','cooling_off_minutes',10080)}<h4>取消费用档</h4><p>按距离入住时间由远到近排列，最后一档从 0 小时开始。越接近入住，费用不得降低。</p><div id="cfTiers"></div><button class="btn" type="button" id="cfAddTier">添加一档</button>${participation('是否允许改期','change_allowed')}<label>改期手续费（${esc(item.currency)}）<input name="change_fee" inputmode="decimal" required value="${r.change_fee_minor==null?'':(r.change_fee_minor/100).toFixed(2)}"></label><p>价差固定为高价补差、等价无差、低价不退。本次发布同时确认：改期后取消按净确认实付计费，含已付改期费、扣除已退款及低价改期已作废差额；剩余款项逐笔原路退回。</p>${participation('是否允许转为本店住宿额度','stay_credit_enabled')}${number('额度期限（1–365 天）','stay_credit_days',365)}<p>额度仅限原酒店，不进入 GO Wallet。本版本可保留净确认扣款，包括已付改期费，并扣除已作废的低价改期差额；客户转换前会再次确认实际金额。</p>${number('未到店宽限（小时）','no_show_grace_hours',48)}<label>未到店费用（百分比）<input name="no_show_percent" type="number" min="0" max="100" step="0.01" required value="${r.no_show_fee_basis_points==null?'':r.no_show_fee_basis_points/100}"></label><label>酒店授权文件或记录引用<input name="authority_reference" required maxlength="512" value="${esc(current?.authority_reference||'')}"></label><label><input name="confirmed" type="checkbox" required>我有权发布上述酒店规则，已核对全部费用和期限。</label><button class="btn primary" type="submit">确认并发布新版本</button><p id="cfStatus" role="status"></p></form>`;
      const form=node.querySelector('#cfForm'),tiers=node.querySelector('#cfTiers');
      function addTier(t={min_hours:0,fee_basis_points:null}){
        const row=document.createElement('div');row.className='business-facts-grid';row.innerHTML=`<label>距离入住至少（小时）<input data-hours type="number" min="0" max="8760" step="1" required value="${esc(t.min_hours)}"></label><label>取消费（百分比）<input data-fee type="number" min="0" max="100" step="0.01" required value="${t.fee_basis_points==null?'':t.fee_basis_points/100}"></label><button type="button" class="btn">移除</button>`;row.querySelector('button').onclick=()=>row.remove();tiers.append(row);
      }
      (r.cancellation_tiers||[{min_hours:0,fee_basis_points:null}]).forEach(addTier);
      node.querySelector('#cfAddTier').onclick=()=>{if(tiers.children.length<20)addTier()};
      form.onsubmit=e=>{e.preventDefault();if(!form.elements.confirmed.checked||!form.reportValidity())return;return run(form.querySelector('button[type="submit"]'),async()=>{
        const f=form.elements,rules={fare_family:f.fare_family.value.trim(),timezone:f.timezone.value.trim(),
          check_in_hour:Number(f.check_in_hour.value),cooling_off_minutes:Number(f.cooling_off_minutes.value),
          cancellation_tiers:[...tiers.children].map(x=>({min_hours:Number(x.querySelector('[data-hours]').value),fee_basis_points:minor(x.querySelector('[data-fee]').value)})),
          change_allowed:f.change_allowed.value==='true',change_fee_minor:minor(f.change_fee.value),
          stay_credit_enabled:f.stay_credit_enabled.value==='true',stay_credit_days:Number(f.stay_credit_days.value),stay_credit_scope:'PROPERTY_ONLY',
          no_show_grace_hours:Number(f.no_show_grace_hours.value),no_show_fee_basis_points:minor(f.no_show_percent.value),
          credit_retained_value_basis:'NET_CONFIRMED_CASH_INCLUDING_PAID_CHANGE_FEES',cash_cancellation_value_basis:'NET_CASH_LESS_FORFEITED_CHANGE_VALUE_INCLUDING_PAID_CHANGE_FEES'};
        const saved=ctx.unwrap(await ctx.request('/v1/supplier/catalog-fare/offers/'+encodeURIComponent(item.offer_id)+'/publish',{method:'POST',body:{rules,authority_reference:f.authority_reference.value.trim(),expected_version_id:current?.version_id||null,confirmed:true}}));
        item.published_rule=saved;if(activeItem===item){paint(item);node.querySelector('#cfStatus').textContent=`第 ${saved.version} 版已发布。已有报价和订单保持原规则。`}else{ctx.notice(`已发布所提交方案的第 ${saved.version} 版。`)}
      })};
    }
  }
  window.GOCatalogFareSupplier={render,minor};
})();
