const fs=require('node:fs'),path=require('node:path');
const {babelParse}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/lib/transform/babelBundle.js');
const root=process.argv[2];let total=0;
function walk(p){for(const e of fs.readdirSync(p,{withFileTypes:true})){const q=path.join(p,e.name);if(e.isDirectory())walk(q);else if(/\.tsx?$/.test(q)){babelParse(fs.readFileSync(q,'utf8'),q);total++;}}}
walk(path.join(root,'mobile/go-app/src'));
const app=path.join(root,'mobile/go-app/App.tsx');babelParse(fs.readFileSync(app,'utf8'),app);
console.log(JSON.stringify({parsed:total+1,scope:'TS/TSX syntax parsing only; no typecheck, Metro, browser or device execution',parser:'bundled Babel parser',started_source:root,completed_at_utc:new Date().toISOString()}));
