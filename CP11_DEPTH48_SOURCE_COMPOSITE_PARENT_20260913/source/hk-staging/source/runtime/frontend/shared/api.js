export class ApiClient{
  constructor(){this.base=''}
  setBase(){/* Production BFF is same-origin by design. */}
  csrf(){const m=document.cookie.match(/(?:^|; )go_csrf=([^;]+)/);return m?decodeURIComponent(m[1]):''}
  async authPolicy(){return this.raw('/bff/auth/policy',{},false)}
  async login(username,password,totp_code=null){await this.raw('/bff/auth/login',{method:'POST',body:{username,password,totp_code}},false);return this.me()}
  async supplierRegistrationTerms(){return this.raw('/bff/auth/supplier/registration-terms',{},false)}
  async supplierRegister(body){await this.raw('/bff/auth/supplier/register',{method:'POST',body},false);return this.me()}
  async startMfaEnrollment(username,password){return this.raw('/bff/auth/mfa/enroll/start',{method:'POST',body:{username,password}},false)}
  async confirmMfaEnrollment(enrollment_token,code){await this.raw('/bff/auth/mfa/enroll/confirm',{method:'POST',body:{enrollment_token,code}},false);return this.me()}
  async refresh(){return this.raw('/bff/auth/refresh',{method:'POST'},false)}
  async me(){return this.request('/bff/auth/me')}
  async logout(){try{await this.request('/bff/auth/logout',{method:'POST'})}catch{} }
  async request(path,opts={}){try{return await this.raw(path,opts,true)}catch(e){if(e.status===401){await this.refresh();return this.raw(path,opts,true)}throw e}}
  async raw(path,opts={},auth=true){
    const headers={'Content-Type':'application/json','X-Request-ID':crypto.randomUUID(),...(opts.headers||{})};
    if(!['GET','HEAD','OPTIONS'].includes((opts.method||'GET').toUpperCase())){const c=this.csrf();if(c)headers['X-CSRF-Token']=c}
    const res=await fetch(this.base+path,{...opts,headers,credentials:'same-origin',body:opts.body===undefined?undefined:JSON.stringify(opts.body)});
    let data={};try{data=await res.json()}catch{}
    if(!res.ok){const e=new Error(data.detail||data.error?.code||`HTTP_${res.status}`);e.status=res.status;e.payload=data;throw e}return data
  }
}
export const api=new ApiClient();
export const money=v=>v==null?'—':new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY',maximumFractionDigits:2}).format(Number(v)/100);
export const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
export const statusClass=s=>/COMPLETED|CONFIRMED|ACTIVE|CLEARED|HEALTHY|APPROVED|RECOMMENDED/i.test(s||'')?'ok':/FAILED|DEAD|UNHEALTHY|REJECTED|NEGATIVE|SUSPENDED/i.test(s||'')?'bad':/PENDING|REVIEW|DEGRADED|PROCESSING|OBSERVATION/i.test(s||'')?'warn':'';
export const unwrap=r=>r?.data??r;
