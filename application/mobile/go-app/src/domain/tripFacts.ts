// Read models only. No checkout, external execution, or projected-URL navigation.
const routes: Record<string, string> = {
  HOTEL_CATALOG: 'OrderDetail', HOTEL_DIRECT: 'DirectReservationDetail', FLIGHT: 'FlightTripDetail', RAIL: 'RailTripDetail',
  RIDE: 'MobilityTripDetail', RENTAL: 'MobilityTripDetail', ATTRACTION: 'AttractionTripDetail',
};
export function cashTripLines(c:any):string[] {
  if(!c)return [];
  const states:Record<string,string>={AUTH_PENDING:'正在保留补款',READY:'申请已保存',SUPPLIER_PENDING:'酒店处理中',UNKNOWN_SUPPLIER:'正在核实酒店结果',CAPTURE_PENDING:'酒店已确认改期，补款待完成',REFUND_PENDING:'取消已确认，退款处理中',REJECTED_RELEASE_PENDING:'正在释放补款',REJECTED:'改期未获确认，原行程保留',PAYMENT_DECLINED:'补款未获授权，原行程保留',COMPLETED:'处理完成'};
  const lines=[`入住：${c.check_in} → ${c.check_out}`,`退改进度：${states[c.state]||'正在核对'}`];
  if(c.action==='CHANGE'&&!['COMPLETED','REJECTED','PAYMENT_DECLINED'].includes(c.state))lines.push(`申请日期：${c.requested_check_in} → ${c.requested_check_out}`);
  for(const [label,key]of [['本次改期已补款','amount_paid_minor'],['累计实付（含补款）','gross_paid_minor'],['累计已退','refunded_minor'],['当前净实付','net_paid_minor']])
    if(Number.isSafeInteger(c[key])&&(key!=='amount_paid_minor'||c.action==='CHANGE'))lines.push(`${label}：${c.currency} ${(c[key]/100).toFixed(2)}`);
  return lines;
}
export function tripRoute(item: any) {
  const n = item?.navigation;
  if (!n || !Object.hasOwn(routes, n.kind) || typeof n.order_id !== 'string' ||
      !/^[A-Za-z0-9_-]{1,100}$/.test(n.order_id) || n.order_id !== item.order_id ||
      item.vertical !== (['HOTEL_CATALOG','HOTEL_DIRECT'].includes(n.kind) ? 'HOTEL' : n.kind)) return null;
  return {screen: routes[n.kind], params: {orderId: n.order_id, vertical: item.vertical}};
}
export async function loadDirectReservation(id:string,request:(path:string)=>Promise<any>){
  if(typeof id!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(id))throw Error('RESERVATION_ID_REQUIRED');
  const data=(await request('/v1/direct/reservations/'+id)).data;
  if(data?.reservation?.hosted_reservation_id!==id)throw Error('RESERVATION_IDENTITY_MISMATCH');
  // Ignore projected links, credentials and unrelated events. The owner check is server-side.
  const r=data.reservation;
  return {id,checkIn:r.check_in,checkOut:r.check_out,amount:r.amount_minor,currency:r.currency,
    state:r.reservation_state||'UNKNOWN',paymentState:r.payment_state||'UNKNOWN',
    events:(Array.isArray(data.events)?data.events:[]).filter((e:any)=>e.hosted_reservation_id===id).map((e:any)=>({id:e.hosted_event_id,type:e.event_type,at:e.occurred_at}))};
}
export function httpsLink(value: unknown): string | null {
  if (typeof value !== 'string' || /[\s\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}
const checkinStates = new Set(['CHECK_IN_NOT_OPEN','CHECK_IN_OPEN','CHECKED_IN','BOARDING_PASS_AVAILABLE']);
export function flightCells(order: any, result: any, now = Date.now()) {
  const belongs = result?.flight_order_id === order.order_id;
  return (order.itinerary || []).flatMap((leg: any, legIndex: number) =>
    (order.passengers || []).map((person: any, passengerIndex: number) => {
      const matches = belongs && Array.isArray(result.items) ? result.items.filter((x: any) =>
        x.leg_index === legIndex && x.passenger_index === passengerIndex) : [];
      const fact = matches.length === 1 ? matches[0] : null;
      const fresh = fact && typeof fact.fact_id === 'string' && fact.fact_id.length > 0 &&
        Number.isFinite(fact.observed_ms) && Number.isFinite(fact.expires_ms) &&
        fact.observed_ms <= now && fact.expires_ms > now;
      const state = fresh && checkinStates.has(fact.state) ? fact.state : 'CHECK_IN_UNVERIFIED';
      return {legIndex, passengerIndex, leg, person, state,
        officialUrl: state !== 'CHECK_IN_UNVERIFIED' ? httpsLink(fact.official_check_in_url) : null,
        passUrl: state === 'BOARDING_PASS_AVAILABLE' ? httpsLink(fact.boarding_pass_reference) : null};
    }));
}
export async function loadMobility(id: string, request: (path: string) => Promise<any>) {
  if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(id)) throw Error('ORDER_ID_REQUIRED');
  const order = (await request(`/v1/mobility/orders/${id}`)).data;
  if (order?.order_id !== id || !['RIDE','RENTAL'].includes(order.vertical)) throw Error('ORDER_IDENTITY_MISMATCH');
  if (order.vertical === 'RENTAL') return {order, tracking: null, trackingError: ''};
  try {
    const tracking = (await request(`/v1/mobility/rides/orders/${id}/flight-tracking`)).data;
    if (tracking?.order_id !== id) throw Error('TRACKING_IDENTITY_MISMATCH');
    return {order, tracking, trackingError: ''};
  } catch { return {order, tracking: null, trackingError: '航班追踪暂不可用，请以订单已确认安排为准。'}; }
}
