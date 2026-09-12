import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const scripts=['booking-travelers.js','vault-manager.js'].map(f=>fs.readFileSync('frontend/consumer/'+f,'utf8'));
function setup() {
  const calls=[],dialogs=[],elements=new Map();
  const document={activeElement:{focus(){}},body:{append(d){dialogs.push(d)}},querySelectorAll(){return []},createElement(){
    const nodes=new Map(),listeners={};return {innerHTML:'',setAttribute(){},showModal(){},close(){},remove(){},addEventListener(k,f){listeners[k]=f},
      querySelector(k){if(!nodes.has(k))nodes.set(k,{value:'',checked:false,disabled:false,textContent:'',focus(){}});return nodes.get(k)},
      cancel(){listeners.cancel({preventDefault(){}})}};
  }};
  const noop=()=>{};const context={document,window:{},state:{me:{display_name:'NICKNAME'}},crypto:{randomUUID:()=>`key-${calls.length}`},setTimeout,clearTimeout,Date,Blob,URL,toast:noop,
    $:key=>{if(!elements.has(key))elements.set(key,{});return elements.get(key)},setVerticalVIMode:noop,bindNav:noop,shell:v=>v,money:v=>v,
    api:async(path,opts)=>{calls.push({path,opts});if(path.endsWith('/vault'))return {travelers:[]};if(path.endsWith('/inspect'))return {value:'PRIVATE VALUE'};if(!opts)return {items:[]};return {status:'UPDATED'}}};
  for(const name of ['renderPay','renderFlightOrder','renderRailOrder','renderMobilityOrder','renderAttractionOrder','createOrder','createFlightOrderAndCheckout','railSelect','mobilityBook','attractionBook','showAccount','showHome','showAuth','showTrip','attractionReload','mobilityReload'])context[name]=noop;
  for(const script of scripts)vm.runInNewContext(script,context);
  return {context,calls,dialogs,current:()=>dialogs.at(-1),vault:context.window.GOVault};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const submit=d=>d.querySelector('form').onsubmit({preventDefault(){}});

test('closing permission confirmation sends no permission mutation',async()=>{
  const s=setup();const p=s.vault.permissionDialog({traveler_id:'trav',full_name:'REAL NAME',relationship_type:'SELF'},'USE_FOR_BOOKING');
  s.current().cancel();await p;assert.equal(s.calls.length,0);
});

test('source disconnect remains explicit and retains server-directed semantics',async()=>{
  const s=setup();const p=s.vault.sourceAction({source_fingerprint:'source-one',source_type:'MANUAL',status:'IMPORT_ENABLED'});
  const d=s.current();await submit(d);assert.equal(s.calls.length,0);assert.match(d.querySelector('[role=alert]').textContent,/确认/);
  d.querySelector('[data-confirm]').checked=true;await submit(d);await p;
  const call=s.calls[0];assert.equal(call.path,'/v1/consumer/profile/sources/source-one/connection');assert.deepEqual(JSON.parse(call.opts.body),{allowed:false});
});

test('person edit binds the displayed revision and leaves a blank birth date untouched',async()=>{
  const s=setup();const p=s.vault.editTraveler({traveler_id:'person-one',full_name:'OLD NAME',nationality:'CHN',revision:'observed-version'});
  const d=s.current();d.querySelector('[data-confirm]').checked=true;d.querySelector('#vmName').value='NEW NAME';d.querySelector('#vmNationality').value='CHN';
  await submit(d);await p;const body=JSON.parse(s.calls[0].opts.body);
  assert.equal(body.expected_revision,'observed-version');assert.equal(body.full_name,'NEW NAME');assert.equal(body.confirmed,true);assert.equal('date_of_birth' in body,false);
});

test('sensitive import inspection happens only after explicit confirmation, with no implicit acceptance',async()=>{
  const s=setup();const p=s.vault.reviewItem({import_job_id:'job'},{import_item_id:'item',preview_masked:'****ALUE',field_type:'PASSPORT_NUMBER'});
  assert.equal(s.calls.length,0);const first=s.current();first.querySelector('[data-confirm]').checked=true;await submit(first);await tick();
  assert.equal(s.calls.length,1);assert.match(s.calls[0].path,/\/inspect$/);assert.equal(JSON.parse(s.calls[0].opts.body).confirmed,true);
  assert.match(s.current().innerHTML,/PRIVATE VALUE/);s.current().cancel();await p;assert.equal(s.calls.length,1);
});

test('untrusted imported content is escaped before display',async()=>{
  const s=setup();s.context.api=async()=>({value:'</pre><script>danger()</script>'});
  const p=s.vault.reviewItem({import_job_id:'job'},{import_item_id:'item',preview_masked:'****',field_type:'PASSPORT_NUMBER'});
  s.current().querySelector('[data-confirm]').checked=true;await submit(s.current());await tick();
  assert.ok(s.current().innerHTML.includes('&lt;script&gt;'));assert.equal(s.current().innerHTML.includes('<script>danger'),false);s.current().cancel();await p;
});

test('duplicate submits during a pending mutation call the server once',async()=>{
  const s=setup();let finish;let writes=0;
  s.context.api=async(path,opts)=>{if(opts){writes++;return new Promise(r=>{finish=r})}return path.endsWith('/vault')?{travelers:[]}:{items:[]}};
  const p=s.vault.permissionDialog({traveler_id:'trav',full_name:'PERSON',relationship_type:'SELF'},'USE_FOR_BOOKING');
  const d=s.current();d.querySelector('[data-confirm]').checked=true;const first=submit(d);await tick();await submit(d);d.cancel();
  assert.equal(writes,1);assert.equal(d.querySelector('[data-cancel]').disabled,true);finish({status:'UPDATED'});await first;await p;
});

test('import reassignment binds traveler and item revision and does not accept content',async()=>{
  const s=setup();s.context.api=async(path,opts)=>{s.calls.push({path,opts});if(opts)return {status:'NEEDS_REVIEW'};return path.endsWith('/vault')?{travelers:[]}:{items:[],status:'COMMITTED'}};
  const p=s.vault.assignTraveler({import_job_id:'job'},{import_item_id:'item',field_type:'MOBILE',revision:'item-revision'},[{traveler_id:'selected-person',full_name:'PERSON',relationship_type:'SELF'}]);
  const d=s.current();d.querySelector('[data-confirm]').checked=true;d.querySelector('#vmOwner').value='selected-person';await submit(d);await p;
  const writes=s.calls.filter(c=>c.opts);assert.equal(writes.length,1);assert.match(writes[0].path,/\/traveler$/);assert.deepEqual(JSON.parse(writes[0].opts.body),{traveler_id:'selected-person',confirmed:true,expected_revision:'item-revision'});
});
