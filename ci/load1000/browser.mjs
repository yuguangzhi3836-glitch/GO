import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {userJourney} from './journey.mjs';

const out=process.env.GO_LOAD_EVIDENCE,state=process.env.GO_JOURNEY_STATE;
const binding=JSON.parse(await fs.readFile(path.join(out,'source-binding.json'),'utf8'));
const fixtures={credentials:JSON.parse(await fs.readFile(path.join(state,'credentials.private.json'),'utf8')),
 suppliers:JSON.parse(await fs.readFile(path.join(state,'suppliers.private.json'),'utf8'))};
const verticals=['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION'];
const stages=[{users:6,concurrency:1},{users:54,concurrency:2},{users:240,concurrency:4},{users:700,concurrency:8}];
const started_at=new Date().toISOString(),results=[],stageResults=[];
const browser=await chromium.launch({headless:true});
let nextIndex=1,stopped=false,fatal=null;
try {
  for(const stage of stages){
    const record={...stage,started_at:new Date().toISOString(),attempted:0};stageResults.push(record);
    const end=nextIndex+stage.users;
    await Promise.all(Array.from({length:stage.concurrency},async()=>{
      while(nextIndex<end&&!stopped){
        const index=nextIndex++;record.attempted++;
        try {
          const result=await userJourney(browser,index,verticals[(index-1)%6],out,fixtures,binding);
          results.push(result);if(result.result!=='PASS')stopped=true;
        }catch(error){stopped=true;fatal=String(error.stack||error);}
      }
    }));
    record.finished_at=new Date().toISOString();record.result=stopped?'STOPPED_ON_FAILURE':'PASS';
    console.log(JSON.stringify({stage:record,total:results.length}));
    if(stopped)break;
  }
}finally {
  await browser.close();
  const latencies=results.flatMap(x=>x.latencies||[]).map(x=>x.response_ms).filter(Number.isFinite).sort((a,b)=>a-b);
  const quantile=q=>latencies.length?latencies[Math.min(latencies.length-1,Math.ceil(q*latencies.length)-1)]:null;
  const checks=results.flatMap(r=>r.order_checks.map(c=>({...c,user_id:r.user_id,user_index:r.user_index})));
  const uniqueUsers=new Set(results.map(r=>r.user_id).filter(Boolean)).size;
  const summary={...binding,schema:'go.depth48-1000-browser.v1',started_at,finished_at:new Date().toISOString(),
    requested_users:1000,attempted_users:stageResults.reduce((n,s)=>n+s.attempted,0),registered_unique_users:uniqueUsers,
    completed_users:results.filter(x=>x.result==='PASS').length,failed_users:results.filter(x=>x.result!=='PASS').length,
    planned_concurrency:[1,2,4,8],stages:stageResults,
    modules:Object.fromEntries(verticals.map(v=>[v,{attempted:results.filter(x=>x.vertical===v).length,passed:results.filter(x=>x.vertical===v&&x.result==='PASS').length}])),
    latency:{scope:'same-origin browser API requests; responseEnd milliseconds',samples:latencies.length,p50_ms:quantile(.5),p95_ms:quantile(.95),p99_ms:quantile(.99)},
    http_status_counts:results.flatMap(x=>x.network).reduce((a,r)=>(a[r.status]=(a[r.status]||0)+1,a),{}),
    http_error_note:'Includes deliberate negative confirmation checks; journey failure count is separate.',
    environment:'GITHUB_HOSTED_ISOLATED_SQLITE_CHROMIUM',hong_kong_load:'NOT_RUN',production:'NOT_ACCESSED',
    interpretation:'1000 cumulative distinct consumer accounts, one module each; not 1000 concurrent users or HK capacity certification.',
    advanced_change_scope:'Not repeated per load user; separate fixed-source preflight evidence only.',
    screenshot_policy:'All first six users, every 100th user, and failures; raw per-user results for all attempts.',
    fatal_error:fatal,order_checks:checks,
    result:!stopped&&uniqueUsers===1000&&checks.length===1000&&results.every(x=>x.result==='PASS')?'BROWSER_SCOPE_PASS':'HOLD'};
  await fs.writeFile(path.join(out,'browser-results.json'),JSON.stringify(summary,null,2)+'\n');
  console.log(JSON.stringify({...summary,order_checks:undefined}));
  process.exitCode=summary.result==='BROWSER_SCOPE_PASS'?0:1;
}
