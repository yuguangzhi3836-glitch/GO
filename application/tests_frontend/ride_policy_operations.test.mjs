import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const code=fs.readFileSync('frontend/admin/ride-policy-operations.js','utf8');
const clone=x=>JSON.parse(JSON.stringify(x));
const event=action=>({preventDefault(){},submitter:{value:action}});
function fixture(){
 let html='',read,post=async()=>({}),forms=[],drafts=[],refresh;
 const snapshot={registry_enabled:true,can_create:true,offers:[{offer_id:'ride_standard',state:'HOLD',versions:[{policy_id:'p1',revision:'a'.repeat(64),version_no:1,state:'DRAFT',can_activate:true,can_revoke:true,policy:{version:'v1',cutoff_seconds:3600,before_fee_minor:100,after_fee_minor:200,effective_from:'2026-01-01',effective_until:'2030-01-01',time_basis:'BOOKED_PICKUP'}}]}]};
 read=async()=>clone(snapshot);const calls=[];
 const container={isConnected:true,get innerHTML(){return html},set innerHTML(value){html=value;refresh={};forms=[...value.matchAll(/data-version="([^"]+)"/g)].map(m=>{const checkbox={checked:false};return {dataset:{version:m[1]},querySelector(){return checkbox}}});drafts=[...value.matchAll(/data-draft="([^"]+)"/g)].map(m=>({dataset:{draft:m[1]},elements:{consent:{checked:false}}}));},querySelector(){return refresh},querySelectorAll(selector){return selector==='[data-version]'?forms:drafts}};
 const window={};vm.runInNewContext(code,{window,Intl,Date});
 return {ui:window.GORidePolicyOperations,container,snapshot,calls,get forms(){return forms},get drafts(){return drafts},get refresh(){return refresh},set read(value){read=value},set post(value){post=value},request:async(url,options)=>{calls.push({url,options:options&&clone(options)});return options?post(url,options):read();}};
}
const start=f=>f.ui.render({container:f.container,request:f.request});
const posts=f=>f.calls.filter(c=>c.options);

test('policy activation requires explicit confirmation and sends only server revision',async()=>{
 const f=fixture();await start(f);let form=f.forms[0];await form.onsubmit(event('activate'));assert.equal(posts(f).length,0);
 form.querySelector().checked=true;await form.onsubmit(event('activate'));
 assert.equal(posts(f)[0].url,'/internal/v1/ride-policy-operations/p1/activate');assert.deepEqual(posts(f)[0].options.body,{revision:'a'.repeat(64)});
 assert.equal(f.forms[0].querySelector().checked,false);
});
test('pending double click does not duplicate policy mutation',async()=>{
 const f=fixture();let finish;f.post=()=>new Promise(resolve=>{finish=resolve});await start(f);
 const form=f.forms[0];form.querySelector().checked=true;const pending=form.onsubmit(event('activate'));
 await form.onsubmit(event('activate'));assert.equal(posts(f).length,1);finish({});await pending;
});
test('revision conflict re-reads without automatically confirming updated policy',async()=>{
 const f=fixture();f.post=async()=>{f.snapshot.offers[0].versions[0].revision='b'.repeat(64);throw Error('REVISION_CHANGED')};await start(f);
 f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(event('activate'));
 assert.equal(posts(f).length,1);assert.equal(f.calls.filter(c=>!c.options).length,2);assert.equal(f.forms[0].querySelector().checked,false);
 await f.forms[0].onsubmit(event('activate'));assert.equal(posts(f).length,1);
 f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(event('activate'));assert.equal(posts(f)[1].options.body.revision,'b'.repeat(64));
});
test('unknown mutation response never claims success and failed read removes writes',async()=>{
 const f=fixture();await start(f);f.post=async()=>{throw Error('response lost')};f.read=async()=>{throw Error('offline')};
 f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(event('activate'));
 assert.match(f.container.innerHTML,/操作未确认/);assert.doesNotMatch(f.container.innerHTML,/操作已记录/);assert.equal(f.forms.length,0);assert.equal(f.drafts.length,0);
});
test('server capabilities prevent maker self approval and read-only writes',async()=>{
 const f=fixture();f.snapshot.offers[0].versions[0].can_activate=false;await start(f);
 assert.doesNotMatch(f.container.innerHTML,/value="activate"/);f.forms[0].querySelector().checked=true;await f.forms[0].onsubmit(event('activate'));assert.equal(posts(f).length,0);
 f.snapshot.can_create=false;f.snapshot.offers[0].versions[0].can_revoke=false;await f.refresh.onclick();
 assert.equal(f.forms.length,0);assert.equal(f.drafts.length,0);assert.match(f.container.innerHTML,/无提交草稿权限/);
});
test('untrusted policy content is escaped and meaningful conditions remain readable',async()=>{
 const f=fixture();f.snapshot.offers[0].versions[0].policy.version='<img src=x onerror=evil()>';await start(f);
 assert.doesNotMatch(f.container.innerHTML,/<img/);assert.match(f.container.innerHTML,/&lt;img/);assert.match(f.container.innerHTML,/提前1小时/);assert.match(f.container.innerHTML,/¥1.00/);
});
test('navigation detach prevents mutation and late read cannot redraw another page',async()=>{
 const f=fixture();await start(f);const form=f.forms[0];form.querySelector().checked=true;f.container.isConnected=false;
 await form.onsubmit(event('activate'));assert.equal(posts(f).length,0);
 f.container.isConnected=true;let resolve;f.read=()=>new Promise(done=>{resolve=done});const pending=f.refresh.onclick();
 f.container.isConnected=false;const previous=f.container.innerHTML;resolve(clone(f.snapshot));await pending;assert.equal(f.container.innerHTML,previous);
});
