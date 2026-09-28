'use strict';
const audience=new URLSearchParams(location.search).get('audience')==='supplier'?'supplier':'consumer';
const base=audience==='consumer'?'/v1/consumer/privacy':'/bff/privacy';
const message=document.querySelector('#message'),records=document.querySelector('#records'),submit=document.querySelector('#submit');
document.querySelector('#back').href=audience==='consumer'?'/go-app/':'/supplier-console/';
async function call(path,method='GET',body){
 const cookieName=audience==='consumer'?'go_consumer_csrf':'go_csrf';
 const token=document.cookie.split(';').map(s=>s.trim()).find(s=>s.startsWith(cookieName+'='))?.slice(cookieName.length+1);
 const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json',...(token?{'X-CSRF-Token':decodeURIComponent(token)}:{})},body:body?JSON.stringify(body):undefined});
 if(!response.ok)throw Error(response.status===401?'请先登录对应 GO 账号。':response.status===403?'当前账号无此操作权限，请检查登录状态。':'处理未完成，请稍后重试。');
 return (await response.json()).data;
}
const labels={RECEIVED:'已收到，待受理',IN_REVIEW:'核验处理中',COMPLETED:'已处理（见处理说明）',REJECTED:'未予处理（见理由）',RESTRICTED_RETENTION:'依法受限保留',CONTRACT_ACCEPTED:'协议已接受',NOTICE_ACKNOWLEDGED:'隐私告知已阅读',DEFERRED:'未开通 / 未授权'};
async function load(){
 try{
  const data=await call(base);submit.disabled=false;
  message.textContent=data.operational_readiness?'':'当前正式注册的隐私运营条件尚未核验齐备；申请可登记并查看进度。';
  records.textContent=JSON.stringify({注册确认:data.decisions,申请进度:data.requests},(k,v)=>typeof v==='string'&&labels[v]?labels[v]:v,2);
  if(audience==='consumer'){
   const result=await call('/v1/consumer/profile/consents');
   const holder=document.querySelector('#vault');holder.replaceChildren();document.querySelector('#vaultSection').hidden=false;
   for(const item of (Array.isArray(result)?result:result?.items||[])){
    const row=document.createElement('p');row.textContent=String(item.purpose||item.consent_id||'授权')+' '+String(item.status||'');
    if(item.status==='ACTIVE'){
     const button=document.createElement('button');button.textContent='撤回此授权';button.onclick=async()=>{button.disabled=true;try{await call('/v1/consumer/profile/consents/'+encodeURIComponent(item.consent_id),'DELETE');await load()}catch(e){message.textContent=e.message;button.disabled=false}};row.append(button);
    }holder.append(row);
   }
  }
 }catch(e){message.textContent=e.message;submit.disabled=true}
}
submit.onclick=async()=>{submit.disabled=true;try{await call(base+'/requests','POST',{kind:document.querySelector('#kind').value});await load();message.textContent='申请已登记，请在下方查看进度。'}catch(e){message.textContent=e.message;submit.disabled=false}};
load();
