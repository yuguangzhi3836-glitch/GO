function requestId(){
  if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const h=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
export class ApiClient{
  constructor(){this.base='';this.refreshPending=null;this.expectedActor=null;this.onSessionChanged=null}
  setBase(){/* Production BFF is same-origin by design. */}
  csrf(){const m=document.cookie.match(/(?:^|; )go_csrf=([^;]+)/);return m?decodeURIComponent(m[1]):''}
  async authPolicy(){return this.raw('/bff/auth/policy',{},false)}
  async login(username,password,totp_code=null){await this.raw('/bff/auth/login',{method:'POST',body:{username,password,totp_code,expected_actor_type:this.expectedActor}},false);return this.me()}
  async supplierRegistrationTerms(){return this.raw('/bff/auth/supplier/registration-terms',{},false)}
  async supplierRegister(body){await this.raw('/bff/auth/supplier/register',{method:'POST',body},false);return this.me()}
  async startMfaEnrollment(username,password){return this.raw('/bff/auth/mfa/enroll/start',{method:'POST',body:{username,password}},false)}
  async confirmMfaEnrollment(enrollment_token,code){await this.raw('/bff/auth/mfa/enroll/confirm',{method:'POST',body:{enrollment_token,code}},false);return this.me()}
  async refresh(){this.refreshPending ||= this.raw('/bff/auth/refresh',{method:'POST'},false).finally(()=>{this.refreshPending=null});return this.refreshPending}
  async me(){return this.request('/bff/auth/me')}
  async logout(){return this.request('/bff/auth/logout',{method:'POST'})}
  async request(path,opts={}){
    const csrfAtStart=this.csrf();
    try{return await this.raw(path,opts,true)}catch(e){
      if(e.status!==401||!csrfAtStart)throw e;
      if(this.csrf()===csrfAtStart)await this.refresh();
      if(!['GET','HEAD','OPTIONS'].includes((opts.method||'GET').toUpperCase())&&path!=='/bff/auth/logout'&&!opts.headers?.['Idempotency-Key'])throw new Error('登录已续期，请核对当前状态后重试。');
      return this.raw(path,opts,true);
    }
  }
  async raw(path,opts={},auth=true){
    const headers={'Content-Type':'application/json','X-Request-ID':requestId(),...(opts.headers||{}),'X-GO-Session':'console'};
    if(this.expectedActor)headers['X-GO-Actor']=this.expectedActor;
    if(!['GET','HEAD','OPTIONS'].includes((opts.method||'GET').toUpperCase())){const c=this.csrf();if(c)headers['X-CSRF-Token']=c}
    const res=await fetch(this.base+path,{...opts,headers,credentials:'same-origin',body:opts.body===undefined?undefined:JSON.stringify(opts.body)});
    let data={};try{data=await res.json()}catch{}
    if(!res.ok){const e=new Error(data.detail||data.error?.code||`HTTP_${res.status}`);e.status=res.status;e.payload=data;if(data.detail==='ACTOR_CONTEXT_CHANGED')this.onSessionChanged?.();throw e}return data
  }
}
export const api=new ApiClient();
export const money=v=>v==null?'—':new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY',maximumFractionDigits:2}).format(Number(v)/100);
export const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
export const statusClass=s=>/COMPLETED|CONFIRMED|ACTIVE|CLEARED|HEALTHY|APPROVED|RECOMMENDED/i.test(s||'')?'ok':/FAILED|DEAD|UNHEALTHY|REJECTED|NEGATIVE|SUSPENDED/i.test(s||'')?'bad':/PENDING|REVIEW|DEGRADED|PROCESSING|OBSERVATION/i.test(s||'')?'warn':'';
export const unwrap=r=>r?.data??r;
