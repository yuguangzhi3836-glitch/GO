from __future__ import annotations
import argparse, json, os, pathlib, socket, ssl, sys, urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'staging' / 'bringup' / 'preflight.local.json'

SECRET_FILE_VARS = [
    'ASC_API_KEY_PATH','APNS_AUTH_KEY_PATH','GOOGLE_PLAY_SERVICE_ACCOUNT_JSON','FIREBASE_SERVICE_ACCOUNT_JSON'
]
REQUIRED_ENV = {
    'PG16':['STAGING_DATABASE_URL'],
    'REDIS':['STAGING_REDIS_URL'],
    'PSP':['PSP_PROVIDER','PSP_SANDBOX_API_KEY'],
    'CONNECTOR':['REAL_CONNECTOR_ID','REAL_CONNECTOR_BASE_URL','REAL_CONNECTOR_CREDENTIAL'],
    'APPLE_SIGNING':['EXPO_TOKEN','EXPO_PUBLIC_EAS_PROJECT_ID','APPLE_TEAM_ID','ASC_APP_ID','ASC_API_KEY_ID','ASC_API_KEY_ISSUER_ID','ASC_API_KEY_PATH'],
    'GOOGLE_SIGNING':['EXPO_TOKEN','EXPO_PUBLIC_EAS_PROJECT_ID','GOOGLE_PLAY_PACKAGE_NAME','GOOGLE_PLAY_SERVICE_ACCOUNT_JSON'],
    'APNS':['APPLE_TEAM_ID','APNS_KEY_ID','APNS_AUTH_KEY_PATH'],
    'FCM':['FIREBASE_PROJECT_ID','FIREBASE_SERVICE_ACCOUNT_JSON'],
    'UNIVERSAL_LINK':['GO_APP_DOMAIN','IOS_BUNDLE_ID','APPLE_ASSOCIATION_URL'],
    'APP_LINK':['GO_APP_DOMAIN','ANDROID_PACKAGE_NAME','ANDROID_SHA256_CERT_FINGERPRINT','ANDROID_ASSOCIATION_URL'],
}

def present(name:str)->bool:
    v=os.getenv(name,'').strip()
    if not v: return False
    if name in SECRET_FILE_VARS:
        return pathlib.Path(v).is_file() and pathlib.Path(v).stat().st_size > 0
    return True

def url_probe(url:str):
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'GO-Sprint2D-Certifier/1.0'})
        with urllib.request.urlopen(req,timeout=8,context=ssl.create_default_context()) as r:
            body=r.read(1_000_000)
            return {'reachable':True,'status':r.status,'content_type':r.headers.get('content-type'),'bytes':len(body)}
    except Exception as e:
        return {'reachable':False,'error':type(e).__name__+': '+str(e)[:240]}

def main():
    parser = argparse.ArgumentParser(description='Check bringup prerequisites without executing deployment.')
    parser.add_argument('--output', type=pathlib.Path, default=OUT,
                        help='Report destination (use a writable temporary path for isolated tests).')
    out = parser.parse_args().output
    result={'generated_at':datetime.now(timezone.utc).isoformat(),'gates':{},'network_probes':{}}
    for gate,names in REQUIRED_ENV.items():
        missing=[n for n in names if not present(n)]
        result['gates'][gate]={'credential_preflight':'PASS' if not missing else 'BLOCKED','missing':missing}
    for key in ('APPLE_ASSOCIATION_URL','ANDROID_ASSOCIATION_URL','PSP_SANDBOX_HEALTH_URL'):
        url=os.getenv(key,'').strip()
        if url:
            result['network_probes'][key]=url_probe(url)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    blocked=[g for g,v in result['gates'].items() if v['credential_preflight']!='PASS']
    print(json.dumps({'state':'READY_FOR_LIVE_EXECUTION' if not blocked else 'BLOCKED_CREDENTIALS','blocked':blocked,'report':str(out)},indent=2))
    return 0 if not blocked else 2
if __name__=='__main__': sys.exit(main())
