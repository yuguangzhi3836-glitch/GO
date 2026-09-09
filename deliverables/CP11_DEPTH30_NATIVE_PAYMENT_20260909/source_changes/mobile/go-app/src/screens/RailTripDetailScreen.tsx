import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {GO,screen} from '../design';
import {TopBar,Btn,Price,StatusPill} from '../components/GO';
import OrderActions from '../components/OrderActions';
import {api,sessionVersion} from '../api/client';
import {readOrder,orderRef} from '../domain/orderActions';
export default function RailTripDetail({route,navigation}:any){
  const id=route.params?.orderId,sequence=useRef(0),[o,setO]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const load=useCallback(async()=>{const ticket=++sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();setLoading(true);setO(null);setError('');
    try{const result=await readOrder(orderRef('RAIL',id),api);if(current())setO(result.order);}
    catch{if(current())setError('订单暂时无法读取，请重试。');}finally{if(current())setLoading(false);}
  },[id]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++;};},[load]));
  const j=o?.journey||{};
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><TopBar title="火车票订单" onBack={()=>navigation.goBack()}/>
    {loading&&<ActivityIndicator color={GO.navy}/>}{!!error&&<Text style={screen.sub}>{error}</Text>}
    {o&&<View style={screen.card}><StatusPill text={o.status}/><Text style={screen.h2}>{j.train_no} · {j.seat_class}</Text>
      <Text style={screen.sub}>{j.travel_date} · {j.origin_station} → {j.destination_station}</Text>
      <Text style={screen.sub}>订座号：{o.booking_reference||'待核实'}</Text><Text style={screen.sub}>电子票号：{o.ticket_numbers?.join('、')||'待出票'}</Text>
      <Price minor={o.total_amount_minor} currency={o.currency}/><OrderActions order={o} vertical="RAIL" navigation={navigation}/>
      {o.status==='TICKETED'&&<Btn title="核对改签方案" secondary onPress={()=>navigation.navigate('RailChange',{orderId:id})}/>}
      {(o.refunds||[]).map((r:any)=><Text key={r.refund_id} style={screen.sub}>退款记录：{r.status} · {r.refund_amount_minor/100} {r.currency}</Text>)}
    </View>}<Btn title="刷新原订单" secondary disabled={loading} onPress={()=>{void load();}}/>
  </ScrollView>;
}
