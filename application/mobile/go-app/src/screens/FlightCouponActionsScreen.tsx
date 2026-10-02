import React,{useCallback,useRef,useState} from 'react';
import {ScrollView,Text,TextInput,View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {screen} from '../design';
import {Brand,Btn,Price} from '../components/GO';
import {api,sessionVersion} from '../api/client';

export default function FlightCouponActions({route}:any){
  const id=route.params?.orderId,mode=route.params?.mode==='CHANGE'?'CHANGE':'REFUND';
  const [order,setOrder]=useState<any>(null),[ids,setIds]=useState<string[]>([]),[dates,setDates]=useState<Record<string,string>>({});
  const [quote,setQuote]=useState<any>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const generation=useRef(0),pending=useRef(false);
  const load=useCallback(async()=>{
    const g=++generation.current;setOrder(null);setQuote(null);setIds([]);setMessage('');
    if(typeof id!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(id)){setMessage('订单编号无效');return;}
    try{const o=(await api('/v1/flights/orders/'+id)).data;
      if(g!==generation.current)return;if(o.order_id!==id)throw Error('订单信息不一致');
      setOrder(o);setDates(Object.fromEntries((o.coupons||[]).map((c:any)=>[c.coupon_id,c.leg.departure_date])));
      if(mode==='REFUND')setQuote((o.coupon_refunds||[]).find((q:any)=>q.status==='PREPARED')||null);
    }catch(e:any){if(g===generation.current)setMessage(e.message||'订单读取失败');}
  },[id,mode]);
  useFocusEffect(useCallback(()=>{void load();return()=>{generation.current++}},[load]));
  async function act(submit:boolean){
    if(pending.current||!order)return;pending.current=true;setBusy(true);setMessage('');
    const g=generation.current,session=sessionVersion(),base='/v1/flights/orders/'+id;
    const current=()=>{if(g!==generation.current||session!==sessionVersion())throw Error('当前账户或订单已变化');};
    try{
      current();
      if(submit){
        if(!quote)throw Error('请先核对方案');
        const refund=mode==='REFUND';
        if(refund&&quote.status!=='PREPARED'&&quote.expires_ms<=Date.now())throw Error('报价已过期');
        await api(base+(refund?'/coupon-refunds/'+quote.refund_id:'/execute-change/'+quote.quote_id),{
          method:'POST',headers:{'Idempotency-Key':`coupon:${id}:${quote.refund_id||quote.quote_id}`},body:JSON.stringify(refund?
          {quote_hash:quote.quote_hash,expected_refund_amount_minor:quote.refund_amount_minor,currency:quote.currency,confirmed:true}:
          {quote_hash:quote.quote_hash,expected_total_due_minor:quote.total_due_minor,currency:quote.currency,confirmed:true})});
        current();await load();setMessage('申请已提交，当前订单展示服务端处理状态。');
      }else{
        if(!ids.length)throw Error('请选择乘机人与航段');
        const changes=ids.map(cid=>{const c=order.coupons.find((x:any)=>x.coupon_id===cid);
          if(!c?.usable)throw Error('票券状态已变化');
          if(mode==='CHANGE'&&(!/^\d{4}-\d{2}-\d{2}$/.test(dates[cid]||'')||dates[cid]===c.leg.departure_date))throw Error('请填写新的出发日期');
          return {leg_index:c.leg_index,coupon_ids:[cid],new_departure_date:dates[cid]};});
        const q=(await api(base+(mode==='REFUND'?'/coupon-refund-quotes':'/change-quote'),{method:'POST',body:JSON.stringify(mode==='REFUND'?{coupon_ids:ids}:{changes})})).data;
        current();const selected=mode==='REFUND'?q.coupon_ids:(q.coupon_changes||[]).map((c:any)=>c.coupon_id);
        const amount=mode==='REFUND'?q.refund_amount_minor:q.total_due_minor;
        if(q.order_id!==id||q.currency!==order.currency||!/^[a-f0-9]{64}$/.test(q.quote_hash)||!Number.isSafeInteger(amount)||amount<0
          ||!Array.isArray(selected)||selected.length!==ids.length||ids.some(cid=>!selected.includes(cid)))throw Error('返回方案与所选票券不一致');
        setQuote(q);
      }
    }catch(e:any){if(g===generation.current){setMessage(e.message||'处理结果待核实，请刷新原订单');if(submit)setQuote(null);}}
    finally{pending.current=false;setBusy(false);}
  }
  const selected=quote&&(mode==='REFUND'?quote.coupon_ids:(quote.coupon_changes||[]).map((c:any)=>c.coupon_id));
  return <ScrollView style={screen.root} contentContainerStyle={screen.content}><Brand/><Text style={screen.h1}>{mode==='CHANGE'?'选择乘客改签':'选择乘客退票'}</Text>
    {!!message&&<Text accessibilityRole="alert" style={screen.sub}>{message}</Text>}
    <Btn title="刷新原订单与处理进度" disabled={busy} onPress={()=>{void load()}}/>
    {order&&(order.coupons||[]).map((c:any)=><View style={screen.card} key={c.coupon_id}>
      <Text style={screen.h2}>{c.passenger_name} · 第 {c.leg_index+1} 程</Text>
      <Text style={screen.sub}>{c.leg.origin} → {c.leg.destination} · {c.leg.departure_date} · {c.state}</Text>
      {quote?<Text>{selected.includes(c.coupon_id)?'本次选择':'保留原票券'}</Text>:<>
        <Btn title={ids.includes(c.coupon_id)?'已选择 · 点击取消':'选择此票券'} disabled={busy||!c.usable||order.status!=='TICKETED'} onPress={()=>setIds(ids.includes(c.coupon_id)?ids.filter(x=>x!==c.coupon_id):[...ids,c.coupon_id])}/>
        {mode==='CHANGE'&&ids.includes(c.coupon_id)&&<TextInput accessibilityLabel={`${c.passenger_name}第${c.leg_index+1}程新日期`} value={dates[c.coupon_id]} placeholder="YYYY-MM-DD" editable={!busy} onChangeText={v=>setDates({...dates,[c.coupon_id]:v})}/>}
      </>}
    </View>)}
    {quote?<View style={screen.card}><Text style={screen.h2}>{mode==='REFUND'?'原路退款金额':'改签补款金额'}</Text>
      <Price minor={mode==='REFUND'?quote.refund_amount_minor:quote.total_due_minor} currency={quote.currency}/>
      <Text style={screen.sub}>手续费</Text><Price minor={mode==='REFUND'?quote.refund_fee_minor:quote.change_fee_minor} currency={quote.currency}/>
      {(quote.changes||[]).map((c:any,i:number)=><Text key={i}>第 {c.leg_index+1} 程：{c.old_departure_date} → {c.new_departure_date}</Text>)}
      <Btn title={quote.status==='PREPARED'?'继续原退款申请':'确认票券及金额并提交'} disabled={busy} onPress={()=>{void act(true)}}/>
      {quote.status!=='PREPARED'&&<Btn title="返回重新选择" disabled={busy} onPress={()=>setQuote(null)}/>}
    </View>:<Btn title="核对票券与费用" disabled={busy||!ids.length} onPress={()=>{void act(false)}}/>}
    <Text style={screen.sub}>当前未连接航空公司实时服务，不可作为实际出行凭证。</Text>
  </ScrollView>;
}
