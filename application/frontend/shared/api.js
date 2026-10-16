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
  // One challenge per channel; the sign-up form issues both, then spends both.
  async registrationChallenge(body){return this.raw('/v1/registration/challenges',{method:'POST',body},false)}
  async recoveryChallenge(body){return this.raw('/bff/auth/recovery/challenge',{method:'POST',body},false)}
  async recoveryUsername(body){return this.raw('/bff/auth/recovery/username',{method:'POST',body},false)}
  async recoveryPassword(body){return this.raw('/bff/auth/recovery/password',{method:'POST',body},false)}
  async supplierRegister(body){const registration=unwrap(await this.raw('/bff/auth/supplier/register',{method:'POST',body},false));let profile=null;try{profile=unwrap(await this.me())}catch{}return {data:{...profile,registration}}}
  async supplierOnboarding(){return this.request('/bff/supplier/onboarding')}
  async supplierLegalEntity(){return this.request('/bff/supplier/legal-entity')}
  async saveSupplierLegalEntity(body){return this.request('/bff/supplier/legal-entity',{method:'PUT',body})}
  async supplierDocuments(scope=null){return this.request('/bff/supplier/legal-entity/documents'+(scope?'?scope='+encodeURIComponent(scope):''))}
  async supplierDocumentHistory(documentType,scope=null){return this.request('/bff/supplier/legal-entity/document-history?document_type='+encodeURIComponent(documentType)+(scope?'&scope='+encodeURIComponent(scope):''))}
  // Hotel claim: search, read the saved claim, save it. The hotel id is an opaque
  // option value produced by search; no screen ever asks a human to type one.
  async hotelSearch(q,city=null,limit=10){const p=new URLSearchParams();if(q)p.set('q',q);if(city)p.set('city',city);p.set('limit',String(limit));return this.request('/bff/supplier/hotel/search?'+p.toString())}
  async supplierHotelClaim(){return this.request('/bff/supplier/hotel/claim')}
  async saveSupplierHotelClaim(body){return this.request('/bff/supplier/hotel/claim',{method:'PUT',body})}
  // Raw octet-stream body: the browser sends the file bytes verbatim, so a 10 MB
  // licence is never inflated into base64, and the runtime image needs no
  // multipart parser. Metadata rides in the query string and one header; the
  // filename is percent-encoded because headers are latin-1 on the wire.
  async uploadSupplierDocument(fields,file){
    const q=new URLSearchParams();
    for(const [k,v] of Object.entries(fields||{})){if(v!==null&&v!==undefined&&v!=='')q.set(k,String(v))}
    return this.uploadRaw('/bff/supplier/legal-entity/documents'+(q.toString()?'?'+q.toString():''),file)
  }
  async uploadRaw(path,file){
    const csrfAtStart=this.csrf();
    const send=async()=>{const headers={'X-Request-ID':requestId(),'X-GO-Session':'console',
        'X-Document-Filename':encodeURIComponent(file.name||'document')};
      if(file.type)headers['Content-Type']=file.type;
      if(this.expectedActor)headers['X-GO-Actor']=this.expectedActor;
      const c=this.csrf();if(c)headers['X-CSRF-Token']=c;
      const res=await fetch(this.base+path,{method:'POST',headers,credentials:'same-origin',body:file});
      let data={};try{data=await res.json()}catch{}
      if(!res.ok){const e=new Error(data.detail||data.error?.code||`HTTP_${res.status}`);e.status=res.status;e.payload=data;if(data.detail==='ACTOR_CONTEXT_CHANGED')this.onSessionChanged?.();throw e}
      return data};
    try{return await send()}catch(e){
      if(e.status!==401||!csrfAtStart)throw e;
      // A 401 may be an expired access token: renew and retry the upload once.
      if(this.csrf()===csrfAtStart)await this.refresh();
      return send();
    }
  }
  // Applicant private evidence is image OR PDF, so this cannot reuse requestBlob
  // (which deliberately accepts only public image types).
  async supplierDocumentBlob(documentId,disposition='attachment'){
    const csrfAtStart=this.csrf();
    const send=async()=>{const headers={'X-Request-ID':requestId(),'X-GO-Session':'console'};
      if(this.expectedActor)headers['X-GO-Actor']=this.expectedActor;
      const res=await fetch(this.base+`/bff/supplier/legal-entity/documents/${encodeURIComponent(documentId)}/content?disposition=${encodeURIComponent(disposition)}`,{headers,credentials:'same-origin'});
      if(res.ok){const type=res.headers.get('Content-Type')||'';
        if(!/^(application\/pdf|image\/(jpeg|png))(?:;|$)/i.test(type))throw new Error('DOCUMENT_TYPE_UNSUPPORTED');
        return {blob:await res.blob(),type}}
      let data={};try{data=await res.json()}catch{}
      const e=new Error(data.detail||`HTTP_${res.status}`);e.status=res.status;throw e};
    try{return await send()}catch(e){if(e.status!==401||!csrfAtStart)throw e;
      if(this.csrf()===csrfAtStart)await this.refresh();return send()}
  }
  async saveSupplierOnboardingProfile(body){return this.request('/bff/supplier/onboarding/profile',{method:'PUT',body})}
  async submitSupplierOnboardingProfile(){return this.request('/bff/supplier/onboarding/profile/submit',{method:'POST',body:{}})}
  // The contract step (Batch 6). Reading the template is a blob fetch because the
  // browser has to *display* the PDF the applicant is agreeing to; the sha256 in the
  // state call is the hash of exactly these bytes, and it is sent back on confirm.
  async supplierContract(){return this.request('/bff/supplier/onboarding/contract')}
  async confirmSupplierContract(body){return this.request('/bff/supplier/onboarding/contract/confirm',{method:'POST',body})}
  async supplierContractTemplateBlob(disposition='inline'){
    const csrfAtStart=this.csrf();
    const send=async()=>{const headers={'X-Request-ID':requestId(),'X-GO-Session':'console'};
      if(this.expectedActor)headers['X-GO-Actor']=this.expectedActor;
      const res=await fetch(this.base+`/bff/supplier/onboarding/contract/template?disposition=${encodeURIComponent(disposition)}`,{headers,credentials:'same-origin'});
      if(res.ok){const type=res.headers.get('Content-Type')||'';
        if(!/^application\/pdf(?:;|$)/i.test(type))throw new Error('CONTRACT_TEMPLATE_UNAVAILABLE');
        return {blob:await res.blob(),type}}
      let data={};try{data=await res.json()}catch{}
      const e=new Error(data.detail||`HTTP_${res.status}`);e.status=res.status;throw e};
    try{return await send()}catch(e){if(e.status!==401||!csrfAtStart)throw e;
      if(this.csrf()===csrfAtStart)await this.refresh();return send()}
  }
  async supplierMyHotel(){return this.request('/bff/supplier/my-hotel')}
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
  async requestBlob(path){return this.request(path,{responseType:'blob'})}
  async raw(path,opts={},auth=true){
    const headers={'Content-Type':'application/json','X-Request-ID':requestId(),...(opts.headers||{}),'X-GO-Session':'console'};
    if(this.expectedActor)headers['X-GO-Actor']=this.expectedActor;
    if(!['GET','HEAD','OPTIONS'].includes((opts.method||'GET').toUpperCase())){const c=this.csrf();if(c)headers['X-CSRF-Token']=c}
    const {responseType,...fetchOpts}=opts;
    const res=await fetch(this.base+path,{...fetchOpts,headers,credentials:'same-origin',body:opts.body===undefined?undefined:JSON.stringify(opts.body)});
    if(res.ok&&responseType==='blob'){if(!/^image\/(jpeg|png|webp)(?:;|$)/i.test(res.headers.get('Content-Type')||''))throw new Error('MEDIA_TYPE_UNSUPPORTED');return res.blob()}
    let data={};try{data=await res.json()}catch{}
    if(!res.ok){const e=new Error(data.detail||data.error?.code||`HTTP_${res.status}`);e.status=res.status;e.payload=data;if(data.detail==='ACTOR_CONTEXT_CHANGED')this.onSessionChanged?.();throw e}return data
  }
}
export const api=new ApiClient();
export const money=v=>v==null?'—':new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY',maximumFractionDigits:2}).format(Number(v)/100);
export const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
export const statusClass=s=>/COMPLETED|CONFIRMED|ACTIVE|CLEARED|HEALTHY|APPROVED|RECOMMENDED/i.test(s||'')?'ok':/FAILED|DEAD|UNHEALTHY|REJECTED|NEGATIVE|SUSPENDED/i.test(s||'')?'bad':/PENDING|REVIEW|DEGRADED|PROCESSING|OBSERVATION/i.test(s||'')?'warn':'';
export const unwrap=r=>r?.data??r;

