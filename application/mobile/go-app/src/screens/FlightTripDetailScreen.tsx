import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,Linking,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {GO,screen} from '../design';
import {Brand,Btn,Price,StatusPill} from '../components/GO';
import {api} from '../api/client';
import {flightCells} from '../domain/tripFacts';
import OrderActions from '../components/OrderActions';
const labels:Record<string,string>={COUPON_REFUNDED:'该票券已退票，不可值机',COUPON_UNAVAILABLE:'该票券暂不可值机，请查看处理进度',CHECK_IN_UNVERIFIED:'等待核实值机信息',CHECK_IN_NOT_OPEN:'值机未开放',CHECK_IN_OPEN:'值机已开放',CHECKED_IN:'已值机',BOARDING_PASS_AVAILABLE:'登机牌可用'};
export default function FlightTripDetail({route,navigation}:any) {
  const id=route.params?.orderId,sequence=useRef(0);
  const [order,setOrder]=useState<any>(null),[checkin,setCheckin]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const load=useCallback(async()=>{
    const ticket=++sequence.current;setLoading(true);setError('');setOrder(null);setCheckin(null);
    try {
      if(typeof id!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(id))throw Error('订单编号无效');
      const result=(await api(`/v1/flights/orders/${id}`)).data;
      if(result?.order_id!==id)throw Error('订单信息不一致');
      if(ticket!==sequence.current)return;setOrder(result);
      try{const facts=(await api(`/v1/flights/orders/${id}/check-in`)).data;if(ticket===sequence.current)setCheckin(facts)}
      catch{if(ticket===sequence.current)setError('值机信息暂不可用，订单详情仍可查看。')}
    }catch{if(ticket===sequence.current)setError('订单加载失败，请重试。')}
    finally{if(ticket===sequence.current)setLoading(false)}
  },[id]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++}},[load]));
  const open=async(url:string)=>{try{await Linking.openURL(url)}catch{setError('暂时无法打开链接，请刷新值机信息后重试。')}};
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><Brand/><Text style={screen.h1}>机票订单</Text>
    {loading&&<ActivityIndicator color={GO.navy}/>}{!!error&&<Text style={screen.sub}>{error}</Text>}
    <Btn title="刷新订单与值机信息" disabled={loading} onPress={()=>{void load()}}/>
    {order&&<>
      <View style={screen.card}><StatusPill text={order.status} tone="navy"/>
        {(order.itinerary||[]).map((leg:any,i:number)=><Text key={i} style={screen.sub}>第 {i+1} 程 · {leg.carrier_code}{leg.flight_number} · {leg.departure_date} · {leg.origin} → {leg.destination}</Text>)}
        <Text style={screen.sub}>PNR：{order.pnr||'待核实'}</Text><Text style={screen.sub}>电子票号：{order.ticket_numbers?.join('、')||'待出票'}</Text>
        <Text style={screen.sub}>累计实付</Text><Price minor={order.total_amount_minor} currency={order.currency}/>
        {Number.isSafeInteger(order.refunded_amount_minor)&&<><Text style={screen.sub}>累计已退</Text><Price minor={order.refunded_amount_minor} currency={order.currency}/><Text style={screen.sub}>净实付</Text><Price minor={order.total_amount_minor-order.refunded_amount_minor} currency={order.currency}/></>}<OrderActions order={order} vertical="FLIGHT" navigation={navigation}/>
      </View>
      {(order.coupons||[]).map((c:any)=><View style={screen.card} key={c.coupon_id}>
        <Text style={screen.h2}>{c.passenger_name} · 第 {c.leg_index+1} 程</Text>
        <Text style={screen.sub}>{c.leg.origin} → {c.leg.destination} · {c.leg.departure_date} · {c.state}</Text>
        <Text style={screen.sub}>票号 {c.ticket_number||'等待出票'} · 预订编号 {c.supplier_reference||'待核实'}</Text>
      </View>)}
      {!!order.coupons?.length&&<View style={screen.card}>
        <Btn title="选择乘客与航段改签" disabled={order.status!=='TICKETED'} onPress={()=>navigation.navigate('FlightCouponActions',{orderId:id,mode:'CHANGE'})}/>
        <Btn title="选择乘客退票 / 继续原退款" disabled={!['TICKETED','REFUND_PENDING'].includes(order.status)} onPress={()=>navigation.navigate('FlightCouponActions',{orderId:id,mode:'REFUND'})}/>
      </View>}
      <Text style={screen.h2}>每位乘机人的每一程</Text>
      {flightCells(order,checkin).map((cell:any)=><View style={screen.card} key={`${cell.legIndex}:${cell.passengerIndex}`}>
        <Text style={screen.h2}>第 {cell.legIndex+1} 程 · {cell.person.full_name||`乘机人 ${cell.passengerIndex+1}`}</Text>
        <StatusPill text={labels[cell.state]} tone={cell.state==='BOARDING_PASS_AVAILABLE'?'green':'navy'}/>
        {cell.officialUrl&&<Btn title="前往航空公司办理" onPress={()=>{const fresh=flightCells(order,checkin).find((x:any)=>x.legIndex===cell.legIndex&&x.passengerIndex===cell.passengerIndex);if(fresh?.officialUrl)void open(fresh.officialUrl);else setError('值机信息已过期，请刷新。')}}/>}
        {cell.passUrl&&<Btn title="查看该乘机人的登机牌" onPress={()=>{const fresh=flightCells(order,checkin).find((x:any)=>x.legIndex===cell.legIndex&&x.passengerIndex===cell.passengerIndex);if(fresh?.passUrl)void open(fresh.passUrl);else setError('登机牌信息已过期，请刷新。')}}/>}
      </View>)}
      {checkin?.data_mode==='SIMULATION'&&<Text style={screen.sub}>当前未连接航空公司实时服务，请勿作为实际出行凭证。</Text>}
      {order.status==='TICKETED'&&<View style={screen.card}><Btn title="核对改签方案" onPress={()=>navigation.navigate('FlightChange',{orderId:id})}/></View>}
    </>}
  </ScrollView>;
}
