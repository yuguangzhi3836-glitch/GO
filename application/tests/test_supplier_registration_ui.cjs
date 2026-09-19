const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/shared/app.js'),'utf8');
const start=source.indexOf('async function supplierRegisterView()');
const code=source.slice(start,source.indexOf('\n',start));
async function setup(){
 const nodes=new Map(),calls=[];let finish,fail;
 const $=id=>{if(!nodes.has(id))nodes.set(id,{value:id,checked:true,isConnected:true,disabled:false});return nodes.get(id)};
 const ctx={$,esc:x=>String(x),unwrap:x=>x?.data??x,userFacingError:x=>x,loginView(){},notice(){},me:null,document:{body:{innerHTML:''}},window:{location:{hash:''}},shell(){ctx.opened=true},api:{supplierRegistrationTerms:async()=>({versions:{supplier_service_terms:'v1'},titles:{supplier_service_terms:'服务协议'}}),supplierRegister:body=>{calls.push(body);return new Promise((resolve,reject)=>{finish=resolve;fail=reject})}}};
 vm.createContext(ctx);vm.runInContext(code,ctx);await ctx.supplierRegisterView();
 return {ctx,$,calls,fail:()=>fail(new Error('FAILED')),finish:()=>finish({actor_type:'SUPPLIER_USER',registration:{property_id:'new'}})};
}
test('nationwide supplier registration sends independent hotel geography and opens library',async()=>{
 const s=await setup();s.$('#city').value='喀什';s.$('#hotelName').value='自有酒店';
 const pending=s.$('#supplierRegister').onsubmit({preventDefault(){}});
 assert.equal(s.calls[0].city,'喀什');assert.equal(s.calls[0].hotel_name,'自有酒店');
 assert.equal(s.$('#supplierRegisterSubmit').disabled,true);s.finish();await pending;
 assert.equal(s.ctx.window.location.hash,'/one-click-build');assert.equal(s.ctx.opened,true);
});
test('double submission only creates one account request',async()=>{
 const s=await setup(), event={preventDefault(){}};
 const first=s.$('#supplierRegister').onsubmit(event);await s.$('#supplierRegister').onsubmit(event);
 assert.equal(s.calls.length,1);s.finish();await first;
});
test('supplier API keeps registration property readback with authenticated identity',async()=>{
 const apiSource=fs.readFileSync(path.join(__dirname,'../frontend/shared/api.js'),'utf8');
 const script=apiSource.replace(/export /g,'')+'\nthis.ApiClient=ApiClient;';
 const ctx={};vm.createContext(ctx);vm.runInContext(script,ctx);
 const client=new ctx.ApiClient();client.raw=async()=>({data:{property_id:'new-property',publication_state:'DRAFT'}});client.me=async()=>({data:{actor_type:'SUPPLIER_USER',user_id:'new-owner'}});
 const result=await client.supplierRegister({});assert.equal(result.data.registration.property_id,'new-property');assert.equal(result.data.actor_type,'SUPPLIER_USER');
});

function termsContext(){
 const nodes=new Map([['#login',{isConnected:true}],['#loginErr',{innerHTML:''}]]);
 const $=id=>nodes.get(id);let resolve,reject;
 const ctx={$,esc:x=>String(x),unwrap:x=>x?.data??x,userFacingError:x=>x,document:{body:{innerHTML:'login-view'}},api:{supplierRegistrationTerms:()=>new Promise((ok,bad)=>{resolve=ok;reject=bad})}};
 vm.createContext(ctx);vm.runInContext(code,ctx);
 return {ctx,$,resolve:()=>resolve({versions:{}}),reject:()=>reject(new Error('TERMS_UNAVAILABLE'))};
}
test('terms failure renders in login error without a notice container',async()=>{
 const s=termsContext(),pending=s.ctx.supplierRegisterView();s.reject();await pending;
 assert.match(s.$('#loginErr').innerHTML,/TERMS_UNAVAILABLE/);assert.equal(s.ctx.document.body.innerHTML,'login-view');
});
test('late terms result does not replace a disconnected login',async()=>{
 const s=termsContext(),pending=s.ctx.supplierRegisterView();s.$('#login').isConnected=false;s.resolve();await pending;
 assert.equal(s.ctx.document.body.innerHTML,'login-view');
});
test('late registration success cannot replace another session view',async()=>{
 const s=await setup(),pending=s.$('#supplierRegister').onsubmit({preventDefault(){}});
 s.$('#supplierRegister').isConnected=false;s.ctx.me={actor_type:'GO_ADMIN'};s.finish();await pending;
 assert.equal(s.ctx.opened,undefined);assert.equal(s.ctx.me.actor_type,'GO_ADMIN');assert.equal(s.ctx.window.location.hash,'');
});
test('late registration failure ignores disconnected error nodes',async()=>{
 const s=await setup(),pending=s.$('#supplierRegister').onsubmit({preventDefault(){}});
 s.$('#supplierRegister').isConnected=false;s.fail();await pending;
 assert.equal(s.$('#supplierRegisterErr').innerHTML,undefined);assert.equal(s.ctx.opened,undefined);
});
