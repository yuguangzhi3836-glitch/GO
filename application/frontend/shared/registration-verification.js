(function(root){
 'use strict';
 const messages={
  REGISTRATION_CODE_INVALID_OR_EXPIRED:'验证码不正确、已过期或已使用，请检查或重新获取。',
  REGISTRATION_CODE_RATE_LIMITED:'发送过于频繁，请稍后再试。',
  REGISTRATION_EMAIL_SEND_FAILED:'验证码发送未完成，请稍后重新获取。',
  REGISTRATION_CODE_REPLACED:'已有新的验证码，请使用最新邮件。',
  REGISTRATION_VERIFICATION_NOT_READY:'邮箱验证服务暂不可用，请稍后重试。',
  REGISTRATION_SEPARATE_DECISIONS_REQUIRED:'请分别确认协议与隐私告知。',
  VALID_EMAIL_REQUIRED:'请填写有效的邮箱地址。'
 };
 function message(error){return messages[error?.message||error]||error?.message||String(error)}
 function markup(){return '<div class="field"><label for="registrationCode">邮箱验证码</label><input id="registrationCode" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required disabled><button class="btn ghost" id="sendRegistrationCode" type="button" disabled>获取验证码</button><p id="registrationCodeStatus" role="status" aria-live="polite"></p></div><section id="registrationDecisions" aria-label="分项协议与隐私告知"></section>'}
 function mount({form,email,accepted,policy,request,audience}){
  const code=form.querySelector('#registrationCode'),button=form.querySelector('#sendRegistrationCode'),status=form.querySelector('#registrationCodeStatus');
  const decisionContainer=form.querySelector('#registrationDecisions');
  let decisionVersion=null,decisionInputs={};
  function decisions(){
   const p=policy();if(!p?.enabled)throw Error('注册条款尚未就绪。');
   const out={},deferred=new Set(p.deferred||[]);for(const key of Object.keys(p.versions)){
    if(deferred.has(key)){out[key]='DEFERRED';continue}
    if(!decisionInputs[key]?.checked)throw Error('请分别确认协议与隐私告知。');
    out[key]=key==='privacy_policy'?'NOTICE_ACKNOWLEDGED':'CONTRACT_ACCEPTED';
   }return out;
  }
  function renderDecisions(){
   const p=policy();if(!decisionContainer||!p)return;
   const version=JSON.stringify([p.versions,p.hashes,p.enabled]);if(version===decisionVersion)return;
   decisionVersion=version;decisionInputs={};decisionContainer.replaceChildren();
   const deferred=new Set(p.deferred||[]);
   for(const key of Object.keys(p.versions)){
    const label=document.createElement('label');label.style.display='block';
    if(deferred.has(key)){
     const deferredText=key==='personal_vault_terms'?'旅行资料库为可选功能，注册时不开通或授权。':
      key==='data_processing_terms'?'数据协作条款将在启用相应业务能力时另行确认。':
      key==='electronic_signature_authorization'?'电子签约授权将在合同阶段另行确认。':'该条款将在对应业务阶段另行确认。';
     label.textContent=deferredText;decisionContainer.append(label);continue
    }
    const input=document.createElement('input');input.type='checkbox';input.required=true;input.disabled=!p.enabled;input.dataset.term=key;
    input.addEventListener('change',update);decisionInputs[key]=input;label.append(input);
    const title=({privacy_policy:'隐私政策',consumer_service_terms:'用户服务条款',supplier_service_terms:'供应商服务条款',data_processing_terms:'数据处理条款',electronic_signature_authorization:'电子签署授权',platform_operating_rules:'平台运营规则'})[key]||key;
    label.append(document.createTextNode(key==='privacy_policy'?'我已阅读隐私告知（不代表同意可选营销或旅行资料共享）':'我已阅读并接受'+title));decisionContainer.append(label);
   }
  }
  let challenge=null,sending=false,retryAt=0,revision=0,timer=null;
  const address=()=>email.value.trim().toLowerCase();
  function update(){
   if(!form.isConnected){clearTimeout(timer);return}
   renderDecisions();
   let choicesReady=false;try{decisions();choicesReady=true}catch{}
   const wait=Math.max(0,Math.ceil((retryAt-Date.now())/1000));
   button.disabled=sending||wait>0||!policy()?.enabled||!accepted.checked||!choicesReady;
   button.textContent=sending?'正在发送…':wait?`${wait} 秒后可重发`:challenge?'重新获取验证码':'获取验证码';
   code.disabled=!policy()?.enabled;clearTimeout(timer);if(wait)timer=setTimeout(update,1000);
  }
  email.addEventListener('input',()=>{revision++;challenge=null;code.value='';status.textContent='邮箱变化后请重新获取验证码。';update()});
  accepted.addEventListener('change',update);
  button.onclick=async()=>{
   if(button.disabled||!email.reportValidity())return;
   const p=policy(),requested=address(),generation=revision;sending=true;challenge=null;code.value='';status.textContent='正在发送验证码…';update();
   try{
    const result=await request('/v1/registration/challenges',{method:'POST',body:JSON.stringify({audience,email:requested,accepted_terms:true,registration_decisions:decisions(),term_versions:p.versions,term_hashes:p.hashes})});
    if(!form.isConnected||generation!==revision||requested!==address())return;
    challenge={id:result.challenge_id,email:requested};retryAt=Date.now()+Math.max(60,result.resend_after||60)*1000;
    status.textContent='验证码已发送，请查看邮箱（包括垃圾邮件），10 分钟内有效。';code.focus();
   }catch(error){if(form.isConnected&&generation===revision){status.textContent=message(error);retryAt=Date.now()+60000}}
   finally{sending=false;update()}
  };
  update();
  return {update,payload(){
   if(!challenge||challenge.email!==address())throw Error('请先获取当前邮箱的验证码。');
   if(!/^[0-9]{6}$/.test(code.value))throw Error('请输入邮件中的 6 位验证码。');
   return {challenge_id:challenge.id,verification_code:code.value,registration_decisions:decisions()};
  }};
 }
 root.GORegistrationVerification={markup,mount,message};
})(typeof window!=='undefined'?window:globalThis);
