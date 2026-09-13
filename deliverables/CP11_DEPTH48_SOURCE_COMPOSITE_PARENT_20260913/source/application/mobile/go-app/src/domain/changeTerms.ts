// Only server-supplied terms may be presented as the accepted change offer.
export type ChangeTerm = {label:string; value?:string; minor?:number};
export function changeTerms(vertical:string,q:any):ChangeTerm[] {
  const fail=()=>{throw Error('CHANGE_QUOTE_UNVERIFIED');};
  if(!q||q.currency!=='CNY')return fail();
  const money=(key:string,signed=false):number=>{
    const n=q[key];if(!Number.isSafeInteger(n)||(!signed&&n<0))return fail();return n;
  };
  const fact=(key:string):string=>{
    const v=q[key];if(typeof v!=='string'||!v.trim()||v.length>100)return fail();return v;
  };
  const fee=money('change_fee_minor');
  const rows:ChangeTerm[]=[];
  if(vertical==='HOTEL'){
    const deadline=fact('change_valid_until');
    if(fee!==0||q.change_policy!=='GO_HOTEL_FREE_CHANGE_365D_V1'||q.change_validity_days!==365||!Number.isFinite(Date.parse(deadline)))return fail();
    const old=money('old_value_minor'),next=money('new_value_minor'),diff=money('fare_difference_minor'),loss=money('lower_price_difference_minor');
    if(q.lower_price_no_refund!==true||q.lower_price_rule!=='FORFEIT_NO_REFUND_NO_FUTURE_OFFSET'||diff!==Math.max(next-old,0)||loss!==Math.max(old-next,0)||money('amount_due_minor')!==diff+fee)return fail();
    rows.push({label:'原房费价值',minor:old},{label:'新房费',minor:next},{label:'需补房费差额',minor:diff},{label:'降价差额（不退还）',minor:loss},{label:'改期规则',value:'改期免手续费，涨价补差，降价不退差额。'},{label:'最晚入住期限',value:new Date(deadline).toLocaleString()},{label:'有效期',value:'原订单创建日起 365 天，连续改期不顺延。'});
  }else if(vertical==='FLIGHT'||vertical==='RAIL'){
    const diff=money('fare_difference_minor');
    if(money('total_due_minor')!==diff+fee)return fail();
    rows.push({label:vertical==='FLIGHT'?'新航班号':'新车次',value:fact(vertical==='FLIGHT'?'new_flight_number':'new_train_no')});
    if(vertical==='RAIL')rows.push({label:'新席别',value:fact('new_seat_class')});
    rows.push({label:'需补票价差额',minor:diff});
  }else if(vertical==='RENTAL'){
    const old=money('old_amount_minor'),next=money('new_amount_minor'),diff=money('difference_minor',true),rate=money('daily_rate_minor');
    if(!Number.isSafeInteger(q.rental_days)||q.rental_days<1||rate<1||next!==rate*q.rental_days||diff!==next-old||fee!==0||q.refund_to!=='ORIGINAL_PAYMENT_METHOD')return fail();
    rows.push({label:'原租金',minor:old},{label:'新租金',minor:next},{label:'日租金',minor:rate},{label:'计费天数',value:String(q.rental_days)},{label:'差额结算',value:diff<0?'差额退回原支付方式。':'按本次确认金额补款。'});
  }else if(vertical==='ATTRACTION'){
    if(fee!==0||money('total_due_minor')!==0)return fail();
    rows.push({label:'费用说明',value:'本次报价无需补款。'});
  }else return fail();
  if(vertical!=='HOTEL')rows.push({label:'改签手续费',minor:fee});
  return rows;
}
