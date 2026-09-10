"""Verify an immutable APK on a clean emulator; no build or backend transactions."""
import hashlib,json,os,subprocess,time,xml.etree.ElementTree as ET
from pathlib import Path
root=Path.cwd();out=root/'evidence';out.mkdir(exist_ok=True);original=root/'original';results=[]
def save(name,data):(out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
def run(name,args,timeout=180,required=True):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    (out/(name+'.log')).write_text(p.stdout+p.stderr)
    results.append({'name':name,'exit_code':p.returncode,'pass':p.returncode==0});save('commands.json',results)
    print(name,p.returncode,flush=True)
    if required and p.returncode:raise RuntimeError(name+' failed')
    return p.stdout
binding=json.loads((original/'source-binding.json').read_text());assert binding['candidate']=='da6897706793fafd73d09cb56013586089733f4d';assert binding['source_tree_sha256']=='cf3f13960effa346337ed549cfb58ed6bae7aec94d05aba2e3b2f00d0b9df84c'
assert json.loads((original/'source-after-build.json').read_text())['source_after_build']=='PASS'
fp=json.loads((original/'artifact-fingerprints.json').read_text());apk=original/'app-release.apk';digest=hashlib.sha256(apk.read_bytes()).hexdigest();assert digest==fp[apk.name]['sha256'];assert apk.stat().st_size==fp[apk.name]['bytes']
save('artifact-binding.json',dict(binding,build_run=34476573746,apk_sha256=digest,rebuilt=False))
sdk=Path(os.environ['ANDROID_HOME']);adb=[str(sdk/'platform-tools/adb'),'-s','emulator-5554'];emulator=sdk/'emulator/emulator'
run('emulator-version',[str(emulator),'-version']);run('acceleration',[str(emulator),'-accel-check'])
with (out/'emulator.log').open('w') as log:
    proc=subprocess.Popen([str(emulator),'-avd','go_depth37','-port','5554','-no-window','-no-audio','-no-boot-anim','-no-snapshot','-gpu','swiftshader_indirect','-memory','2048','-cores','2'],stdout=log,stderr=subprocess.STDOUT)
    try:
        run('adb-ready',adb+['wait-for-device'],timeout=240)
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            p=subprocess.run(adb+['shell','getprop','sys.boot_completed'],capture_output=True,text=True,timeout=15)
            if p.stdout.strip()=='1':break
            if proc.poll() is not None:raise RuntimeError('EMULATOR_EXITED')
            time.sleep(3)
        else:raise RuntimeError('EMULATOR_BOOT_TIMEOUT')
        run('device-properties',adb+['shell','getprop'])
        run('unlock',adb+['shell','input','keyevent','82'])
        run('install',adb+['install','-r',str(apk)])
        run('clear-log',adb+['logcat','-c'])
        run('launch',adb+['shell','am','start','-W','-n','travel.go.consumer/.MainActivity'])
        time.sleep(30)
        run('process',adb+['shell','pidof','travel.go.consumer'])
        run('ui-dump',adb+['shell','uiautomator','dump','/sdcard/go-startup.xml'])
        run('ui-pull',adb+['pull','/sdcard/go-startup.xml',str(out/'login-ui.xml')])
        screen=subprocess.run(adb+['exec-out','screencap','-p'],capture_output=True,timeout=30);assert screen.returncode==0;(out/'android-login.png').write_bytes(screen.stdout)
        logtext=run('application-log',adb+['logcat','-d','-v','threadtime','ReactNativeJS:V','AndroidRuntime:E','*:S'])
        nodes=ET.parse(out/'login-ui.xml').getroot().iter('node');texts=[n.attrib.get('text','')+' '+n.attrib.get('content-desc','') for n in nodes];text='\n'.join(texts)
        rendered='GO' in text and '登录' in text and ('邮箱' in text or '密码' in text)
        fatal=any(term in logtext for term in ['FATAL EXCEPTION','Cannot find native module','Unhandled JS Exception'])
        save('startup-result.json',{'login_rendered':rendered,'fatal_startup':fatal,'texts':texts,'physical_device':'NOT_RUN','backend_journeys':'NOT_RUN','rebuilt':False})
        assert rendered and not fatal,'ANDROID_STARTUP_NOT_ACCEPTED'
    finally:
        subprocess.run(adb+['emu','kill'],capture_output=True,timeout=15)
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        save('artifact-fingerprints.json',{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in out.iterdir() if p.is_file() and p.name!='artifact-fingerprints.json'})
