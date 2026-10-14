import React,{useCallback,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,TextInput,View,Pressable,StyleSheet} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {GO,screen} from '../design';
import {TopBar,Btn,StatusPill} from '../components/GO';
import {api} from '../api/client';

const capabilityNames:Record<string,string>={
  DOMESTIC_FLIGHT_READY:'国内航班',INTERNATIONAL_FLIGHT_READY:'国际航班',
  HOTEL_READY:'酒店预订',RAIL_READY:'铁路出行',CAR_RENTAL_READY:'租车',INVOICE_READY:'发票'
};

export default function TravelProfileVault({navigation}:any){
  const[d,setD]=useState<any>(null),[c,setC]=useState<any>(null);
  const[e,setE]=useState(''),[notice,setNotice]=useState(''),[phone,setPhone]=useState(''),[busy,setBusy]=useState(false);
  const load=useCallback(async()=>{
    setE('');
    try{
      const[vault,completeness]=await Promise.all([
        api('/v1/consumer/profile/vault'),api('/v1/consumer/profile/completeness')
      ]);
      setD(vault.data);setC(completeness.data);
    }catch(error:any){setE(error.message||'旅行资料加载失败');}
  },[]);
  useFocusEffect(useCallback(()=>{void load();},[load]));

  const travelers=d?.travelers||[];
  const primary=travelers.find((t:any)=>t.relationship_type==='SELF')||travelers.find((t:any)=>t.is_primary);
  const hotelReady=c?.capabilities?.HOTEL_READY===true;
  const saveHotelContact=async()=>{
    if(busy||!primary?.full_name||!phone.trim())return;
    setBusy(true);setE('');setNotice('');
    try{
      await api('/v1/consumer/profile/vault/bootstrap',{
        method:'POST',body:JSON.stringify({full_name:primary.full_name,phone:phone.trim()})
      });
      await load();
      setPhone('');
      setNotice('手机号已保存到本人的旅行资料库。酒店预订能力状态已更新；下单时仍需选择这位旅行人并确认本次资料使用。');
    }catch(error:any){setE(error.message||'保存酒店联系资料失败');}
    finally{setBusy(false);}
  };

  return <View style={screen.root}>
    <TopBar title="GO Personal Travel Vault" onBack={()=>navigation.goBack()}/>
    <ScrollView contentContainerStyle={screen.content}>
      <Text style={screen.h1}>我的旅行资料库</Text>
      <Text style={screen.sub}>旅行能力根据资料自动判断，不是需要手动勾选的开关。下单时再选择实际出行人。</Text>
      <View style={screen.card}>
        <View style={screen.row}>
          <Text style={screen.h2}>旅行能力</Text>
          {c?<StatusPill text={`${c.ready_count}/${c.capability_count} 项已就绪`} tone={c.ready_count>0?'green':'amber'}/>:null}
        </View>
        {c?Object.entries(c.capabilities||{}).map(([key,value])=>
          <View key={key} style={[screen.row,{marginTop:10}]}>
            <Text style={screen.body}>{capabilityNames[key]||key}</Text>
            <StatusPill text={value?'已就绪':'待补齐'} tone={value?'green':'amber'}/>
          </View>
        ):<Text style={screen.sub}>正在计算...</Text>}
        {!hotelReady&&<View style={{marginTop:16}}>
          <Text style={screen.sub}>酒店预订需要本人姓名和可联系手机号。保存后，GO 会把账号邮箱和你填写的手机号加入本人的资料库；不会自动发送给酒店，下单时还会单独确认。</Text>
          <TextInput value={phone} onChangeText={setPhone} keyboardType="phone-pad" autoComplete="tel" placeholder="输入酒店预订联系电话" placeholderTextColor="rgba(7,27,85,0.40)" style={s.input}/>
          <Btn title={busy?'正在保存…':'保存手机号并完善酒店资料'} disabled={busy||!phone.trim()||!primary?.full_name} onPress={()=>{void saveHotelContact();}}/>
        </View>}
        {hotelReady&&<Text style={[screen.sub,{marginTop:14}]}>酒店预订资料已就绪。回到“核对与支付”选择本人，并确认本次资料使用。</Text>}
        <Btn title="一键导入其他旅行资料" secondary onPress={()=>navigation.navigate('TravelProfileImport')}/>
      </View>
      {!!notice&&<View style={screen.card}><Text style={screen.sub}>{notice}</Text></View>}
      {!!e&&<View style={screen.card}><Text style={screen.h2}>需要处理</Text><Text style={screen.sub}>{e}</Text><Btn title="重试" secondary onPress={()=>void load()}/></View>}
      {!d&&!e&&<ActivityIndicator color={GO.navy}/>}
      {travelers.map((t:any)=><Pressable key={t.traveler_id} style={screen.card} onPress={()=>navigation.navigate('TravelProfileTraveler',{traveler:t})}>
        <View style={screen.row}>
          <View><Text style={screen.h2}>{t.full_name}</Text><Text style={screen.sub}>{t.relationship_type} · {t.facts?.length||0} 项资料</Text></View>
          {t.is_primary?<StatusPill text="本人" tone="green"/>:null}
        </View>
        {(t.facts||[]).slice(0,4).map((fact:any)=><Text key={fact.fact_id} style={s.fact}>{fact.field_type}: {fact.value_masked} · {fact.trust_level}</Text>)}
        <Text style={s.more}>查看来源、可信度与权限 ›</Text>
      </Pressable>)}
      <View style={screen.card}>
        <Text style={screen.h2}>隐私边界</Text>
        <Text style={screen.sub}>敏感资料默认掩码显示。资料只有在你确认订单和本次资料使用后，才按酒店预订所需字段释放并记录审计。</Text>
      </View>
    </ScrollView>
  </View>;
}

const s=StyleSheet.create({
  input:{minHeight:50,borderWidth:1,borderColor:GO.line,borderRadius:16,paddingHorizontal:14,marginTop:12,color:GO.ink,backgroundColor:'white'},
  fact:{marginTop:8,color:GO.slate,fontSize:12},more:{marginTop:12,color:GO.navy,fontWeight:'800'}
});
