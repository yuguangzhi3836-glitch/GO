import React from 'react';
import {View} from 'react-native';
import {Btn} from './GO';
import {orderRef,payable,refundable} from '../domain/orderActions';
const payment:Record<string,string>={HOTEL:'Payment',FLIGHT:'FlightPayment',RAIL:'RailPayment',RENTAL:'RentalPayment',RIDE:'RidePayment',ATTRACTION:'AttractionPayment'};
const refund:Record<string,string>={HOTEL:'CancelOrder',FLIGHT:'FlightRefund',RAIL:'RailRefund',RENTAL:'RentalCancel',RIDE:'RideCancel',ATTRACTION:'AttractionRefund'};
export default function OrderActions({order,vertical,navigation}:any){
  let ref;try{ref=orderRef(vertical,order?.order_id);}catch{return null;}
  const params={orderId:ref.orderId,vertical:ref.vertical};
  return <View>{payable(order)&&<Btn title="核对原订单并继续支付" onPress={()=>navigation.navigate(payment[ref.vertical],params)}/>}
    {refundable(order)&&<Btn title="核对取消与退款方案" secondary onPress={()=>navigation.navigate(refund[ref.vertical],params)}/>}</View>;
}
