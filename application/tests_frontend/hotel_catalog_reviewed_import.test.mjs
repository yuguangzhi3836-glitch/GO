import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const script=fs.readFileSync(path.join(here,'../frontend/admin/hotel-page-factory.js'),'utf8');
const sourcePlan=JSON.parse(fs.readFileSync(process.env.GO_CATALOG_REVIEWED_PLAN || path.join(here,'fixtures/aoluguya_normalized_ingest_plan.json'),'utf8'));
function environment(){const ctx=vm.createContext({window:{},crypto:webcrypto,TextEncoder,Uint8Array});vm.runInContext(script,ctx);return ctx.window.GO_HOTEL_PAGE_FACTORY.reviewedImport}
const hid=sourcePlan.selected_existing_id,secondary=sourcePlan.protected_secondary_id;
function fixture(plan,{permissions=['admin:rules'],higher=false,scopeReady=true,finalCorrupt=false,failSource=0}={}){
 const calls=[];let writes=0;
 const canonical=Object.assign({},...plan.bodies.map(b=>b.payload));delete canonical.phone;
 const detail={profile:{hotel_id:hid,page_state:'DRAFT',canonical_json:{},field_provenance_json:{}},sources:[],contacts:[],media:{publishable_count:0}};
 const api={async request(route,options){calls.push({route,options});
  if(route==='/bff/auth/me')return {data:{actor_type:'GO_ADMIN',permissions}};
  if(route.endsWith('/catalog-scope/preview'))return {data:{protected_ids:[hid,secondary],physical_deletion:false,immutable_audit_retained:true,running_queue_count:0}};
  if(route.includes('/factory/overview'))return {data:{total_hotels:scopeReady?2:114,items:[{hotel_id:hid},{hotel_id:secondary}]}};
  if(route.endsWith('/factory/hotels/'+secondary))return {data:{sources:[]}};
  if(route.endsWith('/publication'))return {data:{}};
  if(route.endsWith('/sources/ingest')){writes++;if(writes===failSource)throw new Error('network interrupted');return {data:{profile:{hotel_id:hid},idempotent:true}}}
  if(route.endsWith('/factory/hotels/'+hid)){
   if(writes===3)return {data:{...detail,profile:{...detail.profile,canonical_json:finalCorrupt?{}:canonical},contacts:[{channel:'PHONE',normalized_value:plan.bodies[0].payload.phone.replace(/[^0-9+]/g,''),is_public_business_contact:true,do_not_contact:false}]}};
   if(higher)return {data:{...detail,profile:{...detail.profile,canonical_json:{rooms:[{room_type_id:'different'}]},field_provenance_json:{rooms:{source_type:'OFFICIAL_WEBSITE',confidence_bps:9900}}}}};
   return {data:detail};
  }
  throw new Error('unexpected route '+route);
 }};return {api,calls};
}
test('only exact reviewed JSON is accepted, IDs and media boundaries retained',async()=>{const helper=environment();const plan=await helper.reviewedPlan(JSON.stringify(sourcePlan),hid);assert.equal(plan.rooms.length,17);assert.equal(plan.bodies.length,3);assert.equal(plan.bodies[2].source_type,'PUBLIC_SOURCE');assert.equal(Object.isFrozen(plan.bodies[2].payload),true);assert.equal('recovery_source_manifest_sha256' in plan.bodies[2].payload,false);const changed=structuredClone(sourcePlan);changed.operations[3].body.source_type='OFFICIAL_WEBSITE';await assert.rejects(()=>helper.reviewedPlan(JSON.stringify(changed),hid),/不一致/);await assert.rejects(()=>helper.reviewedPlan(JSON.stringify(sourcePlan),secondary),/指定/)});
test('readonly account never sends a write',async()=>{const helper=environment(),plan=await helper.reviewedPlan(JSON.stringify(sourcePlan),hid),f=fixture(plan,{permissions:['admin:read']});await assert.rejects(()=>helper.executeImport(f.api,plan),/权限/);assert.equal(f.calls.some(x=>x.options?.method==='POST'),false)});
test('scope and higher-priority conflicts stop before UNPUBLISH or ingest',async()=>{for(const options of [{scopeReady:false},{higher:true}]){const helper=environment(),plan=await helper.reviewedPlan(JSON.stringify(sourcePlan),hid),f=fixture(plan,options);await assert.rejects(()=>helper.executeImport(f.api,plan));assert.equal(f.calls.some(x=>x.options?.method==='POST'),false)}});
test('unreviewed objects cannot call the import runner',async()=>{const helper=environment();const api={request:()=>{throw new Error('should not call API')}};await assert.rejects(()=>helper.executeImport(api,{hotelId:hid}),/审定文件/)});
test('approved flow uses only unpublish + three existing ingest APIs, then readback',async()=>{const helper=environment(),plan=await helper.reviewedPlan(JSON.stringify(sourcePlan),hid),f=fixture(plan);const result=await helper.executeImport(f.api,plan);assert.equal(result.profile.page_state,'DRAFT');const posts=f.calls.filter(x=>x.options?.method==='POST');assert.equal(posts.length,4);assert.equal(posts[0].options.body.action,'UNPUBLISH');assert.deepEqual(posts.slice(1).map(x=>x.options.body.source_type),['OFFICIAL_WEBSITE','OFFICIAL_WEBSITE','PUBLIC_SOURCE']);assert.equal(posts.some(x=>x.route.includes('media')||x.route.includes('activate')),false)});
test('partial failures stop subsequent imports and do not report success',async()=>{const helper=environment(),plan=await helper.reviewedPlan(JSON.stringify(sourcePlan),hid),f=fixture(plan,{failSource:2});await assert.rejects(()=>helper.executeImport(f.api,plan),/interrupted/);assert.equal(f.calls.filter(x=>x.route.endsWith('/sources/ingest')).length,2)});
test('incorrect merged facts fail final readback',async()=>{const helper=environment(),plan=await helper.reviewedPlan(JSON.stringify(sourcePlan),hid),f=fixture(plan,{finalCorrupt:true});await assert.rejects(()=>helper.executeImport(f.api,plan),/回读不一致/)});
function scopeEnvironment(){const ctx=vm.createContext({window:{},crypto:webcrypto,TextEncoder,Uint8Array});vm.runInContext(script,ctx);return ctx.window.GO_HOTEL_PAGE_FACTORY}
function scopeFixture({readonly=false,running=0,drift=false,leak=false}={}){
 const archived=Array.from({length:112},(_,i)=>'old_'+i),calls=[];let active=false,previews=0;
 const scope={protected_ids:[hid,secondary],archived_ids:archived,scope_sha256:'a'.repeat(64),running_queue_count:running,physical_deletion:false,immutable_audit_retained:true};
 const api={async request(route,options){calls.push({route,options});
  if(route==='/bff/auth/me')return {data:{actor_type:'GO_ADMIN',permissions:readonly?['admin:read']:['admin:rules']}};
  if(route.endsWith('/catalog-scope/preview')){previews++;return {data:{...scope,scope_sha256:drift&&previews>1?'b'.repeat(64):scope.scope_sha256}}}
  if(route.includes('/factory/overview'))return {data:{total_hotels:active?2:114,items:(active?[hid,secondary]:[hid,secondary,...archived]).map(hotel_id=>({hotel_id,name:'酒店'}))}};
  if(route.endsWith('/catalog-scope/activate')){active=true;return {data:scope}}
  if(route.includes('/factory/hotels/old_')){
   if(leak)return {data:{profile:{hotel_id:'old_0'}}};
   const error=new Error('CATALOG_RECORD_ARCHIVED');error.status=409;error.payload={detail:'CATALOG_RECORD_ARCHIVED'};throw error;
  }
  throw new Error('unexpected route '+route);
 }};return {api,calls};
}
test('scope preview is readonly and activation verifies all 112 archived records',async()=>{const helper=scopeEnvironment().reviewedScope,f=scopeFixture();const reviewed=await helper.previewScope(f.api);assert.equal(f.calls.some(x=>x.options?.method==='POST'),false);const result=await helper.activateScope(f.api,reviewed);assert.equal(result.retained,2);assert.equal(result.archived,112);assert.equal(result.physicalDeletion,false);const writes=f.calls.filter(x=>x.options?.method==='POST');assert.equal(writes.length,1);assert.equal(writes[0].route,'/internal/v1/hotel-infrastructure/catalog-scope/activate');assert.deepEqual(Object.keys(writes[0].options.body),['scope_sha256']);await assert.rejects(()=>helper.activateScope(f.api,reviewed),/先读取/)});
test('readonly or running-job scope does not write',async()=>{for(const options of [{readonly:true},{running:1}]){const helper=scopeEnvironment().reviewedScope,f=scopeFixture(options);await assert.rejects(()=>helper.previewScope(f.api));assert.equal(f.calls.some(x=>x.options?.method==='POST'),false)}});
test('scope fingerprint drift refuses activation without writing',async()=>{const helper=scopeEnvironment().reviewedScope,f=scopeFixture({drift:true});const reviewed=await helper.previewScope(f.api);await assert.rejects(()=>helper.activateScope(f.api,reviewed),/资料已变化/);assert.equal(f.calls.some(x=>x.options?.method==='POST'),false)});
test('scope readback leak is not reported as success',async()=>{const helper=scopeEnvironment().reviewedScope,f=scopeFixture({leak:true});const reviewed=await helper.previewScope(f.api);await assert.rejects(()=>helper.activateScope(f.api,reviewed),/仍有历史/)});
test('known anomaly codes are translated and unknown codes are not displayed',()=>{const helper=scopeEnvironment();assert.equal(helper.anomalyLabel({code:'ROOMS_MISSING',label:'ROOMS_MISSING'}),'房型资料待补齐');assert.equal(helper.anomalyLabel({code:'ADDRESS_CONFLICT',label:'ADDRESS_CONFLICT'}),'酒店地址存在来源冲突，待核对');assert.equal(helper.anomalyLabel({code:'FUTURE_INTERNAL_CODE',label:'FUTURE_INTERNAL_CODE'}),'酒店资料需要核对');assert.equal(helper.anomalyLabel({code:'x',label:'来源待核验'}),'来源待核验')});
