const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const source=fs.readFileSync('frontend/consumer/app.js','utf8');
const start=source.indexOf('async function showConsumerRegister()');const end=source.indexOf('\nasync function bootstrapConsumer',start);
function harness(api){
 const nodes={};for(const id of ['app','consumerRegister','doRegister','consumerRegisterError','backLogin','regName','regEmail','regPwd','regPhone','regTerms'])nodes['#'+id]={value:'',isConnected:true,disabled:false,textContent:'',reportValidity:()=>true};
 nodes['#doRegister'].disabled=true;nodes['#regName'].value='Test';nodes['#regEmail'].value=' traveler@example.test ';nodes['#regPwd'].value='strong-password';nodes['#regTerms'].checked=true;
 const calls=[];const ctx={document:{querySelector:key=>nodes[key]},$:key=>nodes[key],setVerticalVIMode(){},shell:s=>s,bindNav(){},showAuth(){},showAccount:()=>calls.push('account'),state:{me:null},api,bootstrapConsumer:async()=>{ctx.state.me={user_id:'consumer'}}};
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);return {ctx,nodes,calls};
}
const terms={consumer_service_terms:'live-version'};
test('register requires fetched server terms and posts exactly those terms',async()=>{
 const requests=[];const h=harness(async(path,options)=>{requests.push({path,options});return {enabled:true,terms}});await h.ctx.showConsumerRegister();await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});
 assert.deepEqual(JSON.parse(requests[1].options.body),{email:'traveler@example.test',password:'strong-password',display_name:'Test',phone:null,accepted_terms:true,term_versions:terms});assert.deepEqual(h.calls,['account']);
});
test('double submit creates one request while first request pending',async()=>{
 let finish,count=0;const h=harness(async(path)=>{if(path.endsWith('/registration'))return {enabled:true,terms};count++;return new Promise(resolve=>finish=resolve)});await h.ctx.showConsumerRegister();const first=h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});assert.equal(count,1);finish({});await first;
});
test('terms metadata failure leaves registration disabled',async()=>{
 const h=harness(async()=>{throw Error('offline')});await h.ctx.showConsumerRegister();assert.equal(h.nodes['#doRegister'].disabled,true);assert.match(h.nodes['#consumerRegisterError'].textContent,/无法获取/);
});
test('unchecked consent cannot create account',async()=>{
 let count=0;const h=harness(async()=>{count++;return {enabled:true,terms}});await h.ctx.showConsumerRegister();h.nodes['#regTerms'].checked=false;await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});assert.equal(count,1);
});
test('navigation during signup does not overwrite current page',async()=>{
 let finish;const h=harness(async(path)=>{if(path.endsWith('/registration'))return {enabled:true,terms};return new Promise(resolve=>finish=resolve)});await h.ctx.showConsumerRegister();const first=h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});h.nodes['#consumerRegister'].isConnected=false;finish({});await first;assert.deepEqual(h.calls,[]);
});
test('failed session readback never claims registration is signed in',async()=>{
 const h=harness(async()=>({enabled:true,terms}));h.ctx.bootstrapConsumer=async()=>{};await h.ctx.showConsumerRegister();await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});assert.deepEqual(h.calls,[]);assert.match(h.nodes['#consumerRegisterError'].textContent,/登录状态未确认/);
});
