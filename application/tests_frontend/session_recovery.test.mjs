import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const consumerSource=fs.readFileSync('frontend/consumer/app.js','utf8');
const consoleSource=fs.readFileSync('frontend/shared/api.js','utf8');
const reply=(status,data={})=>({ok:status<400,status,json:async()=>({data,detail:status>=400?'AUTHENTICATION_REQUIRED':undefined})});

function harness(kind,dispatch){
  const calls=[];
  const document={cookie:kind==='consumer'?'go_consumer_csrf=initial':'go_csrf=initial'};
  const ctx={document,console,crypto:{randomUUID:()=> 'isolated-request'},fetch:async(path,opts)=>{
    calls.push({path,opts});return dispatch(path,opts,document,calls);
  }};
  vm.createContext(ctx);
  if(kind==='consumer'){
    const start=consumerSource.indexOf('function cookie('),end=consumerSource.indexOf('\nfunction toast(');
    vm.runInContext(consumerSource.slice(start,end),ctx);
    return {calls,ctx,request:(p,o)=>ctx.api(p,o)};
  }
  vm.runInContext(consoleSource.slice(0,consoleSource.indexOf('export const api=')).replace('export class ApiClient','class ApiClient')+'\nthis.client=new ApiClient();',ctx);
  return {calls,ctx,request:(p,o)=>ctx.client.request(p,o)};
}

for(const kind of ['consumer','console']){
  test(`${kind}: concurrent expired reads refresh once and preserve namespace`,async()=>{
    let release;const block=new Promise(r=>release=r);
    const h=harness(kind,async(p,o,doc)=>{
      if(p.endsWith('/refresh')){await block;doc.cookie=(kind==='consumer'?'go_consumer_csrf':'go_csrf')+'=rotated';return reply(200)}
      return reply(doc.cookie.endsWith('initial')?401:200,{ready:true});
    });
    const a=h.request('/v1/example'),b=h.request('/v1/example');
    await new Promise(r=>setImmediate(r));release();
    const first=await a,second=await b;assert.equal((kind==='consumer'?first:first.data).ready,true);assert.equal((kind==='consumer'?second:second.data).ready,true);
    assert.equal(h.calls.filter(c=>c.path.endsWith('/refresh')).length,1);
    for(const c of h.calls)assert.equal(c.opts.headers['X-GO-Session'],kind);
  });
  test(`${kind}: a mutation without idempotency is never replayed after renewal`,async()=>{
    const h=harness(kind,async(p)=>reply(p.endsWith('/refresh')?200:401));
    await assert.rejects(h.request('/v1/example',{method:'POST',body:kind==='consumer'?'{}':{}}),/核对当前状态/);
    assert.equal(h.calls.filter(c=>c.path==='/v1/example').length,1);
  });
  test(`${kind}: an idempotent retry retains the original key and body`,async()=>{
    const h=harness(kind,async(p,o,doc,calls)=>reply(p.endsWith('/refresh')||calls.length>2?200:401));
    await h.request('/v1/example',{method:'POST',headers:{'Idempotency-Key':'same-booking'},body:kind==='consumer'?'{}':{}});
    const posts=h.calls.filter(c=>c.path==='/v1/example');
    assert.equal(posts.length,2);assert.equal(posts[0].opts.body,posts[1].opts.body);
    assert.equal(posts[1].opts.headers['Idempotency-Key'],'same-booking');
  });
  test(`${kind}: failed refresh stops without retrying the operation`,async()=>{
    const h=harness(kind,async()=>reply(401));
    await assert.rejects(h.request('/v1/example'));
    assert.equal(h.calls.length,2);
  });
}

test('consumer logout failure preserves account and current page; success clears all private state',async()=>{
  const s=consumerSource.slice(consumerSource.indexOf('async function logoutConsumer('),consumerSource.indexOf('\n',consumerSource.indexOf('async function logoutConsumer(')));
  const ctx={state:{me:{user:'fixture'},trips:['private'],detail:{private:true},screen:'account'},api:async()=>{throw Error('offline')},toast:()=>{},showHome:()=>{ctx.shown=true}};
  vm.createContext(ctx);vm.runInContext(s,ctx);await ctx.logoutConsumer();
  assert.ok(ctx.state.me);assert.equal(ctx.shown,undefined);
  ctx.api=async()=>({status:'REVOKED'});await ctx.logoutConsumer();
  assert.equal(ctx.state.me,null);assert.equal(ctx.state.detail,null);assert.equal(ctx.state.trips.length,0);assert.equal(ctx.shown,true);
});

test('console logout failure is surfaced instead of silently reporting success',async()=>{
  const h=harness('console',async()=>{throw Error('offline')});
  await assert.rejects(h.ctx.client.logout(),/offline/);
});

test('console requests work when randomUUID is unavailable in an HTTP preview',async()=>{
  const h=harness('console',async()=>reply(200));
  h.ctx.crypto={getRandomValues:bytes=>bytes.fill(7)};
  await h.request('/bff/auth/policy');
  assert.match(h.calls[0].opts.headers['X-Request-ID'],/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
});

test('console login binds the requested account type before establishing a session',async()=>{
  const h=harness('console',async()=>reply(200));h.ctx.client.expectedActor='SUPPLIER_USER';
  await h.ctx.client.login('isolated-user','isolated-fixture');
  assert.equal(JSON.parse(h.calls[0].opts.body).expected_actor_type,'SUPPLIER_USER');
  assert.equal(h.calls[1].opts.headers['X-GO-Actor'],'SUPPLIER_USER');
});

test('a changed console actor clears the stale UI and never refreshes or retries',async()=>{
  const h=harness('console',async()=>({ok:false,status:403,json:async()=>({detail:'ACTOR_CONTEXT_CHANGED'})}));
  let cleared=0;h.ctx.client.onSessionChanged=()=>cleared++;
  await assert.rejects(h.request('/internal/v1/example'),/ACTOR_CONTEXT_CHANGED/);
  assert.equal(cleared,1);assert.equal(h.calls.length,1);
});

for(const kind of ['consumer','console'])test(`${kind}: expired access can renew once to revoke its own session`,async()=>{
  const h=harness(kind,async(p,o,doc,calls)=>reply(p.endsWith('/refresh')||calls.length>2?200:401));
  const path=kind==='consumer'?'/v1/consumer/auth/logout':'/bff/auth/logout';
  await (kind==='consumer'?h.request(path,{method:'POST'}):h.ctx.client.logout());
  assert.deepEqual(h.calls.map(c=>c.path),[path,kind==='consumer'?'/v1/consumer/auth/refresh':'/bff/auth/refresh',path]);
});
