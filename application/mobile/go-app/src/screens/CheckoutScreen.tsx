import React,{useCallback,useRef,useState} from 'react';
import {ActivityIndicator,ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {api,sessionVersion} from '../api/client';
import {useAuth} from '../auth/AuthContext';
import {GO,screen} from '../design';
import {TopBar,Btn,Price,StatusPill} from '../components/GO';
import {checkoutView,createOrderActions,detailTarget,orderRef,payable} from '../domain/orderActions';
import type {Vertical} from '../domain/orderActions';
import {bookingIntent} from '../domain/bookingIntent';
import HotelFareTerms from '../components/HotelFareTerms';

const messages:Record<string,string>={PAYMENT_CHANNEL_NOT_READY:'支付渠道尚未就绪，当前不能付款。',ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED:'订单金额已变化，请刷新后重新核对。',BOOKING_TRAVELER_CONSENT_REQUIRED:'请选择出行人并确认本次资料使用。',FRESH_QUOTE_REQUIRED:'报价缺失或已失效，请返回重新选择。',ATTRACTION_PARTY_OR_QUOTE_MISMATCH:'出行人数须与本次门票数量一致。',SESSION_CHANGED:'登录身份已变化，请重新进入订单。',SESSION_OR_SCREEN_CHANGED:'页面或登录身份已变化，请重新核对订单。'};
export default function CheckoutScreen({route,navigation,vertical}:any) {
  const v=vertical as Vertical,auth=useAuth(),params=route.params||{};
  const [id,setId]=useState<string|null>(params.orderId||params.order?.order_id||null);
  const [view,setView]=useState<any>(null),[travelers,setTravelers]=useState<any[]>([]),[selected,setSelected]=useState<string[]>([]);
  const [consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [fareConfirmed,setFareConfirmed]=useState(false);
  const sequence=useRef(0),operation=useRef(false),creationUnknown=useRef(false);
  const load=useCallback(async()=>{
    const ticket=++sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();setLoading(true);setBusy(false);setError('');setView(null);
    try{
      const result=id?await checkoutView(orderRef(v,id),api):(await api('/v1/consumer/profile/vault')).data;
      if(!current())return;
      if(id)setView(result);else setTravelers(result?.travelers||[]);
    }catch(e:any){if(current())setError(messages[e.message]||'暂时无法读取订单或旅行资料，请重试。');}
    finally{if(current())setLoading(false);}
  },[id,v]);
  useFocusEffect(useCallback(()=>{void load();return()=>{sequence.current++;}},[load]));
  const create=async()=>{
    if(operation.current||creationUnknown.current)return;
    operation.current=true;setBusy(true);setError('');const ticket=sequence.current,version=sessionVersion();
    const current=()=>ticket===sequence.current&&version===sessionVersion();
    try{
      const intent=bookingIntent(v,params,auth.profile?.user_id,selected,consent,fareConfirmed);
      let result:any;
      try{result=await api(intent.path,intent.init);}catch(e:any){if(e.uncertain)creationUnknown.current=true;throw e;}
      if(!current())return;
      const created=orderRef(v,result.data?.order_id);
      setId(created.orderId);navigation.setParams({orderId:created.orderId});
      setNotice('订单已建立；请核对最新金额后单独确认支付。');
    }catch(e:any){if(current())setError(creationUnknown.current?'创建结果待核对。请到 GO Trips 查看原订单，暂不重复创建。':messages[e.message]||'订单未能建立，请核对报价与出行资料。');}
    finally{operation.current=false;if(current())setBusy(false);}
  };
  const pay=async()=>{
    if(operation.current||!id||!view)return;operation.current=true;setBusy(true);setError('');
    const ticket=sequence.current,version=sessionVersion(),current=()=>ticket===sequence.current&&version===sessionVersion();
    try{
      const result=await createOrderActions(api,current).pay(orderRef(v,id),view.order);
      if(current()){setView(result);setNotice(result.notice==='PAYMENT_RESULT_UNKNOWN'?'支付请求结果待核对，以下为重新读取的原订单状态。':'原订单状态已更新，请查看确认与支付事实。');}
    }catch(e:any){if(current())setError(messages[e.message]||'支付未能确认，请刷新原订单核对状态。');}
    finally{operation.current=false;if(current())setBusy(false);}
  };
  const details=()=>{if(!id)return;const target=detailTarget(orderRef(v,id));navigation.navigate(target.screen,target.params);};
  return <View style={screen.root}><TopBar title="核对与支付" onBack={()=>navigation.goBack()}/><ScrollView contentContainerStyle={screen.content}>
    {loading&&<ActivityIndicator color={GO.navy}/>}{!!error&&<View style={screen.card}><Text accessibilityRole="alert" style={screen.sub}>{error}</Text></View>}
    {!!notice&&<Text style={screen.sub}>{notice}</Text>}
    {id&&view&&<View style={screen.card}><Text style={screen.h2}>原订单 {id}</Text><StatusPill text={view.order.status||'状态待核对'}/>
      {Number.isSafeInteger(view.order.total_amount_minor)?<Price minor={view.order.total_amount_minor} currency={view.order.currency}/>:<Text>金额待核对</Text>}
      <Text style={screen.sub}>{view.simulation?'隔离支付验证：不产生真实扣款或实际旅行凭证。':'当前没有可用的付款通道，订单会保留。'}</Text>
      <Btn title={busy?'正在核对…':'确认金额并验证支付'} disabled={busy||loading||!view.simulation||!payable(view.order)} onPress={()=>{void pay();}}/>
      <Btn title="查看原订单详情" secondary disabled={busy} onPress={details}/>
    </View>}
    {!id&&!loading&&<View style={screen.card}><Text style={screen.h2}>先建立待付款订单</Text><Text style={screen.sub}>建立订单与完成支付分别确认。出行资料按本次业务所需字段使用，权限不足时不会创建订单。</Text>
      <>{travelers.map(t=><Btn key={t.traveler_id} secondary title={`${selected.includes(t.traveler_id)?'已选择 · ':''}${t.full_name||'出行人'}`} disabled={busy||creationUnknown.current} onPress={()=>{setConsent(false);setSelected(old=>old.includes(t.traveler_id)?old.filter(x=>x!==t.traveler_id):v==='HOTEL'?[t.traveler_id]:[...old,t.traveler_id]);}}/>)}
        <Btn title="管理出行资料与授权" secondary disabled={busy} onPress={()=>navigation.navigate('TravelProfileVault')}/>
        <Btn title={consent?'已确认本次必要资料使用':'确认使用所选出行人的必要资料'} secondary disabled={busy||!selected.length||creationUnknown.current} onPress={()=>setConsent(!consent)}/>
      </>
      {v==='HOTEL'&&<><HotelFareTerms fare={params.prebook?.fare_rule} currency={params.prebook?.currency}/><Btn title={fareConfirmed?'已确认本次酒店规则':'确认上述酒店退改规则'} secondary disabled={busy||!params.prebook?.fare_rule?.rules} onPress={()=>setFareConfirmed(!fareConfirmed)}/></>}
      <Btn title={busy?'正在建立…':'建立订单并核对金额'} disabled={busy||!!error||creationUnknown.current||!consent||(v==='HOTEL'&&!fareConfirmed)} onPress={()=>{void create();}}/>
    </View>}
    <Btn title="刷新当前资料" secondary disabled={busy||loading} onPress={()=>{void load();}}/>
    <Btn title="返回 GO Trips 核对订单" secondary disabled={busy} onPress={()=>navigation.navigate('Main',{screen:'Trips'})}/>
  </ScrollView></View>;
}
