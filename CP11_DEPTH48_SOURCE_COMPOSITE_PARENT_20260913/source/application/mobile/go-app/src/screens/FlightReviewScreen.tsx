import React from 'react';
import {ScrollView,Text,View} from 'react-native';
import {screen} from '../design';
import {TopBar,Btn,Price} from '../components/GO';
export default function FlightReview({route,navigation}:any){
  const p=route.params||{},o=p.offer||p.x||{},quote=p.prebook;
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><TopBar title="核对机票报价" onBack={()=>navigation.goBack()}/><View style={screen.card}>
    <Text style={screen.h2}>{o.carrier_code}{o.flight_number} · {o.fare_family||'舱位待核对'}</Text>
    <Text style={screen.sub}>{o.origin||'出发地待核对'} → {o.destination||'目的地待核对'} · {o.departure_date}</Text>
    <Text style={screen.sub}>{o.fare_rule_summary||'请核对报价中的行李、退改与出票条件；未提供的条件不能视为已确认。'}</Text>
    {Number.isSafeInteger(quote?.total_amount_minor)?<Price minor={quote.total_amount_minor} currency={quote.currency}/>:<Text>金额待核对</Text>}
    <Text style={screen.sub}>下一步选择已保存的乘机人并授权必要资料；建立订单后再单独确认支付。</Text>
    <Btn title="选择乘机人并继续" disabled={!quote?.prebook_id} onPress={()=>navigation.navigate('FlightPayment',{...p,offer:o})}/>
  </View></ScrollView>;
}
