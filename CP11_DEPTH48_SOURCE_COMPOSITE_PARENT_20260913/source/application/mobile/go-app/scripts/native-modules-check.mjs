// Verify SDK 53 autolinking from both JS and generated native working directories.
import {createRequire} from 'node:module';
import {dirname, resolve, relative, isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(resolve(root,'package.json'));
const manifest=require.resolve('expo-modules-autolinking/package.json');
const pkg=require(manifest);
const bin=typeof pkg.bin==='string'?pkg.bin:pkg.bin['expo-modules-autolinking'];
const required=['expo','expo-modules-core','expo-asset','expo-file-system','expo-font','expo-keep-awake'];
const native=process.argv.includes('--native');
for (const platform of ['apple','android']) {
  const nativeDir=resolve(root,platform==='apple'?'ios':'android');
  const contexts=[root];
  if(native && existsSync(nativeDir)) contexts.push(nativeDir);
  for(const cwd of contexts) {
    const p=spawnSync(process.execPath,[resolve(dirname(manifest),bin),'search','--json','--platform',platform],{cwd,encoding:'utf8'});
    if(p.status!==0)throw new Error('NATIVE_MODULE_SEARCH_FAILED: '+p.stderr);
    const found=JSON.parse(p.stdout);
    const missing=required.filter(name=>!found[name]);
    const outside=required.filter(name=>found[name]).filter(name=>{
      const path=relative(resolve(root,'node_modules'),found[name].path);
      return path==='..'||path.startsWith('../')||isAbsolute(path);
    });
    console.log(JSON.stringify({platform,cwd:relative(root,cwd)||'.',required,missing,outside,modules:Object.fromEntries(required.filter(name=>found[name]).map(name=>[name,{version:found[name].version,path:found[name].path}]))},null,2));
    if(missing.length||outside.length)throw new Error('INVALID_NATIVE_MODULE_GRAPH: '+platform+': '+JSON.stringify({missing,outside}));
  }
}
if(native && !existsSync(resolve(root,'ios')) && !existsSync(resolve(root,'android')))throw new Error('NATIVE_DIRECTORIES_REQUIRED');
