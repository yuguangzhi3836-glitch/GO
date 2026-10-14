import React,{useCallback,useState}from'react';
import{ActivityIndicator,ScrollView,Text,View}from'react-native';
import{useFocusEffect}from'@react-navigation/native';
import{GO,screen}from'../design';
import{TopBar,Btn,StatusPill}from'../components/GO';
import{api}from'../api/client';

const money=(minor:number|undefined,currency='CNY')=>`${currency} ${((minor||0)/100).toFixed(2)}`;

export default function Wallet({navigation}:any){
  const[d,setD]=useState<any>(null),[ledger,setLedger]=useState<any[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const refresh=useCallback(async()=>{
    setError('');setLoading(true);
    try{
      const[walletResult,ledgerResult]=await Promise.all([
        api('/v1/consumer/wallet'),api('/v1/consumer/wallet/ledger')
      ]);
      setD(walletResult.data);setLedger(ledgerResult.data?.items||[]);
    }
    catch(e:any){setError(e.message||'钱包加载失败');}
    finally{setLoading(false);}
  },[]);
  useFocusEffect(useCallback(()=>{void refresh();},[refresh]));
  const cards=d?.payment_methods||[];
  const ledgerLabel:Record<string,string>={
    HOTEL_PAYMENT_DEBIT:'酒店订单付款',
    HOTEL_PAYMENT_RELEASE:'酒店预订失败，现金退回',
    LOCAL_DEVELOPMENT_CREDIT:'本地开发测试入账'
  };
  return <View style={screen.root}>
    <TopBar title="GO Wallet" onBack={()=>navigation?.goBack?.()}/>
    <ScrollView contentContainerStyle={screen.content}>
      <Text style={screen.h1}>消费者钱包</Text>
      <Text style={screen.sub}>酒店订单使用钱包现金余额支付；返现单独显示，银行卡用于查看已保存的卡片。</Text>
      {loading&&<ActivityIndicator color={GO.navy}/>}
      {!!error&&<View style={screen.card}><Text accessibilityRole="alert" style={screen.sub}>{error}</Text><Btn title="重试" secondary onPress={()=>void refresh()}/></View>}
      {d&&<>
        <View style={[screen.card,{backgroundColor:GO.navy}]}>
          <Text style={{color:'white',opacity:.78}}>现金余额</Text>
          <Text style={{color:'white',fontSize:32,fontWeight:'700',marginTop:8}}>{money(d.cash_balance_minor,d.currency)}</Text>
          <Text style={{color:'white',opacity:.72,marginTop:8}}>酒店付款从此余额扣除</Text>
        </View>
        <View style={screen.card}>
          <Text style={screen.sub}>返现余额</Text>
          <Text style={[screen.h1,{marginTop:8,color:GO.orange}]}>{money(d.cashback_balance_minor,d.currency)}</Text>
          <Text style={[screen.sub,{marginTop:8}]}>返现与现金余额分开展示。</Text>
        </View>
        <View style={screen.card}>
          <View style={screen.row}>
            <Text style={screen.h2}>银行卡</Text>
            <StatusPill text={`${d.bank_card_count||0} 张`} tone="navy"/>
          </View>
          <Text style={[screen.sub,{marginTop:6}]}>已保存银行卡仅展示卡片信息，本次酒店钱包支付不会从银行卡扣款。</Text>
          {!cards.length&&<Text style={[screen.sub,{marginTop:12}]}>暂无已保存的银行卡</Text>}
          {cards.map((card:any)=><View key={card.payment_method_id} style={[screen.row,{marginTop:12}]}>
            <Text style={screen.body}>{card.brand||'银行卡'}{card.last4?` ···· ${card.last4}`:''}</Text>
            {card.is_default&&<StatusPill text="默认卡" tone="green"/>}
          </View>)}
        </View>
        <View style={screen.card}>
          <Text style={screen.h2}>钱包交易记录</Text>
          {!ledger.length&&<Text style={[screen.sub,{marginTop:8}]}>暂无钱包交易记录</Text>}
          {ledger.map((item:any)=><View key={item.wallet_ledger_id} style={{marginTop:14}}>
            <View style={screen.row}>
              <Text style={screen.body}>{ledgerLabel[item.entry_type]||item.entry_type}</Text>
              <Text style={[screen.body,{color:item.amount_minor<0?GO.navy:GO.green,fontWeight:'600'}]}>
                {item.amount_minor<0?'−':'+'}{money(Math.abs(item.amount_minor),item.currency)}
              </Text>
            </View>
            <Text style={screen.sub}>{new Date(item.created_at).toLocaleString('zh-CN')} · 余额 {money(item.balance_after_minor,item.currency)}</Text>
            {!!item.order_id&&<Btn title="查看关联酒店订单" secondary compact onPress={()=>navigation.navigate('OrderDetail',{orderId:item.order_id})}/>}
          </View>)}
        </View>
      </>}
    </ScrollView>
  </View>;
}
