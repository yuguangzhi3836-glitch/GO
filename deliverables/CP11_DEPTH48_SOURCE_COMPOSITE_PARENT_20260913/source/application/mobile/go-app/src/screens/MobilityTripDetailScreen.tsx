import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {GO,screen} from '../design';
import {Brand,Btn,InfoRow,Price,StatusPill} from '../components/GO';
import {api} from '../api/client';
import {loadMobility} from '../domain/tripFacts';
import OrderActions from '../components/OrderActions';
export default function MobilityTripDetail({route,navigation}:any) {
  const id=route.params?.orderId,sequence=useRef(0);
  const [data,setData]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const load=useCallback(async()=>{
    const ticket=++sequence.current;setLoading(true);setError('');setData(null);
    try{const result=await loadMobility(id,api);if(ticket===sequence.current)setData(result)}
    catch{if(ticket===sequence.current)setError('订单加载失败，请重试。')}
    finally{if(ticket===sequence.current)setLoading(false)}
  },[id]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++}},[load]));
  const o=data?.order,t=data?.tracking,b=t?.binding;
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><Brand/>
    <Text style={screen.h1}>{o?.vertical==='RENTAL'?'租车订单':'接送订单'}</Text>
    {loading&&<ActivityIndicator color={GO.navy}/>}{!!error&&<Text style={screen.sub}>{error}</Text>}
    <Btn title="刷新订单" disabled={loading} onPress={()=>{void load()}}/>
    {o&&<View style={screen.card}><StatusPill text={o.status} tone="navy"/>
      {o.vertical==='RENTAL'?<><InfoRow label="取车地点" value={o.pickup_location||'待核对'}/><InfoRow label="还车地点" value={o.return_location||'待核对'}/><InfoRow label="取车时间" value={o.pickup_at||'待核对'}/><InfoRow label="还车时间" value={o.return_at||'待核对'}/></>:<>
        <InfoRow label="上车地点" value={o.pickup||'待核对'}/><InfoRow label="下车地点" value={o.dropoff||'待核对'}/>
        <InfoRow label="已确认接车时间" value={t?.confirmed_pickup_at||o.pickup_at||'待车队确认'}/>
      </>}<Price minor={o.total_amount_minor} currency={o.currency}/><OrderActions order={o} vertical={o.vertical} navigation={navigation}/></View>}
    {!!data?.trackingError&&<Text style={screen.sub}>{data.trackingError}</Text>}
    {t&&<View style={screen.card}><Text style={screen.h2}>航班与接送安排</Text>
      <Text style={screen.sub}>{b?(b.tracking_enabled?(b.source_current===false?'航班来源暂不可用':'已开启航班追踪'):'已暂停航班追踪'):'未关联航班'}</Text>
      {b&&<InfoRow label="包含免费等待" value={`${b.included_wait_minutes} 分钟`}/>}
      {(t.events||[]).slice().reverse().map((e:any,i:number)=><View key={e.event_id||i}><StatusPill text={e.status||'待核对'} tone={e.status==='CONFIRMED'?'green':'navy'}/><Text style={screen.sub}>{e.status==='CONFIRMED'?'该次确认':'建议'}接车时间：{e.proposed_pickup_at}</Text>{Number.isFinite(e.free_wait_minutes)&&<Text style={screen.sub}>本次规则内免费等待：{e.free_wait_minutes} 分钟</Text>}</View>)}
      {t.data_mode==='SIMULATION'&&<Text style={screen.sub}>当前为模拟体验，未连接真实车队。</Text>}
    </View>}
  </ScrollView>;
}
