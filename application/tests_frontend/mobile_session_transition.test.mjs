import test from 'node:test';
import assert from 'node:assert/strict';
import {createTransport} from '../mobile/go-app/src/api/transport.ts';
const reply=(status,data={})=>new Response(JSON.stringify(data),{status});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
function setup(handler,overrides={}){
  let access='accountA',refresh='refreshA';const calls=[];
  const transport=createTransport({baseUrl:'https://isolated.invalid',online:async()=>true,
    accessToken:async()=>access,refreshToken:async()=>refresh,
    saveTokens:async(a,r)=>{access=a;refresh=r;},clearTokens:async()=>{access=null;refresh=null;},
    newKey:()=>`isolated-${calls.length}`,fetch:async(url,init)=>{const call={url,method:init.method,body:init.body,headers:new Headers(init.headers)};calls.push(call);return handler(call);},...overrides});
  return {transport,calls,tokens:()=>({access,refresh})};
}
test('logout immediately invalidates old UI and blocks orders while remote revocation is pending',async()=>{
  const wait=deferred(),entered=deferred();const h=setup(async c=>{if(c.url.endsWith('/logout')){entered.resolve();await wait.promise;}return reply(200,{data:{status:'REVOKED'}});});
  let changes=0;h.transport.subscribe(()=>changes++);const before=h.transport.version();
  const logout=h.transport.logout();const immediate={version:h.transport.version(),changes};
  await entered.promise;
  const order=await h.transport.request('/v1/orders',{method:'POST'}).catch(e=>e);
  wait.resolve();await logout;
  assert.ok(immediate.version>before);assert.equal(immediate.changes,1);
  assert.equal(order.message,'SESSION_EXPIRED');assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].headers.get('Authorization'),'Bearer accountA');
});
test('read started before logout cannot return old account data',async()=>{
  const wait=deferred(),entered=deferred();const h=setup(async c=>{if(c.url.endsWith('/me')){entered.resolve();await wait.promise;return reply(200,{data:{user_id:'A'}});}return reply(200,{data:{status:'REVOKED'}});});
  const old=h.transport.request('/v1/consumer/me').catch(e=>e);await entered.promise;
  const logout=h.transport.logout();wait.resolve();const result=await old;await logout;
  assert.equal(result.message,'SESSION_CHANGED');
});
test('clear blocks stale stored credentials before slow deletion completes',async()=>{
  const wait=deferred();const h=setup(async()=>reply(200),{clearTokens:async()=>wait.promise});
  const clearing=h.transport.clear();const pending=h.transport.request('/v1/orders',{method:'POST'}).catch(e=>e);
  await new Promise(r=>setImmediate(r));assert.equal(h.calls.length,0);wait.resolve();await clearing;
  assert.equal((await pending).message,'SESSION_EXPIRED');assert.equal(h.calls.length,0);
});
test('logout supersedes a login waiting for secure storage without dispatching login',async()=>{
  const wait=deferred();let clears=0;const h=setup(async()=>reply(200,{data:{access_token:'late',refresh_token:'late-r'}}),{clearTokens:async()=>{if(++clears===1)await wait.promise;}});
  const login=h.transport.login('isolated@example.test','fixture').catch(e=>e);
  const logout=h.transport.logout().catch(e=>e);wait.resolve();const result=await login;await logout;
  assert.equal(result.message,'SESSION_CHANGED');assert.equal(h.calls.filter(c=>c.url.endsWith('/login')).length,0);
});
test('late failed logout cannot clear a later successful account login',async()=>{
  const wait=deferred(),entered=deferred();const h=setup(async c=>{if(c.url.endsWith('/logout')){entered.resolve();await wait.promise;throw Error('offline');}return reply(200,{data:{access_token:'accountB',refresh_token:'refreshB'}});});
  const old=h.transport.logout().catch(e=>e);await entered.promise;await h.transport.login('b@example.test','fixture');wait.resolve();await old;
  assert.deepEqual(h.tokens(),{access:'accountB',refresh:'refreshB'});
});
test('missing refresh token after 401 invalidates the authenticated UI',async()=>{
  const h=setup(async()=>reply(401),{refreshToken:async()=>null});let changes=0;h.transport.subscribe(()=>changes++);
  await assert.rejects(h.transport.request('/v1/consumer/me'),/SESSION_EXPIRED/);assert.equal(changes,1);assert.equal(h.tokens().access,null);
});
test('401 after successful refresh invalidates the session without a third request',async()=>{
  const h=setup(async c=>c.url.endsWith('/refresh')?reply(200,{data:{access_token:'refreshed',refresh_token:'rotated'}}):reply(401));
  await assert.rejects(h.transport.request('/v1/orders',{method:'POST'}),/SESSION_EXPIRED/);
  assert.equal(h.calls.length,3);assert.equal(h.tokens().access,null);
});
test('a permission denial does not clear an otherwise valid account',async()=>{
  const h=setup(async()=>reply(403,{detail:'OWN_ORDER_REQUIRED'}));
  await assert.rejects(h.transport.request('/v1/orders'),/OWN_ORDER_REQUIRED/);assert.equal(h.tokens().access,'accountA');
});
test('a broken UI subscriber cannot prevent token clearing or other subscribers',async()=>{
  const h=setup(async()=>reply(200));let notified=0;h.transport.subscribe(()=>{throw Error('unmounted UI');});h.transport.subscribe(()=>notified++);
  await h.transport.clear();assert.equal(notified,1);assert.equal(h.tokens().access,null);
});
test('failed token persistence cannot expose a partially saved login to requests',async()=>{
  let stored='accountA';
  const h=setup(async()=>reply(200,{data:{access_token:'new',refresh_token:'new-r'}}),{
    accessToken:async()=>stored,clearTokens:async()=>{stored=null;},
    saveTokens:async(a)=>{stored=a;throw Error('secure storage failure');}});
  await assert.rejects(h.transport.login('a@example.test','fixture'),/secure storage failure/);
  assert.equal(stored,null);
  await assert.rejects(h.transport.request('/v1/orders',{method:'POST'}),/SESSION_EXPIRED/);
  assert.equal(h.calls.length,1);
});
test('temporary refresh outage preserves the session and never retries the business mutation',async()=>{
  const h=setup(async c=>c.url.endsWith('/refresh')?reply(503):reply(401));
  await assert.rejects(h.transport.request('/v1/orders',{method:'POST'}),/SESSION_REFRESH_UNAVAILABLE/);
  assert.equal(h.tokens().access,'accountA');assert.equal(h.calls.length,2);
});
test('a successful HTTP response without revocation evidence is not remote logout success',async()=>{
  const h=setup(async()=>reply(200,{}));await assert.rejects(h.transport.logout(),/REMOTE_LOGOUT_UNCONFIRMED/);
  assert.equal(h.tokens().access,null);
});
