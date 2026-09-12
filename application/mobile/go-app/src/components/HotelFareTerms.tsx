import React from 'react';
import {Text,View} from 'react-native';
import {screen} from '../design';
export default function HotelFareTerms({fare,currency}:any){
  const r=fare?.rules;
  if(!r)return <Text style={screen.sub}>完整酒店退改规则待返回，暂不能确认下单。</Text>;
  return <View><Text style={screen.h2}>本次酒店退改规则</Text>
    <Text style={screen.sub}>{r.fare_family} · 酒店时区 {r.timezone} · 入住起算 {r.check_in_hour}:00</Text>
    <Text style={screen.sub}>冷静期 {r.cooling_off_minutes} 分钟；以订单规则适用条件为准。</Text>
    {(r.cancellation_tiers||[]).map((t:any,i:number)=><Text key={i} style={screen.sub}>距入住至少 {t.min_hours} 小时：取消费率 {t.fee_basis_points/100}%</Text>)}
    <Text style={screen.sub}>{r.change_allowed?'改期免手续费；原订单创建日起 365 天内入住，连续改期不顺延。涨价补差，降价不退差额。':'本报价不允许改期。'}</Text>
    <Text style={screen.sub}>未入住宽限 {r.no_show_grace_hours} 小时，未入住费率 {r.no_show_fee_basis_points/100}%。</Text>
    <Text style={screen.sub}>{r.stay_credit_enabled?`可按规则转为原酒店住宿额度，有效期 ${r.stay_credit_days} 天。`:'不支持转为住宿额度。'}</Text>
    <Text style={screen.sub}>住宿额度按已确认净现金核算；现金取消退款还会扣除此前改期中不退还的价值与费用。最终应退金额须另取报价确认。</Text>
  </View>;
}
