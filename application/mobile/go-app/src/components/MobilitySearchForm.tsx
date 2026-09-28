import React,{useRef,useState} from 'react';
import {Alert,ScrollView,Text,View} from 'react-native';
import {screen} from '../design';
import {Brand,Btn,Field} from './GO';
import {mobilityDefaults,rideSearchInput,rentalSearchInput} from '../domain/mobilitySearchInput';
import type {MobilitySearchDraft,RideSearchPayload,RentalSearchPayload} from '../domain/mobilitySearchInput';

export default function MobilitySearchForm({kind,onSearch}:{kind:'ride'|'rental';onSearch:(search:RideSearchPayload|RentalSearchPayload)=>Promise<void>}) {
  const [draft,setDraft]=useState(()=>mobilityDefaults());
  const [busy,setBusy]=useState(false);
  const inFlight=useRef(false),rental=kind==='rental';
  const set=(field:keyof MobilitySearchDraft)=>(value:string)=>setDraft(previous=>({...previous,[field]:value}));
  const go=async()=>{
    if(inFlight.current)return;
    try{
      const search=rental?rentalSearchInput(draft):rideSearchInput(draft);
      inFlight.current=true;setBusy(true);await onSearch(search);
    }catch(e:any){Alert.alert('搜索未完成',e.message||'请检查输入后重试。');}
    finally{inFlight.current=false;setBusy(false);}
  };
  return <ScrollView style={screen.root} contentContainerStyle={screen.content} keyboardShouldPersistTaps="handled">
    <Brand/><Text style={[screen.h1,{marginTop:24}]}>{rental?'自驾租车':'机场接送 / 点到点'}</Text>
    <Text style={[screen.sub,{marginTop:8}]}>填写地点与当地时间，再搜索可用车辆。</Text>
    <View style={[screen.card,{marginTop:18}]}>
      <Field label={rental?'取车地点':'上车地点'} value={draft.pickup} onChangeText={set('pickup')} placeholder="城市、机场或详细地址"/>
      <Field label={rental?'还车地点':'下车地点'} value={draft.dropoff} onChangeText={set('dropoff')} placeholder="城市、机场或详细地址"/>
      <Field label={rental?'取车日期':'上车日期'} value={draft.pickupDate} onChangeText={set('pickupDate')} placeholder="YYYY-MM-DD"/>
      <Field label={rental?'取车地时间（24 小时制）':'出行地时间（24 小时制）'} value={draft.pickupTime} onChangeText={set('pickupTime')} placeholder="HH:mm"/>
      <Field label="出行地时区（默认中国标准时间 +08:00）" value={draft.pickupOffset} onChangeText={set('pickupOffset')} placeholder="+08:00"/>
      <Text style={[screen.sub,{marginTop:8}]}>上方时间使用 UTC{draft.pickupOffset}。默认 +08:00 为中国大陆时间；海外请核对当地出行日的时区及夏令时。</Text>
      {rental&&<>
        <Field label="还车日期" value={draft.returnDate} onChangeText={set('returnDate')} placeholder="YYYY-MM-DD"/>
        <Field label="还车时间（24 小时制）" value={draft.returnTime} onChangeText={set('returnTime')} placeholder="HH:mm"/>
        <Field label="还车地时区（可修改 UTC 偏移）" value={draft.returnOffset} onChangeText={set('returnOffset')} placeholder="+08:00"/>
        <Text style={[screen.sub,{marginTop:8}]}>还车时间使用 UTC{draft.returnOffset}，可与取车地不同。</Text>
      </>}
      <Btn title={busy?'搜索中…':rental?'搜索租车':'搜索接送车辆'} onPress={go} disabled={busy}/>
    </View>
  </ScrollView>;
}
