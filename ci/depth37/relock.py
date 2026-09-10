import json,shutil,subprocess,hashlib
from pathlib import Path
root=Path.cwd(); out=root/'evidence'; app=root/'mobile-relock'
shutil.copytree(root/'restored/mobile/go-app',app)
p=app/'package.json'; data=json.loads(p.read_text());data.pop('expo',None)
data['dependencies'].update({'expo-asset':'11.1.7','expo-file-system':'18.1.11','expo-font':'13.3.2','expo-keep-awake':'14.1.4'})
p.write_text(json.dumps(data,indent=2)+'\n')
result=subprocess.run(['npm','install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund'],cwd=app,capture_output=True,text=True,timeout=300)
(out/'dependency-lock.log').write_text(result.stdout+result.stderr)
if result.returncode: raise SystemExit(result.returncode)
for name in ['package.json','package-lock.json']:shutil.copyfile(app/name,out/name)
lock=json.loads((app/'package-lock.json').read_text())
required=['expo-asset','expo-file-system','expo-font','expo-keep-awake','expo-modules-core']
missing=[n for n in required if 'node_modules/'+n not in lock['packages']]
(out/'lock-layout.json').write_text(json.dumps({'required':required,'missing':missing,'versions':{n:lock['packages'].get('node_modules/'+n,{}).get('version') for n in required}},indent=2)+'\n')
assert not missing,missing
print('LOCK_GENERATED_ROOT_MODULES_PASS')
