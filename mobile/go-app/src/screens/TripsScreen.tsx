import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View,Pressable} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {GO,screen} from '../design';
import {TopBar,StatusPill,Btn} from '../components/GO';
import {api} from '../api/client';
import {tripRoute} from '../domain/tripFacts';

export default function Trips({navigation}:any) {
  const [journeys,setJourneys]=useState<any[]>([]),[orders,setOrders]=useState<any[]>([]);
  const [loading,setLoading]=useState(true),[error,setError]=useState('');
  const sequence=useRef(0);
  const load=useCallback(async()=>{
    const ticket=++sequence.current;
    setLoading(true);setError('');setJourneys([]);setOrders([]);
    const results=await Promise.allSettled([api('/v1/trips/journeys'),api('/v1/consumer/unified-trips')]);
    if(ticket!==sequence.current)return;
    if(results[0].status==='fulfilled')setJourneys(results[0].value.data?.items||[]);
    if(results[1].status==='fulfilled')setOrders(results[1].value.data?.items||[]);
    if(results.some(r=>r.status==='rejected'))setError('部分行程未能加载，当前列表可能不完整。');
    setLoading(false);
  },[]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++}},[load]));
  return <View style={screen.root}><TopBar title="GO Trips"/><ScrollView contentContainerStyle={screen.content}>
    <Text style={screen.h1}>我的订单与行程</Text>
    {loading?<ActivityIndicator color={GO.navy}/>:<>
      {!!error&&<View style={screen.card}><Text style={screen.sub}>{error}</Text><Btn title="重试" onPress={()=>{void load()}}/></View>}
      {!error&&orders.length===0&&journeys.length===0&&<View style={screen.card}><Text style={screen.h2}>还没有行程</Text><Text style={screen.sub}>已创建的订单会显示在这里，待付款订单也会保留。</Text></View>}
      {orders.map((o:any)=>{const target=tripRoute(o);return <View key={`${o.vertical}:${o.order_id}`} style={screen.card}>
        <Text style={screen.h2}>{o.title||'订单'}</Text><Text style={screen.sub}>{o.vertical} · {o.order_id}</Text>
        <StatusPill text={o.native_status||o.lifecycle_state||'状态待核对'} tone="navy"/>
        <Text style={screen.sub}>支付：{o.payment_state||'待核对'} · 退款：{o.refund_state||'待核对'}</Text>
        {target?<Btn title="查看原订单" onPress={()=>navigation.navigate(target.screen,target.params)}/>:<Text style={screen.sub}>此类订单的 App 详情入口尚未接入，请在 GO 网页行程中查看。</Text>}
      </View>})}
      {journeys.length>0&&<Text style={screen.h2}>已归组行程</Text>}
      {journeys.map((j:any)=><Pressable key={j.journey_id} style={screen.card} onPress={()=>navigation.navigate('JourneyDetail',{journeyId:j.journey_id})}>
        <Text style={screen.h2}>{j.title||'未命名行程'}</Text><StatusPill text={j.status||'待核对'} tone="navy"/>
        <Text style={screen.sub}>{j.destination_summary||'目的地信息待同步'} · {j.item_count||0} 项</Text>
      </Pressable>)}
    </>}
  </ScrollView></View>;
}
