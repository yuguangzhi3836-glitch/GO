// Isolated handler test; DOM/API doubles, not a browser or live inventory test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'frontend/consumer/flight-journeys.js'),'utf8');
const elements=new Map();let fields=[],calls=[],html='';
function el(selector){if(!elements.has(selector))elements.set(selector,{value:'',textContent:'',disabled:false});return elements.get(selector)}
Object.defineProperty(el('#app'),'innerHTML',{get:()=>html,set:v=>{html=v;}});
const kinds=['ONE_WAY','ROUND_TRIP','MULTI_CITY'].map(kind=>({dataset:{kind}}));
const sandbox={state:{},window:{},Date,console,uxEsc:s=>String(s),showHome(){},
 $:el,document:{body:{classList:{add(){},remove(){}}},querySelector:el,querySelectorAll:s=>s==='[data-kind]'?kinds:s==='[data-j-field]'?fields:[]},
 api:async(url,opts)=>{calls.push({url,body:JSON.parse(opts.body)});throw Error('TEST_STOP_AFTER_SEARCH_REQUEST')}};
vm.createContext(sandbox);vm.runInContext(source,sandbox);sandbox.showFlightSearch();
assert(!html.includes('模拟体验'));assert(!html.includes('测试数据'));assert(!html.includes('<b>服务状态</b>'));
assert(html.includes('可输入城市、机场名称或三字码'));
const inputs=[...html.matchAll(/<input[^>]*data-j-field="(?:origin|destination)"[^>]*>/g)].map(x=>x[0]);
assert(inputs.length===4);assert(inputs.every(x=>!x.includes('pattern=')&&x.includes('maxlength="120"')));
el('#jAdults').value='1';
kinds[0].onclick();
fields=[['origin','福州'],['destination','哈尔滨'],['departure_date','2026-10-02']].map(([jField,value])=>({dataset:{leg:'0',jField},value}));
(async()=>{
 await el('#jSearch').onsubmit({preventDefault(){}});
 assert.equal(calls.length,1);assert.equal(calls[0].url,'/v1/flights/journeys/search');
 assert.deepEqual(calls[0].body.legs,[{origin:'福州',destination:'哈尔滨',departure_date:'2026-10-02'}]);
 fields[1].value='福州';await el('#jSearch').onsubmit({preventDefault(){}});
 assert.equal(calls.length,1);assert.equal(el('#jError').textContent,'出发与到达机场不能相同。');
 // Product truth remains available at the quote/order stages.
 assert(source.includes('当前报价未连接航空公司实时库存，不可实际出行。'));
 assert(source.includes('当前订单未连接航空公司出票服务，不可实际出行。'));
 const index=fs.readFileSync(path.join(root,'frontend/consumer/index.html'),'utf8');
 assert(index.includes('flight-journeys.js?v=20261001-flight-search-release'));
 console.log('PASS: search render, Chinese handler payload, same-route refusal, quote/order truth, cache version');
})().catch(e=>{console.error(e);process.exitCode=1});
