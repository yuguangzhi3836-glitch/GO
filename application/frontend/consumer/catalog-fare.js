(() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function terms(prebook,money){
    const published=prebook.fare_rule,r=published?.rules;
    if(!r)throw Error('酒店退改规则尚未确认，请刷新方案后重试。');
    return `<p>以下规则随本单保存，酒店后续发布新规则不会追溯改变本单。</p><div class="kv"><span>含税总价</span><b>${escape(money(prebook.total_amount_minor,prebook.currency))}</b></div><div class="kv"><span>入住时间</span><span>${String(r.check_in_hour).padStart(2,'0')}:00 · ${escape(r.timezone)}</span></div><div class="kv"><span>预订后免费撤销</span><span>${r.cooling_off_minutes?`${r.cooling_off_minutes} 分钟内，且入住前`:'按下方取消费执行'}</span></div><h3>取消费用</h3><table><thead><tr><th>距离入住</th><th>取消费</th></tr></thead><tbody>${r.cancellation_tiers.map(t=>`<tr><td>至少 ${t.min_hours} 小时</td><td>订单金额的 ${t.fee_basis_points/100}%</td></tr>`).join('')}</tbody></table><p>按当前时间适用的一档计算，费用不会逐档叠加。${r.cash_cancellation_value_basis?' 改期后的取消费按净确认实付（含已付改期费、扣除已退款和低价改期作废差额）计算。':' 历史改期费用的退款范围须另行核对。'}</p><div class="kv"><span>改期手续费</span><b>${r.change_allowed?escape(money(r.change_fee_minor,prebook.currency)):'本方案不支持改期'}</b></div>${r.change_allowed?'<p>新日期房价更高时补差；相同价格无差价；更低价格不退差额、不生成余额。</p>':''}<div class="kv"><span>本店住宿额度</span><span>${r.stay_credit_enabled?`可申请转换 · 有效期 ${r.stay_credit_days} 天`:'本方案不支持转换'}</span></div>${r.stay_credit_enabled?'<p>仅限原酒店；可保留金额以确认扣款减已退款为准，包含已付改期费；低价改期已作废的差额不计入额度。转换和兑换前会再次报价确认。</p>':''}<div class="kv"><span>未到店规则</span><span>宽限 ${r.no_show_grace_hours} 小时 · 费用 ${r.no_show_fee_basis_points/100}%</span></div><p>酒店责任取消须独立核实责任；原款退款与额外赔付分别处理。</p>`;
  }
  async function accept(prebook,{dialog,money}){
    if(!prebook.fare_rule?.offer_rule_hash)throw Error('酒店退改规则尚未确认，请刷新方案后重试。');
    const quoted=JSON.parse(JSON.stringify(prebook)),body=terms(quoted,money);
    return dialog('确认这次入住的退改规则',body,'同意规则并继续',()=>({expected_fare_rule_hash:quoted.fare_rule.offer_rule_hash,fare_confirmed:true}));
  }
  function card(rule,order,money){
    if(!rule)return '';
    if(rule.reconciliation_required)return '<section class="card"><h3>本单退改规则</h3><p>历史规则需要核对，处理前会向你确认适用条款。</p></section>';
    return `<section class="card"><details><summary>查看本单已确认的退改规则</summary>${terms({fare_rule:rule,total_amount_minor:order.total_amount_minor,currency:order.currency},money)}</details></section>`;
  }
  window.GOCatalogFare={terms,accept,card};
})();
