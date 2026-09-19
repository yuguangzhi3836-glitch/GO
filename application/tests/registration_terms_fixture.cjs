const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const id='consumer_service_terms',hash='a'.repeat(64);
const document={id,title:'测试服务条款',version:'approved-v1',sha256:hash,status:'APPROVED',content_url:'/v1/registration-terms/'+id+'/approved-v1',content:'完整服务条款正文\n第二段。'};
const policy={enabled:true,acceptance_enabled:true,terms:{[id]:document.version},versions:{[id]:document.version},term_hashes:{[id]:hash},documents:[document]};
function element(){return {style:{},children:[],appendChild(child){this.children.push(child)},setAttribute(){},isConnected:true}}
function install(ctx){ctx.document.createElement=element;vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/shared/registration-terms.js'),'utf8'),ctx)}
module.exports={document,policy,element,install};
