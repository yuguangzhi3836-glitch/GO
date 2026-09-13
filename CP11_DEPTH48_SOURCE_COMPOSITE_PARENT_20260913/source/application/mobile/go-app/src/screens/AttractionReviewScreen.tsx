import React,{useRef,useState} from 'react';
import {ScrollView,Text,View} from 'react-native';
import {screen} from '../design';
import {TopBar,Btn,Price} from '../components/GO';
import {api,sessionVersion} from '../api/client';
export default function AttractionReview({route,navigation}:any){
  const p=route.params||{},o=p.offer||{},quantity=p.quantity??1,lock=useRef(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function next(){
    if(lock.current)return;lock.current=true;setBusy(true);setError('');const version=sessionVersion();
    try{
      const result=await api('/v1/attractions/prebook',{method:'POST',body:JSON.stringify({offer_id:o.offer_id,visit_date:o.visit_date,session_time:o.session_time??null,quantity,currency:o.currency})});
      if(version===sessionVersion())navigation.navigate('AttractionPayment',{offer:o,prebook:result.data,quantity});
    }catch{if(version===sessionVersion())setError('报价未能确认，请刷新产品后重试。');}finally{lock.current=false;setBusy(false);}
  }
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><TopBar title="核对门票报价" onBack={()=>navigation.goBack()}/><View style={screen.card}>
    <Text style={screen.h2}>{o.product_name}</Text><Text style={screen.sub}>{o.visit_date} {o.session_time} · {o.ticket_type} × {quantity}</Text>
    {Number.isSafeInteger(o.total_amount_minor)?<Price minor={o.total_amount_minor*quantity} currency={o.currency}/>:<Text>金额待核对</Text>}
    <Text style={screen.sub}>库存与价格以此次报价确认结果为准；下一步选择出行人。</Text>{!!error&&<Text accessibilityRole="alert">{error}</Text>}
    <Btn title={busy?'正在确认报价…':'确认报价并继续'} disabled={busy||!o.offer_id||!o.visit_date} onPress={()=>{void next();}}/>
  </View></ScrollView>;
}
