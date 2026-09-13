from pathlib import Path
import json, sys
root=Path(__file__).resolve().parents[1]
app=json.loads((root/'mobile/go-app/app.json').read_text())['expo']
eas=json.loads((root/'mobile/go-app/eas.json').read_text())
errors=[]
for k in ['name','slug','scheme']:
    if not app.get(k): errors.append(f'missing app.{k}')
if not app.get('ios',{}).get('bundleIdentifier'): errors.append('missing ios.bundleIdentifier')
if not app.get('android',{}).get('package'): errors.append('missing android.package')
if 'production' not in eas.get('build',{}): errors.append('missing EAS production build profile')
if 'production' not in eas.get('submit',{}): errors.append('missing EAS production submit profile')
# Placeholder credentials are acceptable in source but block actual store certification.
placeholders=[]
text=(root/'mobile/go-app/eas.json').read_text()
for p in ['REPLACE_WITH_APP_STORE_CONNECT_APP_ID']:
    if p in text: placeholders.append(p)
print(json.dumps({'passed':not errors,'errors':errors,'credential_placeholders':placeholders},indent=2))
sys.exit(1 if errors else 0)
