// Native changes always quote, explicitly confirm, then re-read the same order.
// This is isolated-mode support, not a live payment/provider certification.
import {orderRef,readOrder} from './orderActions.ts';
import type {OrderRef,Request} from './orderActions.ts';
import {changeTerms} from './changeTerms.ts';
export type ChangeFields = Record<string,string>;
const config = {
  HOTEL: {fields:['new_check_in','new_check_out'],base:'/v1/mobile/orders/'},
  FLIGHT: {fields:['new_departure_date'],base:'/v1/flights/orders/'},
  RAIL: {fields:['new_travel_date'],base:'/v1/rail/orders/'},
  ATTRACTION: {fields:['new_visit_date','new_session_time'],base:'/v1/attractions/orders/'},
  RENTAL: {fields:['pickup_at','return_at'],base:'/v1/mobility/rentals/orders/'},
};
export function changeFields(vertical:string):string[] {
  if(!Object.hasOwn(config,vertical))throw Error('CHANGE_NOT_SUPPORTED');
  return [...config[vertical as keyof typeof config].fields];
}
export function validateChangeFields(vertical:string, fields:ChangeFields) {
  const keys=changeFields(vertical),out:ChangeFields={};
  for(const key of keys){
    const value=fields[key];
    if(typeof value!=='string'||value!==value.trim())throw Error('CHANGE_INPUT_INVALID');
    if(key==='new_session_time'){
      if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(value))throw Error('CHANGE_INPUT_INVALID');
    }else{
      const date=value.slice(0,10),stamp=Date.parse(date+'T00:00:00Z');
      if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!Number.isFinite(stamp)||new Date(stamp).toISOString().slice(0,10)!==date)throw Error('CHANGE_INPUT_INVALID');
      if(vertical==='RENTAL'){
        if(!/^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:Z|[+-](?:0\d|1[0-3]):[0-5]\d|[+-]14:00)$/.test(value)||!Number.isFinite(Date.parse(value)))throw Error('CHANGE_INPUT_INVALID');
      }else if(value!==date)throw Error('CHANGE_INPUT_INVALID');
    }
    out[key]=value;
  }
  if(vertical==='HOTEL'&&out.new_check_out<=out.new_check_in)throw Error('CHANGE_INPUT_INVALID');
  if(vertical==='RENTAL'&&Date.parse(out.return_at)<=Date.parse(out.pickup_at))throw Error('CHANGE_INPUT_INVALID');
  return out;
}
function expires(value:unknown) {
  if(typeof value!=='string')return NaN;
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(value)?value:value+'Z');
}
export function changeAmount(vertical:string,q:any) {
  const value=vertical==='HOTEL'?q.amount_due_minor:vertical==='RENTAL'?q.difference_minor:q.total_due_minor;
  if(!Number.isSafeInteger(value)||(vertical!=='RENTAL'&&value<0)||q.currency!=='CNY')throw Error('CHANGE_QUOTE_UNVERIFIED');
  return value;
}
export function createChangeActions(request:Request,current:()=>boolean=()=>true,now:()=>number=Date.now) {
  let revision=0,busy=false,accepted:any=null;
  const check=(r:number)=>{if(!current()||r!==revision)throw Error('CHANGE_CONTEXT_CHANGED');};
  const invalidate=()=>{revision++;accepted=null;};
  async function capability(){
    const c=(await request('/v1/consumer/checkout-capabilities')).data;
    if(c?.simulation_available!==true||c.external_live!==false)throw Error('CHANGE_ISOLATED_CHANNEL_REQUIRED');
  }
  async function quote(ref:OrderRef,fields:ChangeFields){
    if(busy)throw Error('OPERATION_IN_PROGRESS');
    invalidate();const r=revision;check(r);busy=true;
    try{
      orderRef(ref.vertical,ref.orderId);const input=validateChangeFields(ref.vertical,fields);
      const {order}=await readOrder(ref,request);check(r);
      if(!['CONFIRMED','TICKETED'].includes(order.status))throw Error('ORDER_NOT_CHANGEABLE');
      await capability();check(r);
      const c=config[ref.vertical as keyof typeof config];
      const q=(await request(c.base+ref.orderId+(ref.vertical==='RENTAL'?'/change-quotes':'/change-quote'),{method:'POST',body:JSON.stringify(input)})).data;check(r);
      const qid=q?.change_quote_id||q?.quote_id;
      if(q?.order_id!==ref.orderId||typeof qid!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(qid)||!(expires(q.expires_at)>now()))throw Error('CHANGE_QUOTE_UNVERIFIED');
      for(const key of Object.keys(input)){
        const returned=ref.vertical==='RENTAL'?'new_'+key:key;
        if(q[returned]!==input[key])throw Error('CHANGE_QUOTE_UNVERIFIED');
      }
      if(ref.vertical==='HOTEL'&&!/^[0-9a-f]{64}$/.test(q.quote_hash))throw Error('CHANGE_QUOTE_UNVERIFIED');
      changeAmount(ref.vertical,q);
      changeTerms(ref.vertical,q);
      accepted={ref:{...ref},input:{...input},quote:JSON.parse(JSON.stringify(q)),qid,revision:r};
      return {order,quote:JSON.parse(JSON.stringify(q)),input:{...input},simulation:true};
    }finally{busy=false;}
  }
  async function submit(ref:OrderRef,fields:ChangeFields,confirmed:boolean){
    if(busy)throw Error('OPERATION_IN_PROGRESS');
    if(confirmed!==true)throw Error('CHANGE_CONFIRMATION_REQUIRED');
    const a=accepted;
    if(!a||ref.orderId!==a.ref.orderId||ref.vertical!==a.ref.vertical||JSON.stringify(validateChangeFields(ref.vertical,fields))!==JSON.stringify(a.input))throw Error('FRESH_CHANGE_QUOTE_REQUIRED');
    check(a.revision);
    if(!(expires(a.quote.expires_at)>now())){invalidate();throw Error('CHANGE_QUOTE_EXPIRED');}
    busy=true;let submitted=false;
    try{
      await capability();check(a.revision);
      if(!(expires(a.quote.expires_at)>now()))throw Error('CHANGE_QUOTE_EXPIRED');
      const q=a.quote,c=config[ref.vertical as keyof typeof config];
      const body=ref.vertical==='HOTEL'?{change_quote_id:a.qid,quote_hash:q.quote_hash,confirmed:true}:
        ref.vertical==='RENTAL'?{expected_difference_minor:changeAmount(ref.vertical,q),currency:q.currency,mode:'CONTRACT_SIMULATOR'}:undefined;
      const path=c.base+ref.orderId+(ref.vertical==='HOTEL'?'/change':ref.vertical==='RENTAL'?'/changes/'+a.qid:'/execute-change/'+a.qid);
      // Consume consent before sending; timeouts must never trigger an automatic retry.
      accepted=null;submitted=true;let unknown=false;
      try{
        await request(path,{method:'POST',headers:{'Idempotency-Key':`mobile-change:${ref.vertical}:${ref.orderId}:${a.qid}`},body:body?JSON.stringify(body):undefined});check(a.revision);
      }catch(e:any){check(a.revision);if(e?.status&&e.status<500)throw e;unknown=true;}
      const result=await readOrder(ref,request);check(a.revision);
      return {...result,notice:unknown?'CHANGE_RESULT_UNKNOWN':'CHANGE_SUBMITTED_CHECK_ORDER'};
    }finally{busy=false;if(submitted)accepted=null;}
  }
  return {quote,submit,invalidate};
}
