/* Shared plain-text registration terms reader. Consent stays closed on incomplete or draft terms. */
(function(root){
 'use strict';
 async function mount({container,policy,request,isCurrent=()=>true}){
  const versions=policy.versions||policy.terms||{},hashes=policy.term_hashes||{};
  const documents=policy.documents;
  if(!Array.isArray(documents)||!documents.length)throw new Error('注册条款正文尚未提供，请稍后重新进入。');
  const ids=new Set(),accountStage=policy.account_stage===true;let approved=policy.acceptance_enabled===true&&policy.enabled===true;
  for(const item of documents){
   if(!item.id||ids.has(item.id)||versions[item.id]!==item.version||hashes[item.id]!==item.sha256||!/^[a-f0-9]{64}$/.test(item.sha256))throw new Error('注册条款信息不完整，请重新进入。');
   ids.add(item.id);
   const path='/v1/registration-terms/'+encodeURIComponent(item.id)+'/'+encodeURIComponent(item.version);
   if(item.content_url!==path)throw new Error('注册条款地址无效，请重新进入。');
   const doc=await request(path);
   if(!isCurrent())return null;
   if(doc.id!==item.id||doc.version!==item.version||doc.sha256!==item.sha256||doc.status!==item.status||typeof doc.content!=='string'||!doc.content.trim())throw new Error('注册条款已更新或正文缺失，请重新进入。');
   const details=document.createElement('details'),heading=document.createElement('summary'),body=document.createElement('pre');
   heading.textContent=doc.title+' · '+doc.version+(doc.status==='APPROVED'?'':'（草稿，待确认）');
   body.textContent=doc.content;body.style.whiteSpace='pre-wrap';body.style.overflowWrap='anywhere';body.style.font='inherit';
   details.appendChild(heading);details.appendChild(body);container.appendChild(details);
   approved=approved&&(accountStage||doc.status==='APPROVED');
  }
  if(Object.keys(versions).length!==ids.size||Object.keys(hashes).length!==ids.size)throw new Error('注册条款清单不完整，请重新进入。');
  const notice=document.createElement('p');notice.setAttribute('role','status');
  notice.textContent=approved?(accountStage&&policy.formal_approval_pending?'账号创建阶段可继续；部分后续业务条款仍待正式审批，并将在对应业务阶段另行确认。':'请展开阅读以上完整条款，确认后勾选同意。'):'条款正文为待确认草稿，暂不能接受或提交注册。已有账号可返回登录。';container.appendChild(notice);
  return {enabled:approved,versions:{...versions},hashes:{...hashes},deferred:[...(policy.deferred||[])],account_stage:accountStage,formal_approval_pending:policy.formal_approval_pending===true};
 }
 root.GORegistrationTerms={mount};
})(globalThis);
