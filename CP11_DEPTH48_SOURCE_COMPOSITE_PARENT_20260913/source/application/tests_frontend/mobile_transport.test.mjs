import test from 'node:test';
import assert from 'node:assert/strict';
import {createTransport} from '../mobile/go-app/src/api/transport.ts';
const response=(status,data)=>new Response(JSON.stringify(data),{status});
function harness(fetch){let access='old',refresh='r1',keys=0;const calls=[];
 const t=createTransport({baseUrl:'https://isolated.invalid',online:async()=>true,accessToken:async()=>access,refreshToken:async()=>refresh,
 saveTokens:async(a,r)=>{access=a;refresh=r;},clearTokens:async()=>{access=null;refresh=null;},newKey:()=>`key-${++keys}`,
 fetch:async(url,init)=>{const x={url,method:init.method,headers:Object.fromEntries(init.headers instanceof Headers?init.headers:new Headers(init.headers)),body:init.body};calls.push(x);return fetch(x,init);}});
 return {t,calls,tokens:()=>({access,refresh}),keys:()=>keys};}
const defer=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
test('concurrent expired mutations share one refresh and retain each original idempotency key/body',async()=>{
 const h=harness(async x=>x.url.endsWith('/refresh')?response(200,{data:{access_token:'new',refresh_token:'r2'}}):
   x.headers.authorization==='Bearer old'?response(401,{detail:'EXPIRED'}):response(200,{data:{accepted:true}}));
 await Promise.all([h.t.request('/v1/one',{method:'post',body:'{"amount":100}'}),h.t.request('/v1/two',{method:'POST',headers:{'idempotency-key':'fixed'},body:'{"amount":200}'})]);
 assert.equal(h.calls.filter(x=>x.url.endsWith('/refresh')).length,1);
 for(const p of ['one','two']){const attempts=h.calls.filter(x=>x.url.endsWith('/'+p));assert.equal(attempts.length,2);assert.equal(attempts[0].headers['idempotency-key'],attempts[1].headers['idempotency-key']);assert.equal(attempts[0].body,attempts[1].body);assert.equal(attempts[1].headers.authorization,'Bearer new');}
 assert.equal(h.calls.filter(x=>x.url.endsWith('/two'))[0].headers['idempotency-key'],'fixed');assert.equal(h.keys(),1);
});
test('a mutation with lost response is uncertain and is never automatically retried',async()=>{
 const h=harness(async()=>{throw Error('connection lost after write');});
 await assert.rejects(h.t.request('/v1/orders',{method:'POST'}),e=>e.uncertain===true&&e.message==='NETWORK_RESULT_UNKNOWN');assert.equal(h.calls.length,1);
});
test('account change discards pending reads and refresh tokens from the old account',async()=>{
 const wait=defer(),entered=defer();const h=harness(async x=>{if(x.url.endsWith('/refresh')){entered.resolve();await wait.promise;return response(200,{data:{access_token:'resurrect',refresh_token:'bad'}});}return response(401,{});});
 const result=h.t.request('/v1/orders').catch(e=>e);await entered.promise;await h.t.clear();wait.resolve();
 assert.equal((await result).message,'SESSION_CHANGED');assert.deepEqual(h.tokens(),{access:null,refresh:null});
});
test('refresh rejection invalidates current session and notifies the UI',async()=>{
 const h=harness(async()=>response(401,{detail:'EXPIRED'}));let changes=0;const unsubscribe=h.t.subscribe(()=>changes++);
 await assert.rejects(h.t.request('/v1/orders'),/SESSION_EXPIRED/);assert.equal(changes,1);assert.deepEqual(h.tokens(),{access:null,refresh:null});unsubscribe();await h.t.clear();assert.equal(changes,1);
});
test('logout revokes remotely and still clears locally after a transport failure',async()=>{
 const h=harness(async()=>{throw Error('offline');});await assert.rejects(h.t.logout());assert.equal(h.calls[0].url,'https://isolated.invalid/v1/consumer/auth/logout');assert.deepEqual(h.tokens(),{access:null,refresh:null});
});
test('a previous logout cannot clear a newly logged-in account',async()=>{
 const wait=defer(),entered=defer();const h=harness(async x=>{if(x.url.endsWith('/logout')){entered.resolve();await wait.promise;return response(200,{});}return response(200,{data:{access_token:'accountB',refresh_token:'refreshB'}});});
 const old=h.t.logout().catch(e=>e);await entered.promise;await h.t.login('b@example.test','test');wait.resolve();await old;
 assert.deepEqual(h.tokens(),{access:'accountB',refresh:'refreshB'});
});
test('only chosen API-relative paths are requested and caller auth cannot override the session',async()=>{
 const h=harness(async()=>response(200,{}));for(const p of ['https://other.invalid/v1/x','//other.invalid/v1/x','/internal/v1/x','/v1/a\\b','/v1/a#b'])await assert.rejects(h.t.request(p),/INVALID_API_PATH/);
 assert.equal(h.calls.length,0);await h.t.request('/v1/orders',{headers:{Authorization:'Bearer forged'}});assert.equal(h.calls[0].headers.authorization,'Bearer old');
});
test('aborted mutations before dispatch are known not sent; malformed successful responses are uncertain',async()=>{
 const h=harness(async()=>new Response('invalid',{status:200}));const abort=new AbortController();abort.abort();
 await assert.rejects(h.t.request('/v1/orders',{method:'POST',signal:abort.signal}),e=>e.message==='REQUEST_CANCELLED'&&!e.uncertain);assert.equal(h.calls.length,0);
 await assert.rejects(h.t.request('/v1/orders',{method:'POST'}),e=>e.message==='INVALID_API_RESPONSE'&&e.uncertain);
});
