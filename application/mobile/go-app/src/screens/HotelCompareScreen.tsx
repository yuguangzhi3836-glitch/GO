import React,{useEffect,useState} from 'react';
import {Alert,ScrollView,Text,View} from 'react-native';
import {api} from '../api/client';
import {GO,screen} from '../design';
import {Btn,InfoRow,Price,StatusPill,TopBar} from '../components/GO';

export default function HotelCompare({route,navigation}:any){
  const hotel=route.params?.hotel||{},offers=route.params?.offers||[];
  const [selected,setSelected]=useState<any>(route.params?.offer||offers[0]);
  const [busy,setBusy]=useState(false);
  const selectedId=selected?.offer_id;
  useEffect(()=>setSelected(route.params?.offer||offers[0]),[route.params?.offer?.offer_id]);

  const choose=async()=>{
    if(!selected?.offer_id||busy)return;
    try{
      setBusy(true);
      const prebook=await api(`/v1/offers/${selected.offer_id}/prebook`,{
        method:'POST',body:JSON.stringify({currency:selected.currency})
      });
      navigation.navigate('Payment',{
        hotel,offer:selected,prebook:prebook.data,orderId:null,order:null
      });
    }catch(e:any){
      Alert.alert('价格与库存核验失败',e.message);
    }finally{setBusy(false);}
  };

  return <View style={screen.root}>
    <TopBar title="同房型比价" onBack={()=>navigation.goBack()}/>
    <ScrollView contentContainerStyle={screen.content}>
      <Text style={screen.h1}>{hotel.name||'酒店'}</Text>
      <Text style={[screen.sub,{marginTop:6}]}>核对同一房型的价格、早餐和退改条件，再选择一个报价。</Text>
      {offers.slice(0,4).map((offer:any,index:number)=>{
        const active=offer.offer_id===selectedId;
        return <View key={offer.offer_id||index} style={[screen.card,{borderWidth:active?2:1,borderColor:active?GO.blue:GO.line}]}>
          <View style={screen.row}>
            <StatusPill text={offer.official_direct?'GO 官方直订':'授权来源'} tone={offer.official_direct?'green':'navy'}/>
            <Price minor={offer.total_amount_minor} currency={offer.currency}/>
          </View>
          <Text style={[screen.h2,{marginTop:12}]}>{offer.room_name||offer.room_type_name||'当前房型'}</Text>
          <InfoRow label="早餐" value={offer.meal_plan||'以价格规则为准'}/>
          <InfoRow label="退改" value={offer.refundable?'可退改':'限制退改'}/>
          <Btn title={active?'已选择此报价':'选择此报价'} secondary={!active} disabled={busy} onPress={()=>setSelected(offer)}/>
        </View>;
      })}
      <Btn title={busy?'正在核验价格与库存…':'继续核对并建立待付款订单'} disabled={busy||!selected?.offer_id} onPress={()=>{void choose();}}/>
    </ScrollView>
  </View>;
}
