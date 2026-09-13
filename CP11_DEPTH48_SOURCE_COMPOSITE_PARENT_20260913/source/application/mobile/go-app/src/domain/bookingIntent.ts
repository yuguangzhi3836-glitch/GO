import type {Vertical} from './orderActions';
import {requestFingerprint} from './requestFingerprint.ts';
const id=(v:any)=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(v);
export function bookingIntent(vertical:Vertical, params:any, userId:string, travelers:string[], consent:boolean, fareConfirmed=false) {
  const p=params?.prebook,offer=params?.offer||params?.x||{},search=params?.search||{};
  if(!id(userId))throw Error('CONSUMER_IDENTITY_REQUIRED');
  const usesPrebook=['HOTEL','FLIGHT','RAIL','ATTRACTION'].includes(vertical);
  const reference=usesPrebook?p?.prebook_id:offer.offer_id;
  if(!id(reference))throw Error('FRESH_QUOTE_REQUIRED');
  if(!consent||!travelers.length||travelers.some(t=>!id(t))||new Set(travelers).size!==travelers.length)throw Error('BOOKING_TRAVELER_CONSENT_REQUIRED');
  let path='',body:any;
  if(vertical==='HOTEL'){
    if(travelers.length!==1)throw Error('HOTEL_ONE_PRIMARY_TRAVELER_REQUIRED');
    if(!fareConfirmed||typeof p.fare_rule?.offer_rule_hash!=='string'||!/^[a-f0-9]{64}$/.test(p.fare_rule.offer_rule_hash))throw Error('HOTEL_FARE_CONSENT_REQUIRED');
    path='/v1/consumer/orders';body={prebook_id:reference,traveler_id:travelers[0],expected_fare_rule_hash:p.fare_rule.offer_rule_hash,fare_confirmed:true};
  }
  else if(vertical==='FLIGHT'||vertical==='RAIL'){path=vertical==='FLIGHT'?'/v1/flights/orders':'/v1/rail/orders';body={prebook_id:reference,traveler_ids:[...travelers]};}
  else if(vertical==='ATTRACTION'){
    const quantity=params.quantity??p.quantity;
    if(!Number.isSafeInteger(quantity)||quantity<1||quantity>100||travelers.length!==quantity||!id(offer.offer_id)||!offer.visit_date)throw Error('ATTRACTION_PARTY_OR_QUOTE_MISMATCH');
    path='/v1/attractions/orders';body={prebook_id:reference,offer_id:offer.offer_id,visit_date:offer.visit_date,session_time:offer.session_time??null,quantity,currency:offer.currency||p.currency,traveler_ids:[...travelers]};
  } else if(vertical==='RIDE'||vertical==='RENTAL'){
    const fields=vertical==='RIDE'?['pickup','dropoff','pickup_at']:['pickup_location','return_location','pickup_at','return_at'];
    if(fields.some(f=>typeof search[f]!=='string'||!search[f].trim()))throw Error('MOBILITY_SEARCH_DETAILS_REQUIRED');
    body={offer_id:reference,currency:offer.currency||search.currency,traveler_ids:[...travelers]};
    for(const f of fields)body[f]=search[f];
    path=vertical==='RIDE'?'/v1/mobility/rides/orders':'/v1/mobility/rentals/orders';
    // Flight tracking or a free-wait promise requires its own explicit setup.
  }else throw Error('VERTICAL_NOT_SUPPORTED');
  const key=`native-create:${vertical}:${requestFingerprint(JSON.stringify({userId,body}))}`;
  if(key.length>160)throw Error('BOOKING_REFERENCE_TOO_LONG');
  return {path,init:{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)}};
}
