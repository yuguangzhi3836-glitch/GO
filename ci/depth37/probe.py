"""Run isolated build readiness checks and retain every command outcome."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
root=Path.cwd(); evidence=root/'evidence'; evidence.mkdir(exist_ok=True)
def save(name,value): (evidence/name).write_text(json.dumps(value,indent=2)+'\n')
results=json.loads((evidence/'commands.json').read_text()) if (evidence/'commands.json').exists() else []
def run(name,args,cwd,timeout=900,env=None):
    start=time.monotonic()
    try:
        p=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
        code=p.returncode; output=p.stdout+p.stderr
    except subprocess.TimeoutExpired as exc:
        code=124; output='TIMEOUT\n'+str(exc.stdout or '')+str(exc.stderr or '')
    (evidence/(name+'.log')).write_text(output)
    result={'name':name,'exit_code':code,'seconds':round(time.monotonic()-start,2)}
    results.append(result);save('commands.json',results); print(json.dumps(result),flush=True)
    return code==0

source=root/'restored'; fp=json.loads((root/'candidate/deliverables/CP11_DEPTH36R3_MOBILE_CONTRACT_20260910/SOURCE_FINGERPRINT.json').read_text())
def verify():
    mismatch=[p for p,h in fp.items() if hashlib.sha256((source/p).read_bytes()).hexdigest()!=h]
    assert not mismatch,mismatch
verify()
save('source-binding.json',{'candidate':os.environ['SEALED_CANDIDATE'],'source_tree_sha256':'c58edb0c0568c3f9fe80ba014c260513a07a8e74b211b608ade4d9052f8645b3','files':len(fp),'phase':'BUILD_PROBE_NOT_RELEASE','deployed':False})
seal=root/'node-seal'
if os.environ.get('GO_BUILD_PHASE')!='mobile':
    (seal/'scripts').mkdir(parents=True);(seal/'gate_toolchain').mkdir()
    shutil.copyfile(source/'scripts/r317_provision_node_toolchain.sh',seal/'scripts/provision.sh')
    shutil.copyfile(root/'tooling/ci/depth37/NODE_SOURCE.json',seal/'gate_toolchain/NODE_SOURCE.json')
    sealed=run('node-seal',['sh',str(seal/'scripts/provision.sh')],seal)
    if not sealed:raise SystemExit('NODE_SEAL_FAILED')
node=seal/'gate_toolchain/node/bin/node';npm=seal/'gate_toolchain/node/bin/npm'
env=dict(os.environ,PATH=str(node.parent)+os.pathsep+os.environ['PATH'],CI='1',EXPO_NO_TELEMETRY='1')
manifest=json.loads((seal/'gate_toolchain/NODE_MANIFEST.json').read_text())
manifest['node_binary_sha256']=hashlib.sha256(node.read_bytes()).hexdigest()
save('node-manifest.json',manifest)
shutil.copyfile(seal/'.r317_node_build/download/node-v22.22.0-linux-x64.tar.xz',evidence/'node-v22.22.0-linux-x64.tar.xz')
tree={str(p.relative_to(seal/'gate_toolchain/node')):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((seal/'gate_toolchain/node').rglob('*')) if p.is_file()}
save('node-files.json',tree)
if os.environ.get('GO_BUILD_PHASE')!='mobile':
    tests=sorted(str(p) for p in (source/'tests_frontend').glob('*.test.*'))
    run('frontend-tests',[str(node),'--experimental-strip-types','--test',*tests],source,env=env)
    run('mobile-contract',[str(node),'scripts/contract-check.mjs'],source/'mobile/go-app',env=env)
    run('store-static',['python',str(source/'scripts/store_release_static_check.py')],source,env=env)
    verify()
    save('node-gate.json',{'node_seal':'PASS','commands':results,'source_after_checks':'PASS','final_release':'HOLD'})
    if os.environ.get('GO_BUILD_PHASE')=='node':
        raise SystemExit(0 if all(x['exit_code']==0 for x in results) else 1)
mobile=root/'mobile-build';shutil.copytree(source/'mobile/go-app',mobile)
locked=run('mobile-lock',[str(npm),'install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund'],mobile,env=env)
if locked:
    shutil.copyfile(mobile/'package-lock.json',evidence/'mobile-package-lock.json')
    installed=run('mobile-install',[str(npm),'ci','--no-audit','--no-fund'],mobile,env=env)
    if installed:
        run('mobile-typecheck',[str(node),'node_modules/typescript/bin/tsc','--noEmit'],mobile,env=env)
        run('mobile-export',[str(node),'node_modules/expo/bin/cli','export','--platform','all','--output-dir',str(evidence/'mobile-bundles')],mobile,env=env)
        prebuild=run('android-prebuild',[str(node),'node_modules/expo/bin/cli','prebuild','--platform','android','--no-install'],mobile,env=env)
        if prebuild:
            built=run('android-debug-build',['bash','./gradlew',':app:assembleDebug','--no-daemon','-PreactNativeArchitectures=x86_64'],mobile/'android',timeout=1200,env=env)
            if built:
                for p in (mobile/'android/app/build/outputs/apk').rglob('*.apk'):shutil.copyfile(p,evidence/p.name)
verify();save('source-after-build.json',{'source_after_build':'PASS','files':len(fp),'mismatches':[]})
save('gate-summary.json',{'node_seal':'PASS','commands':results,'native_device':'NOT_RUN','ios_build':'NOT_RUN','provider_external_certification':'NOT_RUN_MISSING_SANDBOX_INPUTS','browser':'DEFERRED_POST_DEPLOYMENT','six_vertical_e2e':'DEFERRED_POST_DEPLOYMENT','final_release':'HOLD','source_unchanged':True})
raise SystemExit(0 if all(x['exit_code']==0 for x in results) else 1)
