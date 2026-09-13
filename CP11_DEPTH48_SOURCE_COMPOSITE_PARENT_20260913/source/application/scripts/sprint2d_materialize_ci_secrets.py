from __future__ import annotations
import base64, os, pathlib, sys
pairs={
 'ASC_API_KEY_B64':('ASC_API_KEY_PATH','asc_api_key.p8'),
 'APNS_AUTH_KEY_B64':('APNS_AUTH_KEY_PATH','apns_auth_key.p8'),
 'GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_B64':('GOOGLE_PLAY_SERVICE_ACCOUNT_JSON','google-play-service-account.json'),
 'FIREBASE_SERVICE_ACCOUNT_JSON_B64':('FIREBASE_SERVICE_ACCOUNT_JSON','firebase-service-account.json'),
}
root=pathlib.Path(os.getenv('RUNNER_TEMP','/tmp'))/'go-sprint2d-secrets'; root.mkdir(parents=True,exist_ok=True)
env_file=os.getenv('GITHUB_ENV')
lines=[]
for source,(target,name) in pairs.items():
    value=os.getenv(source,'').strip()
    if not value: continue
    try: data=base64.b64decode(value,validate=True)
    except Exception as e: raise SystemExit(f'invalid base64 for {source}: {e}')
    path=root/name; path.write_bytes(data); path.chmod(0o600); lines.append(f'{target}={path}')
if env_file and lines:
    with open(env_file,'a',encoding='utf-8') as f: f.write('\n'.join(lines)+'\n')
for line in lines: print(line.split('=',1)[0]+'=<materialized>')
