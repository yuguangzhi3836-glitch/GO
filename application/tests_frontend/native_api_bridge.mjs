// Offline API integration driver. Python supplies TestClient responses via pipes.
// No browser, device, external host, or native rendering is involved.
import fs from 'node:fs';
import {createStayCreditActions} from '../mobile/go-app/src/domain/stayCreditActions.ts';
import {bookingIntent} from '../mobile/go-app/src/domain/bookingIntent.ts';
import {createOrderActions,orderRef,readOrder} from '../mobile/go-app/src/domain/orderActions.ts';
function line(){let b=Buffer.alloc(1),s='';while(fs.readSync(0,b,0,1,null)){if(b[0]===10)return JSON.parse(s);s+=b.toString();}throw Error('BRIDGE_EOF');}
const output=x=>fs.writeSync(1,JSON.stringify(x)+'\n');
const request=async(path,init={})=>{output({request:{path,method:init.method||'GET',headers:init.headers||{},body:init.body?JSON.parse(init.body):null}});const r=line();if(r.status>=400)throw Object.assign(Error(JSON.stringify(r.body)),{status:r.status,uncertain:r.status>=500});return r.body;};
try{
 const task=line();let result;
 if(task.action==='create'){const intent=bookingIntent(task.vertical,task.params,task.userId,[task.travelerId],true,true,task.cancellationAcceptedHash??null);result=await request(intent.path,intent.init);}
 else if(task.action==='credit'){const actions=createStayCreditActions(request),q=await actions.quote(task.orderId);result=await actions.convert(task.orderId,q,true);}
 else{
   const ref=orderRef(task.vertical,task.orderId),actions=createOrderActions(request);
   if(task.action==='pay'){const initial=await readOrder(ref,request);result=await actions.pay(ref,initial.order);}
   else{const initial=await actions.refundQuote(ref);result=await actions.refund(ref,initial.quote);}
 }
 output({result});
}catch(error){output({error:String(error)});process.exitCode=1;}
