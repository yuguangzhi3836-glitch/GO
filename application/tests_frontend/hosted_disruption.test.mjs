import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const admin={window:{GO_CONSOLE:{nav:[]}},Intl};
vm.runInNewContext(fs.readFileSync('frontend/admin/hosted-disruption.js','utf8'),admin);
const ui=admin.window.GOHostedDisruption;
function form({confirmed=true,ids=['proof-one'],cause='NO_ROOM',reference=' signed review '}={}){
 return {elements:{confirmed:{checked:confirmed},confirmed_cause:{value:cause},decision_reference:{value:reference}},querySelectorAll(){return ids.map(value=>({value}))}};
}
test('independent review requires an explicit checked attestation and chosen proof',()=>{
 const c={evidence_hash:'current-snapshot'};
 assert.throws(()=>ui.reviewBody(c,form({confirmed:false})),/独立检查/);
 assert.throws(()=>ui.reviewBody(c,form({ids:[]})),/证据/);
 assert.throws(()=>ui.reviewBody(c,form({cause:''})),/独立原因/);
 assert.throws(()=>ui.reviewBody(c,form({reference:' '})),/独立原因/);
});
test('review submits the exact evidence snapshot and no caller-selected money',()=>{
 const result=JSON.parse(JSON.stringify(ui.reviewBody({evidence_hash:'current-snapshot'},form())));
 assert.deepEqual(result,{confirmed_cause:'NO_ROOM',accepted_evidence_ids:['proof-one'],decision_reference:'signed review',expected_evidence_hash:'current-snapshot'});
 assert.ok(admin.window.GO_CONSOLE.nav.some(x=>x.custom==='hostedSupplierDisruption'));
});
const consumer={window:{},Intl};
vm.runInNewContext(fs.readFileSync('frontend/consumer/direct-after-sales.js','utf8'),consumer);
const card=consumer.window.GODirectAfterSales.disruption;
const approved={state:'COMPENSATION_PENDING',actual_paid_minor:162001,refund_due_minor:162001,compensation_due_minor:162001,refund_state:'REFUND_CONFIRMED_SIMULATION',compensation_state:'PENDING',retry_allowed:true};
test('customer sees completed original refund separately from pending extra payment',()=>{
 const html=card(approved,'CNY');
 for(const label of ['额外赔付待完成','退款已完成','额外赔付：待完成','1,620.01','retrySupplierRemedy','不发生真实交易'])assert.ok(html.includes(label));
 for(const label of ['bank_debit','negative_balance','protection_fund'])assert.equal(html.includes(label),false);
});
test('unapproved guest liability is a review hold without a refund promise or pay button',()=>{
 const html=card({state:'GUEST_LIABILITY_POLICY_REQUIRED',actual_paid_minor:162000,refund_due_minor:null,compensation_due_minor:null,refund_state:'NOT_APPROVED',retry_allowed:false},'CNY');
 assert.ok(html.includes('正在复核住客责任条款'));assert.ok(html.includes('以审核通过的规则为准'));
 assert.equal(html.includes('本次退回原款'),false);assert.equal(html.includes('retrySupplierRemedy'),false);
});
test('zero captured payment explains authorization release and completed case has no retry',()=>{
 const html=card({...approved,state:'COMPLETED',actual_paid_minor:0,refund_due_minor:0,compensation_due_minor:0,compensation_state:'NOT_REQUIRED',retry_allowed:false},'CNY');
 assert.ok(html.includes('未扣取的授权会释放'));assert.ok(html.includes('不适用'));assert.equal(html.includes('retrySupplierRemedy'),false);
});

const finance={window:{},Intl};
vm.runInNewContext(fs.readFileSync('frontend/admin/hosted-fault-finance.js','utf8'),finance);
test('finance entry converts decimal currency without fractional cents or silent rounding',()=>{
 const minor=finance.window.GOHostedFaultFinance.minor;
 assert.equal(minor('1620.01'),162001);assert.equal(minor(' 0.10 '),10);assert.equal(minor('1'),100);
 for(const bad of ['0','-1','1.001','1e3','NaN','12,300','9007199254740991',''])assert.throws(()=>minor(bad));
});
