const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const fixture=require('./registration_terms_fixture.cjs');
const source=fs.readFileSync('frontend/consumer/app.js','utf8');
const start=source.indexOf('async function showConsumerRegister()');const end=source.indexOf('\nasync function bootstrapConsumer',start);
function harness(api,document=fixture.document){
 const nodes={};for(const id of ['app','consumerRegister','doRegister','consumerRegisterError','backLogin','regName','regEmail','regPwd','regPhone','regTerms','registrationDocuments','registrationStatus','retryRegistrationRules'])nodes['#'+id]={...fixture.element(),value:'',isConnected:true,disabled:false,textContent:'',reportValidity:()=>true,addEventListener(){}};
 nodes['#doRegister'].disabled=true;nodes['#regName'].value='Test';nodes['#regEmail'].value=' traveler@example.test ';nodes['#regPwd'].value='strong-password';nodes['#regTerms'].checked=true;
 const calls=[];const ctx={document:{querySelector:key=>nodes[key]},$:key=>nodes[key],setVerticalVIMode(){},shell:s=>s,bindNav(){},showAuth(){},showAccount:()=>calls.push('account'),state:{me:null},api:async(path,opts)=>path.startsWith('/v1/registration-terms/')?document:api(path,opts),bootstrapConsumer:async()=>{ctx.state.me={user_id:'consumer'}}};
 vm.createContext(ctx);fixture.install(ctx);vm.runInContext(source.slice(start,end),ctx);return {ctx,nodes,calls};
}
const terms=fixture.policy.terms;
async function open(h){await h.ctx.showConsumerRegister();h.nodes['#regTerms'].checked=true}
test('register requires fetched server terms and posts exactly those terms',async()=>{
 const requests=[];const h=harness(async(path,options)=>{requests.push({path,options});return fixture.policy});await open(h);await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});
 assert.deepEqual(JSON.parse(requests[1].options.body),{email:'traveler@example.test',password:'strong-password',display_name:'Test',phone:null,accepted_terms:true,term_versions:terms,term_hashes:fixture.policy.term_hashes});assert.deepEqual(h.calls,['account']);
});
test('double submit creates one request while first request pending',async()=>{
 let finish,count=0;const h=harness(async(path)=>{if(path.endsWith('/registration'))return fixture.policy;count++;return new Promise(resolve=>finish=resolve)});await open(h);const first=h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});assert.equal(count,1);finish({});await first;
});
test('terms metadata failure leaves registration disabled',async()=>{
 const h=harness(async()=>{throw Error('offline')});await open(h);assert.equal(h.nodes['#doRegister'].disabled,true);assert.match(h.nodes['#consumerRegisterError'].textContent,/无法获取/);
});
test('unchecked consent cannot create account',async()=>{
 let count=0;const h=harness(async()=>{count++;return fixture.policy});await open(h);h.nodes['#regTerms'].checked=false;await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});assert.equal(count,1);
});
test('navigation during signup does not overwrite current page',async()=>{
 let finish;const h=harness(async(path)=>{if(path.endsWith('/registration'))return fixture.policy;return new Promise(resolve=>finish=resolve)});await open(h);const first=h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});h.nodes['#consumerRegister'].isConnected=false;finish({});await first;assert.deepEqual(h.calls,[]);
});
test('failed session readback never claims registration is signed in',async()=>{
 const h=harness(async()=>(fixture.policy));h.ctx.bootstrapConsumer=async()=>{};await open(h);await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});assert.deepEqual(h.calls,[]);assert.match(h.nodes['#consumerRegisterError'].textContent,/登录状态未确认/);
});

test('draft consumer terms render but cannot create account even with checked consent',async()=>{
 let submitted=0;const document={...fixture.document,status:'DRAFT'},policy={...fixture.policy,acceptance_enabled:false,enabled:false,documents:[document]};
 const h=harness(async(path)=>{if(path.endsWith('/register'))submitted++;return policy},document);await h.ctx.showConsumerRegister();
 assert.equal(h.nodes['#regTerms'].disabled,true);h.nodes['#regTerms'].checked=true;await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});assert.equal(submitted,0);assert.equal(h.nodes['#doRegister'].disabled,true);
});
test('consumer term mismatch locks consent until full terms are reloaded',async()=>{
 const h=harness(async(path)=>{if(path.endsWith('/register'))throw Error('CONSUMER_TERMS_VERSION_MISMATCH');return fixture.policy});await open(h);await h.nodes['#consumerRegister'].onsubmit({preventDefault(){}});
 assert.equal(h.nodes['#regTerms'].checked,false);assert.equal(h.nodes['#regTerms'].disabled,true);assert.equal(h.nodes['#doRegister'].disabled,true);
});
