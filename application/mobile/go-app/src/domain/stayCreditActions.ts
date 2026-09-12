import {orderRef,readOrder} from './orderActions.ts';
import type {Request} from './orderActions.ts';
import {requestFingerprint} from './requestFingerprint.ts';

export function validateCreditQuote(orderId:string, currency:string, quote:any, at=Date.now()) {
  if(quote?.order_id!==orderId||quote.currency!==currency||quote.scope!=='PROPERTY_ONLY'||
    !Number.isSafeInteger(quote.credit_value_minor)||quote.credit_value_minor<=0||
    !/^[A-Za-z0-9_-]{1,100}$/.test(quote.quote_id)||!/^[0-9a-f]{64}$/.test(quote.quote_hash)||
    quote.credit_validity_basis!=='ORIGINAL_ORDER_365D_CAP')throw Error('CREDIT_QUOTE_UNVERIFIED');
  const expiry=Date.parse(quote.credit_expires_at), deadline=Date.parse(quote.expires_at), original=Date.parse(quote.credit_original_created_at);
  if(![expiry,deadline,original].every(Number.isFinite)||expiry<=at||deadline<=at||expiry>original+365*86400000)throw Error('CREDIT_QUOTE_EXPIRED_OR_INVALID');
  return Object.freeze({...quote});
}

export function createStayCreditActions(request:Request,current:()=>boolean=()=>true) {
  let busy=false;
  const check=()=>{if(!current())throw Error('SESSION_OR_SCREEN_CHANGED');};
  async function quote(orderId:string) {
    const result=await readOrder(orderRef('HOTEL',orderId),request);check();
    if(result.order.status!=='CONFIRMED')throw Error('CREDIT_ORDER_NOT_AVAILABLE');
    const q=(await request(`/v1/mobile/orders/${orderId}/stay-credit-quote`,{method:'POST'})).data;check();
    return validateCreditQuote(orderId,result.order.currency,q);
  }
  async function convert(orderId:string,accepted:any,consent:boolean) {
    if(busy)throw Error('OPERATION_IN_PROGRESS');
    if(consent!==true)throw Error('CREDIT_CONSENT_REQUIRED');
    const q={...accepted};busy=true;
    try {
      check();const ref=orderRef('HOTEL',orderId),view=await readOrder(ref,request);check();
      if(view.order.status!=='CONFIRMED')throw Error('CREDIT_ORDER_NOT_AVAILABLE');
      validateCreditQuote(orderId,view.order.currency,q);
      let uncertain=false;
      try {
        await request(`/v1/mobile/orders/${orderId}/convert-to-stay-credit`,{method:'POST',
          headers:{'Idempotency-Key':`mobile-credit:${requestFingerprint(orderId+':'+q.quote_id+':'+q.quote_hash)}`},
          body:JSON.stringify({quote_id:q.quote_id,quote_hash:q.quote_hash,confirmed:true})});check();
      }catch(e:any){check();if(e.status&&e.status<500)throw e;uncertain=true;}
      const latest=await readOrder(ref,request);check();
      return {...latest,notice:uncertain?'CREDIT_RESULT_UNKNOWN':'CREDIT_REQUEST_SUBMITTED'};
    } finally {busy=false;}
  }
  return {quote,convert};
}
