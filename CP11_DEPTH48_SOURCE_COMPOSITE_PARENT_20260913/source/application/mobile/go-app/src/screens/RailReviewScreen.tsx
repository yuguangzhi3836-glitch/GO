import React from 'react';
import {ScrollView,Text,View} from 'react-native';
import {screen} from '../design';
import {TopBar,Btn,Price} from '../components/GO';
export default function RailReview({route,navigation}:any){
  const p=route.params||{},o=p.offer||{},quote=p.prebook;
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><TopBar title="核对火车票报价" onBack={()=>navigation.goBack()}/><View style={screen.card}>
    <Text style={screen.h2}>{o.train_no} · {o.seat_class}</Text><Text style={screen.sub}>{o.travel_date} · {o.origin_station||'出发站待核对'} → {o.destination_station||'到达站待核对'}</Text>
    {Number.isSafeInteger(quote?.total_amount_minor)?<Price minor={quote.total_amount_minor} currency={quote.currency}/>:<Text>金额待核对</Text>}
    <Text style={screen.sub}>下一步选择已保存的乘车人并授权必要资料；建立订单后再单独确认支付。</Text>
    <Btn title="选择乘车人并继续" disabled={!quote?.prebook_id} onPress={()=>navigation.navigate('RailPayment',p)}/>
  </View></ScrollView>;
}
