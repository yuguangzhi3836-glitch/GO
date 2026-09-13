import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {api,sessionVersion} from '../api/client';
import {screen,GO} from '../design';
import {TopBar,Btn,Price,StatusPill} from '../components/GO';
import {createOrderActions,detailTarget,orderRef} from '../domain/orderActions';
export default function RefundScreen({route,navigation,vertical}:any){
  const id=route.params?.orderId||route.params?.order?.order_id;
  const [view,setView]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[notice,setNotice]=useState('');
  const sequence=useRef(0),operation=useRef(false);
  const load=useCallback(async()=>{
    const ticket=++sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();setView(null);setBusy(false);setError('');setLoading(true);
    try{const result=await createOrderActions(api,current).refundQuote(orderRef(vertical,id));if(current())setView(result);}
    catch{if(current())setError('当前无法取得可执行的退订报价，请查看原订单状态。');}
    finally{if(current())setLoading(false);}
  },[id,vertical]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++;}},[load]));
  const submit=async()=>{
    if(operation.current||!view?.quote)return;operation.current=true;setBusy(true);setError('');
    const ticket=sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();
    try{const result=await createOrderActions(api,current).refund(orderRef(vertical,id),view.quote);if(current()){setView(result);setNotice(result.notice==='REFUND_RESULT_UNKNOWN'?'退款请求结果待核对，请以下方原订单状态为准。':'退订请求已处理。退订状态与退款到账分别核对。');}}
    catch(e:any){if(current())setError(/RECONFIRM|CASH_FARE_QUOTE_STALE|CASH_FARE_QUOTE_EXPIRED|CANCELLATION_FEE_CHANGED/.test(String(e.message))?'退订金额或规则已变化，请刷新报价后重新确认。':'暂时无法确认退订结果，请查看原订单，勿重复提交。');}
    finally{operation.current=false;if(current())setBusy(false);}
  };
  return <View style={screen.root}><TopBar title="取消与退款" onBack={()=>navigation.goBack()}/><ScrollView contentContainerStyle={screen.content}>
    {loading&&<ActivityIndicator color={GO.navy}/>}{!!error&&<Text accessibilityRole="alert" style={screen.sub}>{error}</Text>}{!!notice&&<Text style={screen.sub}>{notice}</Text>}
    {view&&<View style={screen.card}><Text style={screen.h2}>原订单 {id}</Text><StatusPill text={view.order.status||'状态待核对'}/>
      {view.quote&&<><Text style={screen.sub}>预计原路退款</Text><Price minor={view.quote.refund_amount_minor} currency={view.quote.currency||view.order.currency}/>
        <Text style={screen.sub}>取消费／退票费</Text>{Number.isSafeInteger(view.quote.refund_fee_minor??view.quote.cancellation_fee_minor??view.quote.fee_minor)?<Price minor={view.quote.refund_fee_minor??view.quote.cancellation_fee_minor??view.quote.fee_minor} currency={view.order.currency}/>:<Text>费用待核对</Text>}
        <Text style={screen.sub}>仅确认本次退订；不会将受理状态显示为退款到账。</Text>
        <Btn title={busy?'正在核对…':'确认以上金额并提交退订'} disabled={busy||loading||view.quote.refundable===false} onPress={()=>{void submit();}}/>
      </>}
    </View>}
    <Btn title="刷新退订报价" secondary disabled={busy||loading} onPress={()=>{void load();}}/>
    <Btn title="查看原订单状态" secondary disabled={busy} onPress={()=>{try{const t=detailTarget(orderRef(vertical,id));navigation.navigate(t.screen,t.params);}catch{navigation.navigate('Main',{screen:'Trips'});}}}/>
  </ScrollView></View>;
}
