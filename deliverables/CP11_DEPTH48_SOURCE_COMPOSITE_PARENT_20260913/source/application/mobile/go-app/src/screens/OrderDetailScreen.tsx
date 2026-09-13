import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {GO,screen} from '../design';
import {TopBar,Price,Btn,StatusPill,InfoRow,Timeline} from '../components/GO';
import OrderActions from '../components/OrderActions';
import {api,sessionVersion} from '../api/client';
import {readOrder,orderRef} from '../domain/orderActions';
export default function OrderDetail({route,navigation}:any){
  const id=route.params?.orderId,sequence=useRef(0),[d,setD]=useState<any>(null),[remedy,setRemedy]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const load=useCallback(async()=>{const ticket=++sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();setLoading(true);setD(null);setRemedy(null);setError('');
    try{const result=await readOrder(orderRef('HOTEL',id),api);if(!current())return;setD(result.data);
      try{const r=await api('/v1/consumer/orders/'+id+'/supplier-cancellation-remedy');if(current())setRemedy(r.data);}
      catch{if(current())setError('酒店取消赔付信息暂不可用，原订单仍可查看。');}
    }catch{if(current())setError('订单暂时无法读取，请重试。');}finally{if(current())setLoading(false);}
  },[id]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++;};},[load]));
  const o=d?.order,tl=(d?.timeline||[]).slice().reverse().slice(0,8).map((x:any)=>({title:String(x.event_type||'订单事件').replaceAll('_',' '),sub:x.occurred_at,done:true}));
  return <View style={screen.root}><TopBar title="酒店订单" onBack={()=>navigation.goBack()}/><ScrollView contentContainerStyle={screen.content}>
    {loading&&<ActivityIndicator color={GO.navy}/>}{!!error&&<Text style={screen.sub}>{error}</Text>}
    {o&&<><StatusPill text={o.status}/><Text style={screen.h1}>{o.hotel_name||o.product_name||'酒店订单'}</Text>
      {remedy&&<View style={screen.card}><Text style={screen.h2}>酒店主动取消处理</Text><InfoRow label="责任结论" value={remedy.fault_party||remedy.case_state||'待核对'}/>
        <InfoRow label="原支付退款" value={remedy.refund?remedy.refund.status:'待核对'}/><InfoRow label="额外履约赔付" value={remedy.compensation?remedy.compensation.status:'待核对或不适用'}/>
        <Text style={screen.sub}>退款与额外赔付分别核对。</Text></View>}
      <View style={screen.card}><InfoRow label="确认号" value={o.supplier_confirmation_no||'待确认'}/><InfoRow label="支付状态" value={d.payments?.[0]?.status||'暂无支付记录'}/>
        <InfoRow label="退改规则" value={o.fare_rule_summary||'以已确认的订单规则快照为准'}/><Price minor={o.total_amount_minor} currency={o.currency}/>
        <OrderActions order={o} vertical="HOTEL" navigation={navigation}/>
        {o.status==='CONFIRMED'&&<Btn title="核对改期方案" secondary onPress={()=>navigation.navigate('ChangeOrder',{orderId:id})}/>}
        {(d.refunds||[]).map((r:any)=><Text key={r.refund_id} style={screen.sub}>退款：{r.status} · {(r.refund_amount_minor??r.amount_minor)/100} {r.currency}</Text>)}
      </View><View style={screen.card}><Text style={screen.h2}>旅行时间线</Text>{tl.length?<Timeline items={tl}/>:<Text style={screen.sub}>暂无订单事件</Text>}</View>
    </>}<Btn title="刷新原订单" secondary disabled={loading} onPress={()=>{void load();}}/>
  </ScrollView></View>;
}
