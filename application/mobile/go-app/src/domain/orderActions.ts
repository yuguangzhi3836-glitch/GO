// One owner-checked canonical order per interaction. Never follow projected URLs.
import {requestFingerprint} from './requestFingerprint.ts';
export type Vertical = 'HOTEL'|'FLIGHT'|'RAIL'|'RENTAL'|'RIDE'|'ATTRACTION';
export type OrderRef = {vertical: Vertical; orderId: string};
export type Request = (path: string, init?: RequestInit) => Promise<any>;
const endpoints: Record<Vertical,string> = {HOTEL:'/v1/consumer/orders/',FLIGHT:'/v1/flights/orders/',RAIL:'/v1/rail/orders/',RENTAL:'/v1/mobility/orders/',RIDE:'/v1/mobility/orders/',ATTRACTION:'/v1/attractions/orders/'};
const screens: Record<Vertical,string> = {HOTEL:'OrderDetail',FLIGHT:'FlightTripDetail',RAIL:'RailTripDetail',RENTAL:'MobilityTripDetail',RIDE:'MobilityTripDetail',ATTRACTION:'AttractionTripDetail'};
export function orderRef(vertical: string, orderId: unknown): OrderRef {
  if(!Object.hasOwn(endpoints,vertical)||typeof orderId!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(orderId))throw Error('ORDER_REFERENCE_INVALID');
  return {vertical:vertical as Vertical,orderId};
}
export function detailTarget(ref: OrderRef) { orderRef(ref.vertical,ref.orderId);return {screen:screens[ref.vertical],params:{orderId:ref.orderId,vertical:ref.vertical}}; }
export async function readOrder(ref: OrderRef, request: Request) {
  orderRef(ref.vertical,ref.orderId);
  const data=(await request(endpoints[ref.vertical]+ref.orderId+(ref.vertical==='HOTEL'?'/detail':''))).data;
  const order=ref.vertical==='HOTEL'?data?.order:data;
  if(order?.order_id!==ref.orderId||(order.vertical&&order.vertical!==ref.vertical))throw Error('ORDER_IDENTITY_MISMATCH');
  return {data,order};
}
export function payable(order: any) { return ['PAYMENT_PENDING','PAYMENT_AUTHORIZED'].includes(order?.status); }
export function refundable(order: any) { return ['CONFIRMED','TICKETED'].includes(order?.status); }
function amount(order: any) {
  if(!Number.isSafeInteger(order?.total_amount_minor)||order.total_amount_minor<=0||order.currency!=='CNY')throw Error('ORDER_AMOUNT_UNAVAILABLE');
  return {amount:order.total_amount_minor,currency:order.currency};
}
export async function checkoutView(ref: OrderRef, request: Request) {
  const result=await readOrder(ref,request);
  const capability=(await request('/v1/consumer/checkout-capabilities')).data;
  return {...result,simulation:capability?.simulation_available===true&&capability?.external_live===false};
}
export function createOrderActions(request: Request, current: ()=>boolean = ()=>true) {
  let busy=false;
  const check=()=>{if(!current())throw Error('SESSION_OR_SCREEN_CHANGED');};
  async function exclusive<T>(run:()=>Promise<T>) {
    if(busy)throw Error('OPERATION_IN_PROGRESS');busy=true;
    try{check();return await run();}finally{busy=false;}
  }
  async function pay(ref:OrderRef, accepted:any) {
    return exclusive(async()=>{
      const old=amount(accepted),view=await checkoutView(ref,request);check();
      if(accepted.order_id!==ref.orderId)throw Error('ORDER_IDENTITY_MISMATCH');
      if(!payable(view.order))return {...view,notice:'ORDER_STATE_UPDATED'};
      if(!view.simulation)throw Error('PAYMENT_CHANNEL_NOT_READY');
      const fresh=amount(view.order);
      if(fresh.amount!==old.amount||fresh.currency!==old.currency)throw Error('ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED');
      let uncertain=false;
      try {
        const response=await request(`/v1/consumer/checkout/${ref.vertical}/${ref.orderId}`,{method:'POST',
          headers:{'Idempotency-Key':`mobile-pay:${ref.vertical}:${ref.orderId}:${fresh.amount}:${fresh.currency}`},
          body:JSON.stringify({mode:'CONTRACT_SIMULATOR',expected_amount_minor:fresh.amount,currency:fresh.currency})});check();
        if(response.data?.order_id!==ref.orderId||response.data?.external_live!==false)throw Error('PAYMENT_RESPONSE_UNVERIFIED');
      }catch(error:any){check();if(error?.status&&error.status<500)throw error;uncertain=true;}
      // A request outcome is not an order outcome; always re-read the same order.
      const latest=await readOrder(ref,request);check();
      return {...latest,simulation:true,notice:uncertain?'PAYMENT_RESULT_UNKNOWN':'ORDER_STATE_UPDATED'};
    });
  }
  function quotePath(ref:OrderRef) {return ref.vertical==='HOTEL'?`/v1/mobile/orders/${ref.orderId}/cancellation-quote`:endpoints[ref.vertical]+ref.orderId+'/refund-quote';}
  async function refundQuote(ref:OrderRef) {
    const result=await readOrder(ref,request);check();
    if(!refundable(result.order))throw Error('ORDER_NOT_REFUNDABLE');
    const q=(await request(quotePath(ref),ref.vertical==='HOTEL'?{method:'POST'}:{})).data;check();
    const fee=q?.refund_fee_minor??q?.cancellation_fee_minor??q?.fee_minor;
    if((q?.order_id&&q.order_id!==ref.orderId)||!Number.isSafeInteger(q?.refund_amount_minor)||q.refund_amount_minor<0||!Number.isSafeInteger(fee)||fee<0||q.currency!==result.order.currency)throw Error('REFUND_QUOTE_UNVERIFIED');
    return {...result,quote:q};
  }
  const terms=(q:any)=>JSON.stringify([q.refund_amount_minor,q.refund_fee_minor??null,q.cancellation_fee_minor??null,q.fee_minor??null,q.currency??null,q.refundable??null]);
  async function refund(ref:OrderRef, accepted:any) {
    accepted={...accepted};
    return exclusive(async()=>{
      let view;
      if(ref.vertical==='HOTEL'){
        const id=accepted.cancellation_quote_id||accepted.quote_id;
        if(accepted.order_id!==ref.orderId||typeof id!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(id)||!/^[0-9a-f]{64}$/.test(accepted.quote_hash))throw Error('REFUND_QUOTE_UNVERIFIED');
        const result=await readOrder(ref,request);check();
        if(!refundable(result.order))throw Error('ORDER_NOT_REFUNDABLE');
        const q=(await request(`/v1/mobile/orders/${ref.orderId}/cancellation-quotes/${id}`)).data;check();
        // Hotel quote creation has a new identity each time. Re-read the accepted
        // immutable quote and let the server recheck current facts under its lock.
        if(q?.order_id!==ref.orderId||(q.cancellation_quote_id||q.quote_id)!==id||q.quote_hash!==accepted.quote_hash||
          !Number.isSafeInteger(q.refund_amount_minor)||q.refund_amount_minor<0||!Number.isSafeInteger(q.cancellation_fee_minor)||q.cancellation_fee_minor<0||
          q.currency!==result.order.currency||q.expires_at!==accepted.expires_at||!Number.isFinite(Date.parse(q.expires_at))||Date.parse(q.expires_at)<=Date.now())throw Error('REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED');
        view={...result,quote:q};
      }else{view=await refundQuote(ref);check();}
      if(terms(view.quote)!==terms(accepted))throw Error('REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED');
      const bound=ref.vertical!=='HOTEL';
      if(bound&&(!/^[0-9a-f]{64}$/.test(accepted?.quote_hash)||accepted.quote_hash!==view.quote.quote_hash))throw Error('REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED');
      if(view.quote.refundable===false)throw Error('ORDER_NOT_REFUNDABLE');
      const q=view.quote;
      let body: string|undefined;
      if(ref.vertical==='HOTEL'){
        if(typeof q.quote_hash!=='string'||!q.quote_hash||!(q.cancellation_quote_id||q.quote_id))throw Error('REFUND_QUOTE_UNVERIFIED');
        body=JSON.stringify({cancellation_quote_id:q.cancellation_quote_id||q.quote_id,quote_hash:q.quote_hash,confirmed:true});
      }
      if(bound)body=JSON.stringify({quote_hash:accepted.quote_hash,confirmed:true});
      const path=ref.vertical==='HOTEL'?`/v1/mobile/orders/${ref.orderId}/cancel`:endpoints[ref.vertical]+ref.orderId+(bound?'/refund-confirmed':['RIDE','RENTAL'].includes(ref.vertical)?'/cancel':'/refund');
      let uncertain=false;
      const key=`mobile-refund:${ref.vertical}:${requestFingerprint(JSON.stringify({orderId:ref.orderId,quote:q.quote_hash||terms(q)}))}`;
      try{await request(path,{method:'POST',headers:{'Idempotency-Key':key},body});check();}
      catch(error:any){check();if(error?.status&&error.status<500)throw error;uncertain=true;}
      const latest=await readOrder(ref,request);check();
      return {...latest,notice:uncertain?'REFUND_RESULT_UNKNOWN':'REFUND_SUBMITTED_CHECK_ORDER'};
    });
  }
  return {pay,refundQuote,refund};
}
