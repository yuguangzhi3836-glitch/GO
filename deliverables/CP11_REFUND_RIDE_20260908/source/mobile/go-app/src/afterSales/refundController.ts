export type RefundVertical = 'RAIL' | 'ATTRACTION' | 'RIDE';
type Api = (path:string,init?:RequestInit)=>Promise<any>;
export type RefundView = {phase:string;quote?:any;progress?:any;message?:string};
const routes = {RAIL:'rail',ATTRACTION:'attractions',RIDE:'mobility'};
export function createRefundController(api:Api,key:()=>string,vertical:RefundVertical,orderId:string){
  const base=`/v1/${routes[vertical]}/orders/${encodeURIComponent(orderId||'')}`;
  let view:RefundView={phase:'LOADING'},requestKey='',busy=false;
  const listeners=new Set<(v:RefundView)=>void>();
  function set(value:RefundView){view=value;for(const listener of listeners)listener({...value});return view}
  async function load(){
    if(!orderId)return set({phase:'BLOCKED',message:'缺少订单，请从 GO Trips 重新打开。'});
    try{
      const order=(await api(base)).data;
      if(order.order_id!==orderId)throw Error('ORDER_IDENTITY_INVALID');
      if(['REFUND_PENDING','REFUNDED'].includes(order.status)){
        const progress=(await api(base+'/refund-progress')).data;
        if(progress.order_id!==orderId)throw Error('REFUND_IDENTITY_INVALID');
        if(progress.status==='COMPLETED'&&order.status==='REFUNDED')return set({phase:'COMPLETE',progress});
        if(progress.status==='PENDING'&&order.status==='REFUND_PENDING')return set({phase:'PENDING',progress});
        return set({phase:'BLOCKED',message:'订单与退款进度需要核对，请联系订单支持。'});
      }
      if(order.status!==(vertical==='RAIL'?'TICKETED':'CONFIRMED'))return set({phase:'BLOCKED',message:'当前订单状态不支持退款。'});
      const quote=(await api(base+'/refund-quote')).data;
      if(quote.refundable===false||quote.refund_amount_minor===0)return set({phase:'BLOCKED',quote,message:'此方案当前不可退款。'});
      if(quote.order_id!==orderId||!/^[0-9a-f]{64}$/.test(quote.quote_hash||'')||!Number.isSafeInteger(quote.refund_amount_minor)||quote.refund_amount_minor<=0)throw Error('REFUND_QUOTE_INVALID');
      if(view.quote?.quote_hash!==quote.quote_hash||!requestKey)requestKey=key();
      return set({phase:'QUOTE',quote});
    }catch{return set({phase:'UNKNOWN',message:'暂时无法核实处理结果，请重新查询。'})}
  }
  async function run(recover:boolean){
    if(busy||view.phase!==(recover?'PENDING':'QUOTE'))return view;
    busy=true;
    const quoted=view.quote,originalKey=requestKey||key();
    set({...view,phase:'BUSY'});
    let failure='';
    try{
      const options:RequestInit={method:'POST',headers:{'Idempotency-Key':originalKey}};
      if(!recover)options.body=JSON.stringify({expected_quote_hash:quoted.quote_hash});
      await api(base+(recover?'/refund-progress/reconcile':vertical==='RIDE'?'/cancel':'/refund'),options);
    }catch(e:any){
      failure=String(e.message).includes('REFUND_QUOTE_CHANGED')?'方案已变化，请重新核对金额后确认。':'申请结果需要核对，请查看订单的最新进度。';
    }
    // A success screen is never inferred from navigation or a lost response.
    // Only the independently loaded order and operation establish completion.
    await load();busy=false;
    if(failure&&view.phase!=='COMPLETE')set({...view,message:failure});
    return view;
  }
  return {load,submit:()=>run(false),recover:()=>run(true),get:()=>({...view}),
    subscribe(listener:(v:RefundView)=>void){listeners.add(listener);listener({...view});return ()=>{listeners.delete(listener)}}};
}
