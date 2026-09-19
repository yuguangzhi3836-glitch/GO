const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/shared/app.js'),'utf8');
const code=source.slice(source.indexOf('const HOTEL_IMPORT_FIELDS='),source.indexOf('async function supplierPropertyProfile()'));
async function setup(){
 const nodes=new Map(),requests=[];let checked=[],failure=null,response={status:'IMPORTED',room_types_created:0};
 const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,files:[]});return nodes.get(id)};
 const ctx={$,console,document:{querySelectorAll:()=>checked.map(value=>({value}))},esc:x=>String(x??'').replace(/</g,'&lt;'),unwrap:x=>x?.data??x,supplierFriendlyValue:()=> '草稿',supplierStructuredShell:(_,body)=>body,notice:()=>{},window:{open:()=>{}},FileReader:class{readAsDataURL(){this.result='data:image/png;base64,aGVsbG8=';this.onload()}},api:{request:async(url,opts)=>{
  if(!opts)return url.endsWith('/providers')?{providers:{CTRIP:{label:'携程'}}}:[{property_id:'prop-test',name_zh:'测试酒店',publication_state:'DRAFT'}];
  requests.push({url,opts:JSON.parse(JSON.stringify(opts))});if(failure)throw new Error(failure);return response;
 }}};
 vm.createContext(ctx);vm.runInContext(code,ctx);await ctx.supplierOneClickBuild();$('#buildProvider').value='CTRIP';
 return {$,requests,select:x=>{checked=x},fail:x=>{failure=x},respond:x=>{response=x},ctx};
}
const pack={hotel:{name_zh:'新酒店',contacts:{phone:'123'},address:{city:'哈尔滨'}},room_types:[{name_zh:'房型',media:[{url:'https://example.test/old.jpg'}]}],media:[{url:'https://example.test/old.jpg'}]};
async function preview(s){s.$('#hotelPackage').value=JSON.stringify(pack);await s.$('#previewHotelPackage').onclick()}
test('preview is local and explicitly unsaved; only chosen fields are submitted without OTA images',async()=>{
 const s=await setup();await preview(s);assert.equal(s.requests.length,0);assert.match(s.$('#hotelImportStatus').textContent,/未保存/);
 s.select(['hotel.contacts','room_types']);await s.$('#importHotelPackage').onclick();
 const body=s.requests[0].opts.body;assert.deepEqual(body.selected_fields,['hotel.contacts','room_types']);
 assert.deepEqual(body.hotel_package,{hotel:{contacts:{phone:'123'}},room_types:[{name_zh:'房型'}]});assert.equal(body.hotel_package.media,undefined);
 assert.match(s.$('#hotelImportStatus').textContent,/所选资料已保存/);
});
test('empty selection and stale preview never write hotel data',async()=>{
 const s=await setup();await preview(s);await s.$('#importHotelPackage').onclick();assert.equal(s.requests.length,0);
 s.select(['hotel.name_zh']);s.$('#hotelPackage').value='{}';await s.$('#importHotelPackage').onclick();assert.equal(s.requests.length,0);assert.equal(s.$('#importHotelPackage').disabled,true);
});
test('failed import retains text and choices and suppresses internal error codes',async()=>{
 const s=await setup();await preview(s);s.select(['hotel.contacts']);s.fail('DATABASE_INTERNAL_FAILURE');await s.$('#importHotelPackage').onclick();
 assert.equal(s.$('#hotelPackage').value,JSON.stringify(pack));assert.match(s.$('#hotelImportStatus').textContent,/选择已保留/);assert.doesNotMatch(s.$('#hotelImportStatus').textContent,/DATABASE/);
 s.fail(null);await s.$('#importHotelPackage').onclick();assert.deepEqual(s.requests[1].opts.body.selected_fields,['hotel.contacts']);
});
test('unexpected import response cannot report success',async()=>{
 const s=await setup();await preview(s);s.select(['hotel.name_zh']);s.respond({status:'PROCESSING'});await s.$('#importHotelPackage').onclick();assert.doesNotMatch(s.$('#hotelImportStatus').textContent,/已保存/);
});
function selectPhoto(s){s.$('#hotelMediaFile').files=[{name:'hotel.png',type:'image/png',size:1024}];s.$('#hotelMediaRole').value='GALLERY';s.$('#hotelMediaHolder').value='酒店';s.$('#hotelMediaEvidence').value='自有摄影记录';s.$('#hotelMediaRights').checked=true}
test('direct image upload sends bytes and rights and reports verified dimensions as unpublished draft',async()=>{
 const s=await setup();selectPhoto(s);s.respond({asset_id:'asset-1',state:'DRAFT',width:1920,height:1080,publishable:false});await s.$('#uploadHotelMedia').onclick();
 assert.match(s.requests[0].url,/\/media-uploads$/);assert.equal(s.requests[0].opts.body.content_base64,'aGVsbG8=');assert.deepEqual(s.requests[0].opts.body.rights.usage_scope,['DISTRIBUTE_ON_GO']);assert.match(s.$('#hotelMediaStatus').textContent,/1920×1080/);assert.match(s.$('#hotelMediaStatus').textContent,/尚未发布/);
});
test('image rejection keeps file and rights available for retry with Chinese quality feedback',async()=>{
 const s=await setup();selectPhoto(s);s.fail('MEDIA_IMAGE_TOO_SMALL');await s.$('#uploadHotelMedia').onclick();assert.match(s.$('#hotelMediaStatus').textContent,/清晰度不足/);assert.equal(s.$('#hotelMediaFile').files[0].name,'hotel.png');assert.equal(s.$('#hotelMediaRights').checked,true);assert.equal(s.$('#uploadHotelMedia').disabled,false);
});
test('missing rights or oversized file never sends an upload',async()=>{
 const s=await setup();selectPhoto(s);s.$('#hotelMediaRights').checked=false;await s.$('#uploadHotelMedia').onclick();assert.equal(s.requests.length,0);
 s.$('#hotelMediaRights').checked=true;s.$('#hotelMediaFile').files[0].size=16*1024*1024;await s.$('#uploadHotelMedia').onclick();assert.equal(s.requests.length,0);
});
test('invalid JSON never enables confirmation',async()=>{
 const s=await setup();s.$('#hotelPackage').value='{';await s.$('#previewHotelPackage').onclick();assert.equal(s.$('#importHotelPackage').disabled,true);assert.equal(s.requests.length,0);
});
test('source room selection requires mapping confirmation without blocking hotel fields',async()=>{
 const s=await setup();s.$('#hotelPackage').value=JSON.stringify({hotel:{name_zh:'酒店'},room_types:[{source_room_id:'ota-1',name_zh:'套房'}]});
 await s.$('#previewHotelPackage').onclick();assert.match(s.$('#hotelImportPreview').innerHTML,/value="room_types" disabled/);
 s.select(['room_types']);await s.$('#importHotelPackage').onclick();assert.equal(s.requests.length,0);assert.match(s.$('#hotelImportStatus').textContent,/对应关系/);
 s.select(['hotel.name_zh']);await s.$('#importHotelPackage').onclick();assert.deepEqual(s.requests[0].opts.body.hotel_package,{hotel:{name_zh:'酒店'}});
});
test('malformed room collection cannot enable import',async()=>{
 for(const room_types of [{bad:true},[null],['room']]){const s=await setup();s.$('#hotelPackage').value=JSON.stringify({room_types});await s.$('#previewHotelPackage').onclick();assert.equal(s.$('#importHotelPackage').disabled,true);assert.match(s.$('#hotelImportStatus').textContent,/格式不正确/);assert.equal(s.requests.length,0)}
});
test('preview escapes supplied hotel markup',async()=>{
 const s=await setup();s.$('#hotelPackage').value=JSON.stringify({hotel:{name_zh:'<img src=x onerror=alert(1)>'}});await s.$('#previewHotelPackage').onclick();assert.doesNotMatch(s.$('#hotelImportPreview').innerHTML,/<img/);assert.match(s.$('#hotelImportPreview').innerHTML,/&lt;img/);
});
test('upload response must confirm nonpublished draft and valid dimensions',async()=>{
 for(const response of [{asset_id:'a',state:'DRAFT',width:1920,height:1080,publishable:true},{asset_id:'a',state:'DRAFT',width:-1,height:1080,publishable:false}]){const s=await setup();selectPhoto(s);s.respond(response);await s.$('#uploadHotelMedia').onclick();assert.doesNotMatch(s.$('#hotelMediaStatus').textContent,/上传成功/)}
});
test('double submission during pending import sends a single request',async()=>{
 const s=await setup();await preview(s);s.select(['hotel.name_zh']);let resolve;s.respond(new Promise(done=>resolve=done));
 const pending=s.$('#importHotelPackage').onclick();await s.$('#importHotelPackage').onclick();assert.equal(s.requests.length,1);resolve({status:'IMPORTED',room_types_created:0});await pending;assert.equal(s.$('#importHotelPackage').disabled,false);
});
