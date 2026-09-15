import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View,Switch} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {api,sessionVersion} from '../api/client';
import {GO,screen} from '../design';
import {TopBar,Price,Btn,InfoRow} from '../components/GO';
import {createStayCreditActions} from '../domain/stayCreditActions';

const messages:Record<string,string>={CREDIT_CONSENT_REQUIRED:'请先确认本次金额和额度规则。',CREDIT_QUOTE_EXPIRED_OR_INVALID:'报价或额度期限已失效，请重新获取报价。',CREDIT_QUOTE_UNVERIFIED:'报价信息不完整，请重新获取报价。',CREDIT_ORDER_NOT_AVAILABLE:'订单状态已变化，请返回订单查看进度。',SESSION_OR_SCREEN_CHANGED:'页面或登录身份已变化，请重新进入订单。'};
export default function StayCredit({route,navigation}:any) {
  const orderId=route.params?.orderId;
  const [q,setQ]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[consent,setConsent]=useState(false);
  const sequence=useRef(0),operation=useRef(false);
  const load=useCallback(async()=>{
    const ticket=++sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();
    setLoading(true);setQ(null);setConsent(false);setError('');
    try{const value=await createStayCreditActions(api,current).quote(orderId);if(current())setQ(value);}
    catch(e:any){if(current())setError(messages[e.message]||'暂时无法获取住宿额度报价，请重试。');}
    finally{if(current())setLoading(false);}
  },[orderId]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++;};},[load]));
  const convert=async()=>{
    if(operation.current||!q)return;operation.current=true;setBusy(true);setError('');
    const ticket=sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();
    try{
      await createStayCreditActions(api,current).convert(orderId,q,consent);
      if(current())navigation.replace('OrderDetail',{orderId});
    }catch(e:any){if(current())setError(messages[e.message]||'处理结果需核对，请返回原订单查看额度与取消进度。');}
    finally{operation.current=false;if(current())setBusy(false);}
  };
  return <View style={screen.root}><TopBar title="本店住宿额度" onBack={()=>navigation.goBack()}/><ScrollView contentContainerStyle={screen.content}>
    {loading?<ActivityIndicator color={GO.navy}/>:null}
    {error?<Text accessibilityRole="alert" style={screen.sub}>{error}</Text>:null}
    {q?<><View style={screen.card}><Text style={screen.h2}>本次可转换额度</Text><Price minor={q.credit_value_minor} currency={q.currency}/>
      <InfoRow label="额度到期" value={new Date(q.credit_expires_at).toLocaleString()}/>
      <InfoRow label="报价有效至" value={new Date(q.expires_at).toLocaleString()}/>
      <Text style={screen.sub}>仅限原酒店，到期日不晚于原订单创建后 365 天，转换不会重新起算一年。须在期限内按酒店入住时间办理入住。</Text>
      <Text style={screen.sub}>贵了补差价；便宜了差额不退款、不留余额。原预订取消确认后额度才激活，结果以原订单进度为准。</Text>
      <Text style={screen.sub}>当前为隔离验收，不会产生真实预订或扣款。</Text>
      <View style={screen.row}><Switch accessibilityLabel="确认本次金额和住宿额度规则" value={consent} onValueChange={setConsent} disabled={busy}/><Text style={screen.sub}>我已核对金额、有效期和规则</Text></View>
    </View><Btn title={busy?'正在提交…':'确认转换'} disabled={busy||!consent} onPress={convert}/></>:null}
    <Btn title="重新获取报价" secondary disabled={busy||loading} onPress={load}/>
    <Btn title="查看原订单处理进度" secondary onPress={()=>navigation.replace('OrderDetail',{orderId})}/>
  </ScrollView></View>;
}
