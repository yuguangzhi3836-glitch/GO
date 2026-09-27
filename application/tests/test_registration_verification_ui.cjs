const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(request){
 const nodes={};for(const id of ['registrationCode','sendRegistrationCode','registrationCodeStatus'])nodes['#'+id]={value:'',focus(){}};
 const form={isConnected:true,querySelector:id=>nodes[id]};
 const email={value:'one@example.test',reportValidity:()=>true,addEventListener(event,fn){this[event]=fn}};
 const accepted={checked:true,addEventListener(event,fn){this[event]=fn}};
 const ctx={setTimeout:()=>0,clearTimeout(){}};vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/shared/registration-verification.js','utf8'),ctx);
 const controller=ctx.GORegistrationVerification.mount({form,email,accepted,policy:()=>({enabled:true,versions:{v:'1'},hashes:{v:'hash'}}),request,audience:'consumer'});
 return {nodes,form,email,accepted,controller};
}
test('code must be requested and is bound to unchanged address',async()=>{
 const s=setup(async()=>({challenge_id:'id',resend_after:60}));assert.throws(()=>s.controller.payload(),/先获取/);
 await s.nodes['#sendRegistrationCode'].onclick();s.nodes['#registrationCode'].value='123456';
 assert.equal(s.controller.payload().challenge_id,'id');s.email.value='two@example.test';s.email.input();
 assert.throws(()=>s.controller.payload(),/先获取/);
});
test('late delivery result after editing email is discarded',async()=>{
 let finish;const s=setup(()=>new Promise(r=>finish=r));const p=s.nodes['#sendRegistrationCode'].onclick();
 s.email.value='new@example.test';s.email.input();finish({challenge_id:'old'});await p;
 assert.throws(()=>s.controller.payload(),/先获取/);assert.match(s.nodes['#registrationCodeStatus'].textContent,/邮箱变化/);
});
test('failed sending is visible and cannot submit or immediately spam',async()=>{
 const s=setup(async()=>{throw Error('REGISTRATION_EMAIL_SEND_FAILED')});await s.nodes['#sendRegistrationCode'].onclick();
 assert.match(s.nodes['#registrationCodeStatus'].textContent,/发送未完成/);assert.equal(s.nodes['#sendRegistrationCode'].disabled,true);
 assert.throws(()=>s.controller.payload(),/先获取/);
});
test('missing consent blocks mail and double click sends once',async()=>{
 let finish,count=0;const s=setup(()=>{count++;return new Promise(r=>finish=r)});
 s.accepted.checked=false;s.accepted.change();await s.nodes['#sendRegistrationCode'].onclick();assert.equal(count,0);
 s.accepted.checked=true;s.accepted.change();const pending=s.nodes['#sendRegistrationCode'].onclick();await s.nodes['#sendRegistrationCode'].onclick();assert.equal(count,1);finish({challenge_id:'id'});await pending;
});
