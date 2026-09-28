const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/admin/hotel-direct-review.js'),'utf8');
function module(){const ctx={};vm.createContext(ctx);vm.runInContext(source,ctx);return ctx.GO_HOTEL_DIRECT_REVIEW}
const inspect=(id='r1',state='SUBMITTED',hash='a'.repeat(64))=>({facts_sha256:'f'.repeat(64),review:{review_id:id,state,manifest_sha256:hash},property:{name_zh:'酒店'},actions:{can_approve:state==='SUBMITTED',can_publish:state==='APPROVED',can_revoke:state==='APPROVED'},assets:[],room_mappings:[]});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
test('approve fresh-reads and submits exact displayed manifest hash then reads back',async()=>{
 const calls=[];let d=inspect();const c=module().createController({request:async(p,o)=>{calls.push({p,o});if(o){d=inspect('r1','APPROVED');return{data:{}}}return{data:d}}},()=>{});
 await c.open('r1');assert.equal(c.prepare('approve'),true);assert.equal(await c.confirm(),true);
 assert.equal(calls.length,4);assert.equal(calls[2].o.body.expected_sha256,'a'.repeat(64));assert.equal(calls[2].o.body.expected_facts_sha256,'f'.repeat(64));assert.equal(c.state().detail.review.state,'APPROVED');
});
test('changed hash or state blocks mutation and requires fresh confirmation',async()=>{
 let d=inspect(),posts=0;const c=module().createController({request:async(p,o)=>{if(o)posts++;return{data:d}}},()=>{});await c.open('r1');c.prepare('approve');d=inspect('r1','SUBMITTED','b'.repeat(64));await assert.rejects(c.confirm(),/REVIEW_CHANGED/);assert.equal(posts,0);assert.equal(c.state().pending,null);assert.equal(c.state().busy,false);
});
test('duplicate confirmation while pending never sends a second action',async()=>{
 const wait=deferred();let posts=0,reads=0;const c=module().createController({request:async(p,o)=>{if(o){posts++;return{data:{}}}reads++;if(reads===2)return wait.promise;return{data:inspect()}}},()=>{});await c.open('r1');c.prepare('approve');const one=c.confirm();assert.equal(await c.confirm(),false);wait.resolve({data:inspect()});await one;assert.equal(posts,1);
});
test('older hotel inspection cannot replace newer hotel response',async()=>{
 const a=deferred(),b=deferred();const c=module().createController({request:p=>p.includes('/r1/')?a.promise:b.promise},()=>{});const first=c.open('r1'),second=c.open('r2');b.resolve({data:inspect('r2')});await second;a.resolve({data:inspect('r1')});assert.equal(await first,false);assert.equal(c.state().detail.review.review_id,'r2');
});
test('leaving view during confirmation read prevents action',async()=>{
 const wait=deferred();let reads=0,posts=0,active=true;const c=module().createController({request:async(p,o)=>{if(o)posts++;if(++reads===2)return wait.promise;return{data:inspect()}}},()=>{},()=>active);await c.open('r1');c.prepare('approve');const action=c.confirm();active=false;wait.resolve({data:inspect()});assert.equal(await action,false);assert.equal(posts,0);
});
test('post failure cannot report success or retain a ready confirmation',async()=>{
 const c=module().createController({request:async(p,o)=>{if(o)throw Error('FAIL');return{data:inspect()}}},()=>{});await c.open('r1');c.prepare('approve');await assert.rejects(c.confirm());assert.equal(c.state().pending,null);assert.equal(c.state().busy,false);
});
test('state capability is required and publish never calls the legacy request endpoint',async()=>{
 const calls=[];const c=module().createController({request:async(p,o)=>{calls.push({p,o});return{data:inspect('r1','APPROVED')}}},()=>{});await c.open('r1');assert.equal(c.prepare('approve'),false);c.prepare('publish');await c.confirm();assert.ok(calls.some(x=>x.p.endsWith('/r1/publish')&&x.o.method==='POST'));assert.ok(!calls.some(x=>x.p.includes('publication-requests')));
});
test('supplier strings are escaped and internal conflict codes are not shown as primary error',()=>{
 const d=inspect();d.property.name_zh='<img src=x onerror=alert(1)>';d.conflicts=[{code:'ROOM_MAPPING_AUTHORITY_UNAVAILABLE'}];d.assets=[{rights:{rights_holder:'<script>bad</script>',usage_scope:[]},verification:{}}];const html=module().inspectionHtml(d);assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img src=x'));assert.match(html,/&lt;img/);assert.ok(!html.includes('ROOM_MAPPING_AUTHORITY_UNAVAILABLE'));
});
test('image preview is lazy and contains no remote supplier URL in markup',()=>{
 const d=inspect();d.assets=[{preview_url:'https://attacker.test/file',rights:{usage_scope:[]}}];const html=module().inspectionHtml(d);assert.ok(!html.includes('<img'));assert.ok(!html.includes('attacker.test'));assert.match(html,/data-preview/);
});
async function apiModule(fetch){const ctx={fetch,crypto:{randomUUID:()=> 'req'},document:{cookie:''}};vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/shared/api.js'),'utf8').replace(/export /g,'')+'\nglobalThis.Client=ApiClient;',ctx);return new ctx.Client()}
test('authenticated blob retains actor and cookie headers without parsing successful image JSON',async()=>{
 let sent;const blob={image:true};const api=await apiModule(async(p,o)=>{sent=o;return{ok:true,headers:{get:()=> 'image/jpeg'},blob:async()=>blob,json:async()=>{throw Error('must not parse')}}});api.expectedActor='GO_ADMIN';assert.equal(await api.requestBlob('/internal/image'),blob);assert.equal(sent.credentials,'same-origin');assert.equal(sent.headers['X-GO-Actor'],'GO_ADMIN');assert.equal(sent.headers['X-GO-Session'],'console');assert.equal(sent.responseType,undefined);
});
test('blob rejects active SVG or unexpected content type',async()=>{
 const api=await apiModule(async()=>({ok:true,headers:{get:()=> 'image/svg+xml'}}));await assert.rejects(api.requestBlob('/internal/image'),/MEDIA_TYPE_UNSUPPORTED/);
});
test('blob auth context change triggers existing session callback',async()=>{
 const api=await apiModule(async()=>({ok:false,status:403,json:async()=>({detail:'ACTOR_CONTEXT_CHANGED'})}));let changed=0;api.onSessionChanged=()=>changed++;await assert.rejects(api.requestBlob('/internal/image'),/ACTOR_CONTEXT_CHANGED/);assert.equal(changed,1);
});
function domHarness(){
 const elements=new Map();const element=()=>({value:'',innerHTML:'',textContent:'',disabled:false,isConnected:true,querySelectorAll:()=>[],querySelector:()=>element()});
 const root={innerHTML:'',querySelector:s=>{if(!elements.has(s))elements.set(s,element());return elements.get(s)},contains:()=>true};
 const context={URLSearchParams,URL};vm.createContext(context);vm.runInContext(source,context);return{root,ui:context.GO_HOTEL_DIRECT_REVIEW};
}
test('review list omits empty state/property filters accepted by backend',async()=>{
 const {root,ui}=domHarness();let requested;ui.mount({root,notice:()=>{},api:{request:async p=>{requested=p;return{data:{items:[],total:0}}}}});await new Promise(resolve=>setImmediate(resolve));const query=new URL('https://go.test'+requested).searchParams;assert.equal(query.has('state'),false);assert.equal(query.has('property_id'),false);assert.equal(query.get('limit'),'25');
});
test('session change before list reply clears previous hotel details and ignores response',async()=>{
 const {root,ui}=domHarness(),wait=deferred();let session='first';ui.mount({root,notice:()=>{},api:{csrf:()=>session,request:()=>wait.promise}});session='second';wait.resolve({data:{items:[{review_id:'r-other',property_name:'other hotel'}],total:1}});await new Promise(resolve=>setImmediate(resolve));assert.equal(root.querySelector('[data-list]').innerHTML,'');assert.match(root.querySelector('[data-status]').textContent,/登录会话已变化/);
});
test('unexpected review identity cannot arm a mutation',async()=>{
 const c=module().createController({request:async()=>({data:inspect('other-review')})},()=>{});await assert.rejects(c.open('expected-review'),/REVIEW_CHANGED/);assert.equal(c.prepare('approve'),false);
});
test('changed hotel or room facts with same manifest hash require a new confirmation',async()=>{
 let d=inspect(),posts=0;const c=module().createController({request:async(p,o)=>{if(o)posts++;return{data:d}}},()=>{});await c.open('r1');assert.equal(c.prepare('approve'),true);d={...inspect(),facts_sha256:'e'.repeat(64)};await assert.rejects(c.confirm(),/REVIEW_CHANGED/);assert.equal(posts,0);assert.equal(c.state().detail.facts_sha256,'e'.repeat(64));assert.equal(c.state().pending,null);
});
test('missing trusted facts snapshot cannot arm approval',async()=>{
 const d=inspect();delete d.facts_sha256;const c=module().createController({request:async()=>({data:d})},()=>{});await c.open('r1');assert.equal(c.prepare('approve'),false);assert.match(module().inspectionHtml(d),/data-action="approve" disabled/);
});
function factoryHarness(request){
 let html='',nodes=new Map(),mounted=0;
 const root={get innerHTML(){return html},set innerHTML(v){html=v;nodes=new Map();if(v.includes('factoryLoadingStatus'))nodes.set('#factoryLoadingStatus',{textContent:''})},insertAdjacentHTML(_,v){html=v+html;if(v.includes('directReviewOpen'))nodes.set('#directReviewOpen',{})},querySelector:s=>nodes.get(s)||null};
 const context={window:{GO_HOTEL_DIRECT_REVIEW:{mount:()=>{mounted++;root.innerHTML='<div>review interface</div>'}}}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/admin/hotel-page-factory.js'),'utf8'),context);
 return{root,mounted:()=>mounted,render:()=>context.window.GO_HOTEL_PAGE_FACTORY.render({root,api:{request},notice:()=>{}})};
}
test('failed legacy factory overview leaves review entry available and functional',async()=>{
 const f=factoryHarness(async()=>{throw Error('LEGACY_FAILURE')});await f.render();assert.match(f.root.querySelector('#factoryLoadingStatus').textContent,/仍可进入酒店资料审核/);f.root.querySelector('#directReviewOpen').onclick();assert.equal(f.mounted(),1);
});
test('opening review during legacy overview prevents stale factory redraw and further legacy requests',async()=>{
 const wait=deferred();let calls=0;const f=factoryHarness(()=>{calls++;return wait.promise});const loading=f.render();f.root.querySelector('#directReviewOpen').onclick();wait.resolve({data:{}});await loading;assert.equal(calls,1);assert.match(f.root.innerHTML,/review interface/);
});
