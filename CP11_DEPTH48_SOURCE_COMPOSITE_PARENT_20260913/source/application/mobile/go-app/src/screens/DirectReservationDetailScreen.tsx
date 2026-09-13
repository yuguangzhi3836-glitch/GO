import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {api,sessionVersion} from '../api/client';
import {screen} from '../design';
import {TopBar,Btn,Price,StatusPill,InfoRow} from '../components/GO';
import {loadDirectReservation} from '../domain/tripFacts';
export default function DirectReservationDetail({route,navigation}:any){
  const id=route.params?.orderId,sequence=useRef(0);
  const [data,setData]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const load=useCallback(async()=>{
    const ticket=++sequence.current,session=sessionVersion();setData(null);setError('');setBusy(true);
    const current=()=>ticket===sequence.current&&session===sessionVersion();
    try{const d=await loadDirectReservation(id,api);if(current())setData(d);}
    catch{if(current())setError('预订记录暂不可用，请核对登录身份后重试。');}
    finally{if(current())setBusy(false);}
  },[id]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++;};},[load]));
  return <View style={screen.root}><TopBar title="酒店直连预订" onBack={()=>navigation.goBack()}/><ScrollView contentContainerStyle={screen.content}>
    {busy&&<ActivityIndicator/>}{!!error&&<Text accessibilityRole="alert" style={screen.sub}>{error}</Text>}
    {data&&<View style={screen.card}><Text style={screen.h2}>{data.id}</Text><StatusPill text={data.state}/>
      <InfoRow label="入住" value={data.checkIn||'待核对'}/><InfoRow label="退房" value={data.checkOut||'待核对'}/>
      <Text style={screen.sub}>预订金额</Text><Price minor={data.amount} currency={data.currency}/>
      <InfoRow label="支付状态" value={data.paymentState}/>
      <Text style={screen.sub}>预订受理不等于酒店确认或扣款完成，请以对应状态为准。</Text>
      {data.events.map((e:any,i:number)=><Text key={e.id||i} style={screen.sub}>{e.at} · {e.type}</Text>)}
    </View>}
    <Btn title="刷新预订状态" disabled={busy} onPress={()=>{void load();}}/>
  </ScrollView></View>;
}
