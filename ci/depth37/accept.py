"""Build the immutable source, recording commands and retaining blocked external gates."""
import hashlib,json,os,shutil,subprocess,sys,tarfile,time
from pathlib import Path
root=Path.cwd(); evidence=root/'evidence';evidence.mkdir(exist_ok=True)
source=root/'restored'; platform=sys.argv[1]; results=[]
def save(name,obj): (evidence/name).write_text(json.dumps(obj,indent=2)+'\n')
def run(name,args,cwd=source,env=None,timeout=1200,expected=0):
    start=time.monotonic()
    try:
        p=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
        code=p.returncode;output=p.stdout+p.stderr
    except subprocess.TimeoutExpired as exc:
        code=124;output='TIMEOUT\n'+str(exc.stdout or '')+str(exc.stderr or '')
    (evidence/(name+'.log')).write_text(output)
    item={'name':name,'exit_code':code,'expected_exit_code':expected,'pass':code==expected,'seconds':round(time.monotonic()-start,2)}
    results.append(item);save('commands.json',results);print(json.dumps(item),flush=True)
    return code==expected
package=root/'candidate/deliverables/CP11_DEPTH37_NODE_NATIVE_PROVIDER_20260910'
fp=json.loads((package/'SOURCE_FINGERPRINT.json').read_text());meta=json.loads((package/'MANIFEST.json').read_text())
def verify():
    mismatches=[p for p,h in fp.items() if not (source/p).is_file() or hashlib.sha256((source/p).read_bytes()).hexdigest()!=h]
    assert not mismatches,mismatches
verify();save('source-binding.json',{'candidate':os.environ['SEALED_CANDIDATE'],'source_tree_sha256':meta['source_tree_sha256'],'files':len(fp),'platform':platform,'deployed':False})
env=dict(os.environ,CI='1',EXPO_NO_TELEMETRY='1')
if platform=='android':
    seal=root/'node-seal';(seal/'scripts').mkdir(parents=True);(seal/'gate_toolchain').mkdir()
    for name in ['r317_provision_node_toolchain.sh','r82_gate_toolchain_integrity.py']:shutil.copyfile(source/'scripts'/name,seal/'scripts'/name)
    shutil.copyfile(source/'gate_toolchain/NODE_SOURCE.json',seal/'gate_toolchain/NODE_SOURCE.json')
    if not run('node-provision',['sh',str(seal/'scripts/r317_provision_node_toolchain.sh')],seal):raise SystemExit(1)
    node=seal/'gate_toolchain/node/bin/node';env['PATH']=str(node.parent)+os.pathsep+env['PATH']
    run('node-integrity',[sys.executable,str(seal/'scripts/r82_gate_toolchain_integrity.py')],seal,env)
    archive=seal/'.r317_node_build/download/node-v22.22.0-linux-x64.tar.xz'
    shutil.copyfile(archive,evidence/archive.name)
    shutil.copyfile(seal/'gate_toolchain/NODE_MANIFEST.json',evidence/'node-manifest.json')
    # Replay only the verified local archive; this step performs no download.
    replay=root/'node-replay';(replay/'scripts').mkdir(parents=True);(replay/'gate_toolchain/node').mkdir(parents=True)
    for name in ['NODE_SOURCE.json','NODE_MANIFEST.json']:shutil.copyfile(seal/'gate_toolchain'/name,replay/'gate_toolchain'/name)
    shutil.copyfile(seal/'scripts/r82_gate_toolchain_integrity.py',replay/'scripts/r82_gate_toolchain_integrity.py')
    with tarfile.open(archive) as tar:
        tar.extractall(replay,filter='data')
    shutil.rmtree(replay/'gate_toolchain/node');shutil.move(str(replay/'node-v22.22.0-linux-x64'),str(replay/'gate_toolchain/node'))
    replayenv=dict(env,PATH=str(replay/'gate_toolchain/node/bin')+os.pathsep+os.environ['PATH'])
    check=[sys.executable,str(replay/'scripts/r82_gate_toolchain_integrity.py')]
    run('node-offline-replay',check,replay,replayenv)
    tamper=replay/'gate_toolchain/node/DEPTH37_TAMPER_PROBE';tamper.write_text('must be rejected')
    run('node-reject-tampering',check,replay,replayenv,expected=1);tamper.unlink()
    run('node-reject-host-precedence',check,replay,env,expected=1)
    run('node-replay-restored',check,replay,replayenv)
    tests=sorted(str(p) for p in (source/'tests_frontend').glob('*.test.*'))
    run('frontend-tests',[str(node),'--experimental-strip-types','--test',*tests],source,env)
    run('provider-contract',[sys.executable,'scripts/r82_provider_adapter_contract_gate.py'],source,env)
    run('provider-input-tests',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_depth37_provider_preflight.py','-v'],source,env)
    run('provider-input-preflight',[sys.executable,'scripts/provider_certification_preflight.py','--evidence',str(evidence/'provider-inputs.json')],source,env,expected=2)
else:
    node=Path(shutil.which('node'));run('ios-node-version',[str(node),'--version'],source,env)
    run('xcode-version',['xcodebuild','-version'],source,env)
mobile=root/'mobile-build';shutil.copytree(source/'mobile/go-app',mobile)
npm=str(node.parent/'npm')
installed=run('mobile-install',[npm,'ci','--no-audit','--no-fund'],mobile,env)
if installed:
    run('mobile-typecheck',[str(node),'node_modules/typescript/bin/tsc','--noEmit'],mobile,env)
    run('mobile-contract',[str(node),'scripts/contract-check.mjs'],mobile,env)
    cli=[str(node),'node_modules/expo/bin/cli']
    exported=run('mobile-export',cli+['export','--platform',platform,'--output-dir','dist'],mobile,env)
    if exported:
        with tarfile.open(evidence/(platform+'-metro-bundle.tar.gz'),'w:gz') as tar:tar.add(mobile/'dist',arcname='dist')
    prebuilt=run('native-prebuild',cli+['prebuild','--platform',platform,'--no-install'],mobile,env)
    if prebuilt and platform=='android':
        built=run('android-bundled-build',['bash','./gradlew',':app:assembleRelease','--no-daemon','-PreactNativeArchitectures=x86_64'],mobile/'android',env,timeout=1500)
        if built:
            for p in (mobile/'android/app/build/outputs/apk').rglob('*.apk'):shutil.copyfile(p,evidence/p.name)
            save('android-package-scope.json',{'configuration':'Release','signing':'Expo generated debug keystore; internal CI only','architecture':'x86_64','physical_device':'NOT_RUN','store_release':'NOT_AUTHORIZED'})
    elif prebuilt:
        pods=run('ios-pods',['pod','install'],mobile/'ios',env,timeout=900)
        if pods:
            workspaces=list((mobile/'ios').glob('*.xcworkspace'));assert len(workspaces)==1
            workspace=workspaces[0]
            built=run('ios-simulator-build',['xcodebuild','-workspace',workspace.name,'-scheme',workspace.stem,'-configuration','Release','-sdk','iphonesimulator','-destination','generic/platform=iOS Simulator','-derivedDataPath',str(root/'ios-derived'),'CODE_SIGNING_ALLOWED=NO','build'],mobile/'ios',env,timeout=1800)
            if built:
                apps=list((root/'ios-derived/Build/Products/Release-iphonesimulator').glob('*.app'));assert len(apps)==1
                with tarfile.open(evidence/'ios-simulator-app.tar.gz','w:gz') as tar:tar.add(apps[0],arcname=apps[0].name)
                devices=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','available','-j'],text=True))['devices']
                iphones=[d for ds in devices.values() for d in ds if d['name'].startswith('iPhone')]
                assert iphones,'NO_IPHONE_SIMULATOR';device=iphones[0]['udid']
                if iphones[0]['state']!='Booted':run('ios-simulator-boot',['xcrun','simctl','boot',device],mobile,env)
                if run('ios-simulator-ready',['xcrun','simctl','bootstatus',device,'-b'],mobile,env,timeout=180):
                    run('ios-simulator-install',['xcrun','simctl','install',device,str(apps[0])],mobile,env)
                    run('ios-simulator-launch',['xcrun','simctl','launch',device,'travel.go.consumer'],mobile,env)
                    run('ios-simulator-screenshot',['xcrun','simctl','io',device,'screenshot',str(evidence/'ios-simulator.png')],mobile,env)
                    save('ios-simulator-scope.json',{'device':iphones[0]['name'],'udid':device,'checks':'install and launch only; no backend journey','physical_device':'NOT_RUN'})
verify();save('source-after-build.json',{'source_after_build':'PASS','files':len(fp),'mismatches':[]})
save('gate-summary.json',{'commands':results,'physical_devices':'NOT_RUN_MISSING_DEVICE_ENVIRONMENT','provider_external_certification':'NOT_RUN_MISSING_SANDBOX_INPUTS','browser':'DEFERRED_POST_DEPLOYMENT','six_vertical_e2e':'DEFERRED_POST_DEPLOYMENT','final_release':'HOLD','source_unchanged':True})
save('artifact-fingerprints.json',{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in evidence.iterdir() if p.is_file()})
raise SystemExit(0 if all(x['pass'] for x in results) else 1)
