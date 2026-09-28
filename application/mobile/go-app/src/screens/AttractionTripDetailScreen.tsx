import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {GO,screen} from '../design';
import {TopBar,Btn,Price,StatusPill} from '../components/GO';
import OrderActions from '../components/OrderActions';
import {api,sessionVersion} from '../api/client';
import {readOrder,orderRef} from '../domain/orderActions';
export default function AttractionTripDetail({route,navigation}:any){
  const id=route.params?.orderId||route.params?.order?.order_id,sequence=useRef(0),[o,setO]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const load=useCallback(async()=>{const ticket=++sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();setLoading(true);setO(null);setError('');
    try{const result=await readOrder(orderRef('ATTRACTION',id),api);if(current())setO(result.order);}
    catch{if(current())setError('订单暂时无法读取，请重试。');}finally{if(current())setLoading(false);}
  },[id]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++;};},[load]));
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><TopBar title="门票订单" onBack={()=>navigation.goBack()}/>
    {loading&&<ActivityIndicator color={GO.navy}/>}{!!error&&<Text style={screen.sub}>{error}</Text>}
    {o&&<View style={screen.card}><StatusPill text={o.status}/><Text style={screen.h2}>{o.product_name}</Text>
      <Text style={screen.sub}>{o.visit_date} {o.session_time} · {o.ticket_type} × {o.quantity}</Text>
      <Text style={screen.sub}>凭证：{o.voucher_code||'待出票'}</Text><Price minor={o.total_amount_minor} currency={o.currency}/>
      <Text style={screen.sub}>{o.can_redeem?'当前处于可核销时间窗':'当前不可核销，请核对日期、场次与处理状态'}</Text>
      {o.redemption_window?.opens_at&&<Text style={screen.sub}>有效期：{o.redemption_window.opens_at} 至 {o.redemption_window.closes_at}（不含结束时刻）；目的地时区 {o.redemption_window.destination_timezone}</Text>}
      {o.status==='CLOSED_BY_SUPPLIER'&&<Text style={screen.sub}>供应商已关闭该场次，可核对全额原路退款方案。</Text>}
      <OrderActions order={o} vertical="ATTRACTION" navigation={navigation}/>
      {o.status==='CONFIRMED'&&<Btn title="核对改期方案" secondary onPress={()=>navigation.navigate('AttractionChange',{order:o})}/>}
      {(o.refunds||[]).map((r:any)=><Text key={r.refund_id} style={screen.sub}>退款记录：{r.status} · {r.refund_amount_minor/100} {r.currency}</Text>)}
    </View>}<Btn title="刷新原订单" secondary disabled={loading} onPress={()=>{void load();}}/>
  </ScrollView>;
}
