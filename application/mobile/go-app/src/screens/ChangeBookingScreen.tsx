import React,{useCallback,useRef,useState} from 'react';
import {ScrollView,Text,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {api,sessionVersion} from '../api/client';
import {screen} from '../design';
import {TopBar,Btn,Field,Price,StatusPill} from '../components/GO';
import {changeFields,changeAmount,createChangeActions} from '../domain/changeActions';
import {orderRef,detailTarget} from '../domain/orderActions';
import {changeTerms} from '../domain/changeTerms';

const labels:Record<string,string>={new_check_in:'新入住日期（YYYY-MM-DD）',new_check_out:'新退房日期（YYYY-MM-DD）',new_departure_date:'新出发日期（YYYY-MM-DD）',new_travel_date:'新乘车日期（YYYY-MM-DD）',new_visit_date:'新游览日期（YYYY-MM-DD）',new_session_time:'新场次（HH:mm）',pickup_at:'取车时间（含时区，如 2026-10-01T10:00:00+08:00）',return_at:'还车时间（含时区）'};
const errors:Record<string,string>={CHANGE_INPUT_INVALID:'请填写有效日期、时间和先后顺序。',CHANGE_CONTEXT_CHANGED:'页面或登录身份已变化，请重新核对。',CHANGE_QUOTE_UNVERIFIED:'报价与原订单或所选日期不一致，不能提交。',CHANGE_QUOTE_EXPIRED:'报价已过期，请重新获取并确认。',CHANGE_ISOLATED_CHANNEL_REQUIRED:'当前不是已启用的隔离模拟通道，不能执行改签。',ORDER_NOT_CHANGEABLE:'当前订单状态不允许改签，请查看原订单。',FRESH_CHANGE_QUOTE_REQUIRED:'修改日期后必须重新报价并确认。'};
export default function ChangeBookingScreen({route,navigation,vertical}:any){
  const id=route.params?.orderId||route.params?.order?.order_id;
  const [fields,setFields]=useState<Record<string,string>>({}),[view,setView]=useState<any>(null),[result,setResult]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const sequence=useRef(0),operation=useRef(false),controller=useRef<ReturnType<typeof createChangeActions>|null>(null);
  useFocusEffect(useCallback(()=>{
    const ticket=++sequence.current,version=sessionVersion();
    const active=createChangeActions(api,()=>ticket===sequence.current&&version===sessionVersion());controller.current=active;
    setFields({});setView(null);setResult(null);setError('');setBusy(false);
    return()=>{sequence.current++;active.invalidate();controller.current=null;};
  },[id,vertical]));
  const edit=(key:string,value:string)=>{controller.current?.invalidate();setView(null);setError('');setFields(old=>({...old,[key]:value}));};
  const run=async(submit:boolean)=>{
    if(operation.current||!controller.current)return;
    operation.current=true;setBusy(true);setError('');
    const ticket=sequence.current,version=sessionVersion(),active=controller.current;
    const current=()=>ticket===sequence.current&&version===sessionVersion();
    if(!submit)setView(null);
    try{
      const ref=orderRef(vertical,id);
      const next=submit?await active.submit(ref,fields,true):await active.quote(ref,fields);
      if(current()){if(submit){setView(null);setResult(next);}else{setView(next);setResult(null);}}
    }catch(e:any){if(current()){setView(null);setError(errors[e.message]||'改签结果未能确认，请核对原订单状态，不要重复提交。');}}
    finally{operation.current=false;if(current())setBusy(false);}
  };
  return <View style={screen.root}><TopBar title="核对改签方案" onBack={()=>navigation.goBack()}/><ScrollView contentContainerStyle={screen.content}>
    <Text style={screen.sub}>隔离模拟验收，不产生真实扣款或实际旅行凭证。申请受理不等于供应商确认。</Text>
    <Text style={screen.sub}>原订单：{id||'缺失'}</Text>
    {!busy&&changeFields(vertical).map(key=><Field key={key} label={labels[key]} value={fields[key]||''} onChangeText={v=>edit(key,v)}/>)}
    {!!error&&<Text accessibilityRole="alert" style={screen.sub}>{error}</Text>}
    <Btn title={busy?'正在核对…':'获取改签报价'} disabled={busy||!!result} onPress={()=>{void run(false);}}/>
    {view&&<View style={screen.card}><Text style={screen.h2}>请确认本次方案</Text>
      {changeFields(vertical).map(key=><Text key={key} style={screen.sub}>{labels[key]}：{view.input[key]}</Text>)}
      {changeTerms(vertical,view.quote).map(term=><View key={term.label}><Text style={screen.sub}>{term.label}{term.value?'：'+term.value:''}</Text>{term.minor!==undefined&&<Price minor={term.minor} currency={view.quote.currency}/>}</View>)}
      <Text style={screen.sub}>{changeAmount(vertical,view.quote)<0?'预计原路退款':'本次需补金额'}</Text>
      <Price minor={Math.abs(changeAmount(vertical,view.quote))} currency={view.quote.currency}/>
      <Text style={screen.sub}>报价有效期（服务端时间）：{view.quote.expires_at}</Text>
      <Btn title="确认上述方案、费用及条款并模拟提交" disabled={busy} onPress={()=>{void run(true);}}/>
    </View>}
    {result&&<View style={screen.card}><Text style={screen.sub}>{result.notice==='CHANGE_RESULT_UNKNOWN'?'请求结果待核对；以下是重新读取的原订单状态。':'请求已提交；以下是原订单状态，不代表改签或补款已完成。'}</Text><StatusPill text={result.order.status||'待核对'}/></View>}
    <Btn title="查看原订单状态" secondary disabled={busy} onPress={()=>{try{const t=detailTarget(orderRef(vertical,id));navigation.navigate(t.screen,t.params);}catch{navigation.navigate('Main',{screen:'Trips'});}}}/>
  </ScrollView></View>;
}
