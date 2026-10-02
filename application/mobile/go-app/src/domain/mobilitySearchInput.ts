// Explicit wall-clock + UTC offset input; independent of device timezone.
export type MobilitySearchDraft = {
  pickup:string; dropoff:string;
  pickupDate:string; pickupTime:string; pickupOffset:string;
  returnDate:string; returnTime:string; returnOffset:string;
};
export type RideSearchPayload = {pickup:string; dropoff:string; pickup_at:string; currency:'CNY'};
export type RentalSearchPayload = {pickup_location:string; return_location:string; pickup_at:string; return_at:string; currency:'CNY'};
function offsetMinutes(value:string):number {
  const m=/^([+-])(\d{2}):(\d{2})$/.exec(value.trim());
  if(!m)throw Error('时区请填写 UTC 偏移，例如 +08:00 或 -05:00。');
  const hours=Number(m[2]),minutes=Number(m[3]),total=(hours*60+minutes)*(m[1]==='-'?-1:1);
  if(minutes>59||total < -720||total > 840)throw Error('时区偏移应在 -12:00 至 +14:00 之间。');
  return total;
}
export function mobilityInstant(date:string,time:string,offset:string):number {
  const d=/^(\d{4})-(\d{2})-(\d{2})$/.exec(date.trim()),t=/^(\d{2}):(\d{2})$/.exec(time.trim());
  if(!d||!t)throw Error('日期请用 YYYY-MM-DD，时间请用 24 小时制 HH:mm。');
  const year=Number(d[1]),month=Number(d[2]),day=Number(d[3]),hour=Number(t[1]),minute=Number(t[2]);
  if(year<1970||month<1||month>12||day<1||day>31||hour>23||minute>59)throw Error('日期或时间无效，请重新填写。');
  const wall=Date.UTC(year,month-1,day,hour,minute),checked=new Date(wall);
  if(checked.getUTCFullYear()!==year||checked.getUTCMonth()!==month-1||checked.getUTCDate()!==day)throw Error('该日期不存在，请检查月份和天数。');
  const instant=wall-offsetMinutes(offset)*60_000;
  if(new Date(instant).getUTCFullYear()>9999)throw Error('日期超出支持范围，请重新填写。');
  return instant;
}
export function mobilityDefaults(now=Date.now(),offset='+08:00'):MobilitySearchDraft {
  if(!Number.isFinite(now))throw Error('无法读取当前时间，请重试。');
  const delta=offsetMinutes(offset)*60_000,pickup=Math.ceil((now+86400000)/60000)*60000;
  const first=new Date(pickup+delta).toISOString(),last=new Date(pickup+3*86400000+delta).toISOString();
  return {pickup:'',dropoff:'',pickupDate:first.slice(0,10),pickupTime:first.slice(11,16),pickupOffset:offset,returnDate:last.slice(0,10),returnTime:last.slice(11,16),returnOffset:offset};
}
function place(value:string,label:string):string {
  const result=value.trim();
  if(!result||result.length>200)throw Error(`请填写${label}（不超过 200 字）。`);
  return result;
}
function futurePickup(d:MobilitySearchDraft,now:number):number {
  if(!Number.isFinite(now))throw Error('无法读取当前时间，请重试。');
  const at=mobilityInstant(d.pickupDate,d.pickupTime,d.pickupOffset);
  if(at<=now)throw Error('上车或取车时间必须晚于当前时间。');
  return at;
}
export function rideSearchInput(d:MobilitySearchDraft,now=Date.now()):RideSearchPayload {
  return {pickup:place(d.pickup,'上车地点'),dropoff:place(d.dropoff,'下车地点'),pickup_at:new Date(futurePickup(d,now)).toISOString(),currency:'CNY'};
}
export function rentalSearchInput(d:MobilitySearchDraft,now=Date.now()):RentalSearchPayload {
  const pickup=futurePickup(d,now),returned=mobilityInstant(d.returnDate,d.returnTime,d.returnOffset);
  if(returned<=pickup)throw Error('还车时间必须晚于取车时间，请同时核对时区。');
  return {pickup_location:place(d.pickup,'取车地点'),return_location:place(d.dropoff,'还车地点'),pickup_at:new Date(pickup).toISOString(),return_at:new Date(returned).toISOString(),currency:'CNY'};
}
