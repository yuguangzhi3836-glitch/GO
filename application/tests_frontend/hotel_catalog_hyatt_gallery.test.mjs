import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const script=fs.readFileSync(path.join(here,'../frontend/admin/hotel-page-factory.js'),'utf8');
const raw=fs.readFileSync(path.join(here,'fixtures/aoluguya_hyatt_expanded_40_plan.json'),'utf8'),original=JSON.parse(raw);
const hid=original.canonical_hotel_id,secondary=original.protected_secondary_id;
function environment(){const context=vm.createContext({window:{},crypto:webcrypto,TextEncoder,Uint8Array});vm.runInContext(script,context);return context.window.GO_HOTEL_PAGE_FACTORY.reviewedGallery}
function record(item,index){return {asset_id:'asset_'+index,...item.request.body,...item.expected,room_type_id:null,cache_state:'VALIDATED'}}
function fixture({allExisting=false,readonly=false,corruptReply=false,lostResponse=false,existingCorrupt=false,duplicate=false,readbackLost=false}={}){
 const records=allExisting?original.items.map(record):[],calls=[];let postCount=0,lost=false;
 if(existingCorrupt){records.push(record(original.items[0],0));records[0].sha256='0'.repeat(64)}
 if(duplicate)records.push(record(original.items[0],0),record(original.items[0],1));
 const detail={profile:{hotel_id:hid,page_state:'DRAFT',canonical_json:{rooms:Array.from({length:17},(_,i)=>({room_type_id:'room_'+i}))}}};
 const api={async request(route,options){calls.push({route,options});
  if(route==='/bff/auth/me')return {data:{actor_type:'GO_ADMIN',permissions:readonly?['admin:read']:['admin:rules']}};
  if(route.endsWith('/catalog-scope/preview'))return {data:{protected_ids:[hid,secondary],archived_ids:Array.from({length:112},(_,i)=>'old_'+i),scope_sha256:'a'.repeat(64),running_queue_count:0,physical_deletion:false,immutable_audit_retained:true}};
  if(route.includes('/factory/overview'))return {data:{total_hotels:2,items:[{hotel_id:hid},{hotel_id:secondary}]}};
  if(route.endsWith('/factory/hotels/'+hid))return {data:detail};
  if(route.includes('/media/assets?'))return {data:readbackLost&&postCount>0?[]:records.map(x=>({...x}))};
  if(route.endsWith('/media/harvest')){
   postCount++;const index=original.items.findIndex(x=>x.request.body.source_url===options.body.source_url);assert.notEqual(index,-1);
   const asset=record(original.items[index],index);records.push(asset);
   if(lostResponse&&!lost){lost=true;throw new Error('unknown network outcome')}
   return {data:corruptReply?{...asset,width:1}:asset};
  }
  throw new Error('unexpected route '+route);
 }};
 return {api,calls,records,get postCount(){return postCount}};
}
test('exact Hyatt plan admitted; changes, wrong hotel and invented kwargs rejected',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid);assert.equal(p.items.length,40);assert.ok(p.items.every(x=>['HERO','GALLERY'].includes(x.body.role)&&!('room_type_id'in x.body)&&!('expected_sha256'in x.body)));assert.ok(Object.isFrozen(p.items[0].body));let altered=structuredClone(original);altered.items[0].request.body.source_url='https://example.com/image.jpg';await assert.rejects(()=>h.reviewedGalleryPlan(JSON.stringify(altered),hid),/不一致/);altered=structuredClone(original);altered.items[0].request.body.expected_sha256=altered.items[0].expected.sha256;await assert.rejects(()=>h.reviewedGalleryPlan(JSON.stringify(altered),hid),/不一致/);await assert.rejects(()=>h.reviewedGalleryPlan(raw,secondary),/指定/)});
test('readonly user and unreviewed plans never write',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture({readonly:true});await assert.rejects(()=>h.executeGalleryImport(f.api,p),/权限/);assert.equal(f.postCount,0);await assert.rejects(()=>h.executeGalleryImport(f.api,{hotelId:hid}),/审定图库/)});
test('40 images including hero are metadata-checked without rights/publication/room writes',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture();const result=await h.executeGalleryImport(f.api,p);assert.equal(result.checked,40);assert.equal(result.harvested,40);assert.equal(result.reused,0);assert.equal(result.independentServedByteHashVerified,false);assert.equal(result.roomBindings,0);assert.equal(result.published,false);const posts=f.calls.filter(c=>c.options?.method==='POST');assert.equal(posts.length,40);assert.ok(posts.every(c=>c.route.endsWith('/media/harvest')));assert.ok(posts.every(c=>['HERO','GALLERY'].includes(c.options.body.role)&&!c.options.body.room_type_id&&!c.options.body.rights_state))});
test('existing reviewed gallery assets are reused without POST',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture({allExisting:true});const result=await h.executeGalleryImport(f.api,p);assert.equal(result.reused,40);assert.equal(f.postCount,0)});
test('lost harvest response resumes by querying index instead of duplicating',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture({lostResponse:true});await assert.rejects(()=>h.executeGalleryImport(f.api,p),/unknown network outcome/);assert.equal(f.records.length,1);const result=await h.executeGalleryImport(f.api,p);assert.equal(result.reused,1);assert.equal(result.harvested,39);assert.equal(f.postCount,40);assert.equal(f.records.length,40)});
test('harvest mismatch stops immediately and does not pretend indexed row rolled back',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture({corruptReply:true});await assert.rejects(()=>h.executeGalleryImport(f.api,p),/不一致/);assert.equal(f.postCount,1);assert.equal(f.records.length,1)});
test('wrong existing hash or duplicate source records stop before write',async()=>{for(const options of [{existingCorrupt:true},{duplicate:true}]){const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture(options);await assert.rejects(()=>h.executeGalleryImport(f.api,p));assert.equal(f.postCount,0)}});
test('missing index readback stops after first image',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture({readbackLost:true});await assert.rejects(()=>h.executeGalleryImport(f.api,p),/索引回读/);assert.equal(f.postCount,1)});
test('public or room-bound asset is never silently reused',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid);for(const changes of [{publishable:true},{rights_state:'AUTHORIZED'},{room_type_id:'invented'},{source_type:'PUBLIC_SOURCE'}])assert.throws(()=>h.verifyGalleryAsset(p.items[0],{...record(original.items[0],0),...changes}))});
test('fixed WebP content negotiation is sent on every actual harvest',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture();const request=f.api.request;f.api.request=async(route,options)=>{if(route.endsWith('/media/harvest'))assert.equal(JSON.stringify(options.body.request_headers),JSON.stringify({Accept:'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'}));return request(route,options)};await h.executeGalleryImport(f.api,p);assert.ok(p.items.every(x=>x.expected.mime_type==='image/webp'))});
test('actual HK first WebP is reused and only remaining thirty-nine are harvested',async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),f=fixture();const first=record(original.items[0],0);assert.equal(first.sha256,'973ff3e051d5707dd29c5e88c3d137c0dbffb5f815a9ba45e803de4b1e2cba08');assert.equal(first.byte_size,212140);assert.equal(first.width,2560);assert.equal(first.height,1920);assert.equal(first.mime_type,'image/webp');f.records.push(first);const result=await h.executeGalleryImport(f.api,p);assert.equal(result.reused,1);assert.equal(result.harvested,39);assert.equal(f.records.length,40);assert.ok(f.calls.filter(c=>c.options).every(c=>c.options.body.source_url!==first.source_url))});
test('arbitrary or omitted request headers and wrong expected hash reject before API calls',async()=>{const h=environment(),f=fixture();for(const headers of [{Accept:'image/jpeg'},{Accept:'image/webp',Cookie:'forbidden'},{Accept:'image/webp',Authorization:'forbidden'},undefined]){const altered=structuredClone(original);if(headers)altered.items[0].request.body.request_headers=headers;else delete altered.items[0].request.body.request_headers;await assert.rejects(async()=>{const p=await h.reviewedGalleryPlan(JSON.stringify(altered),hid);await h.executeGalleryImport(f.api,p)})}const altered=structuredClone(original);altered.items[0].expected.sha256='0'.repeat(64);await assert.rejects(()=>h.reviewedGalleryPlan(JSON.stringify(altered),hid));assert.equal(f.calls.length,0);assert.equal(f.postCount,0)});
test('legacy JPEG reviewed plan is rejected without network writes',async()=>{const h=environment(),legacy=fs.readFileSync(path.join(here,'fixtures/aoluguya_hyatt_gallery_harvest_plan_legacy_jpeg.json'),'utf8'),f=fixture();await assert.rejects(async()=>{const p=await h.reviewedGalleryPlan(legacy,hid);await h.executeGalleryImport(f.api,p)},/不一致/);assert.equal(f.calls.length,0)});

test("hero role is preserved and gallery substitution cannot be reused",async()=>{const h=environment(),p=await h.reviewedGalleryPlan(raw,hid),i=p.items.findIndex(x=>x.body.role==='HERO');assert.equal(i,21);assert.equal(p.items[i].display.category,'HERO_EXTERIOR');assert.throws(()=>h.verifyGalleryAsset(p.items[i],{...record(original.items[i],i),role:'GALLERY'}));const f=fixture();const result=await h.executeGalleryImport(f.api,p);assert.equal(result.assets.filter(x=>x.role==='HERO').length,1);assert.equal(result.assets.filter(x=>x.category==='Dining').length,9);assert.equal(result.assets[i].page_url,'https://www.hyatt.com/unbound-collection/en-US/hrbub-aoluguya')});

test("previous reviewed 21-image plan remains preserved but cannot execute as expanded 40",async()=>{const h=environment(),old=fs.readFileSync(path.join(here,"fixtures/aoluguya_hyatt_gallery_harvest_plan.json"),"utf8");assert.equal(JSON.parse(old).items.length,21);await assert.rejects(()=>h.reviewedGalleryPlan(old,hid),/不一致/)});
