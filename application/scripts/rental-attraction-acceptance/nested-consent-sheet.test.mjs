import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const path=new URL('../../frontend/consumer/app.js',import.meta.url);
const source=fs.readFileSync(path,'utf8'),hash=s=>createHash('sha256').update(s).digest('hex'),before=hash(source);
const functions=source.slice(source.indexOf('function uxCloseSheet()'),source.indexOf('function uxConfirm('));
let attached=[];
const document={querySelector:()=>attached[0]||null,body:{appendChild:w=>attached.push(w)},createElement:()=>{
 const cancel={},confirm={};const wrap={innerHTML:'',querySelector:q=>q==='#uxCancel'?cancel:q==='#uxConfirm'?confirm:null,remove:()=>{attached=attached.filter(w=>w!==wrap);}};return wrap;
}};
const ctx={document,uxEsc:x=>String(x),setTimeout:()=>{},toast:()=>{}};vm.createContext(ctx);vm.runInContext(functions,ctx);
let accepted=0;
ctx.uxSheet({title:'first',onConfirm:async()=>{ctx.uxSheet({title:'second',onConfirm:async()=>{accepted++;}});}});
const first=attached[0];await first.querySelector('#uxConfirm').onclick();assert.equal(attached.length,1);assert.notEqual(attached[0],first);assert.match(attached[0].innerHTML,/second/);assert.equal(accepted,0);
await attached[0].querySelector('#uxConfirm').onclick();assert.equal(accepted,1);assert.equal(attached.length,0);
ctx.uxSheet({title:'failure',onConfirm:async()=>{throw Error('failure');}});const failed=attached[0];await failed.querySelector('#uxConfirm').onclick();assert.equal(attached[0],failed);assert.equal(failed.querySelector('#uxConfirm').disabled,false);
assert.equal(hash(fs.readFileSync(path,'utf8')),before);console.log(JSON.stringify({result:'PASS',tests:2,mode:'ACTUAL_UI_CALLBACK_STUB_NOT_BROWSER',scenarios:['nested_confirmation_requires_second_click','failure_keeps_current_confirmation'],app_js_sha256:before}));
