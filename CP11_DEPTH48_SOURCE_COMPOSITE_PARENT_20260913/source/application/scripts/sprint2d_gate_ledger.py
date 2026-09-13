from __future__ import annotations
import argparse, hashlib, json, pathlib
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).resolve().parents[1]
LEDGER=ROOT/'staging'/'certification'/'status.sprint2d.json'
GATES=['PG16','REDIS','PSP','CONNECTOR','APNS','FCM','UNIVERSAL_LINK','APP_LINK','APPLE_SIGNING','GOOGLE_SIGNING','TESTFLIGHT','PLAY_INTERNAL','IPHONE_E2E','ANDROID_E2E','STORE_CHECKLIST']

def load():
    if LEDGER.exists(): return json.loads(LEDGER.read_text())
    return {'release':'GO Mobile Sprint 2D','state':'BLOCKED','gates':{g:{'status':'BLOCKED','evidence':None} for g in GATES},'updated_at':None}
def main():
    p=argparse.ArgumentParser(); p.add_argument('--gate',choices=GATES); p.add_argument('--pass-evidence'); p.add_argument('--block-reason'); p.add_argument('--show',action='store_true'); a=p.parse_args()
    d=load()
    if a.gate:
        if a.pass_evidence:
            ev=pathlib.Path(a.pass_evidence)
            if not ev.is_file(): raise SystemExit('evidence file not found')
            digest=hashlib.sha256(ev.read_bytes()).hexdigest()
            d['gates'][a.gate]={'status':'PASS','evidence':str(ev.relative_to(ROOT) if ev.is_relative_to(ROOT) else ev),'sha256':digest}
        elif a.block_reason:
            d['gates'][a.gate]={'status':'BLOCKED','reason':a.block_reason,'evidence':None}
        else: raise SystemExit('provide --pass-evidence or --block-reason')
    blocked=[g for g,v in d['gates'].items() if v.get('status')!='PASS']
    d['state']='INSTALLABLE_INTERNAL' if not blocked else 'BLOCKED'
    d['blocked']=blocked; d['updated_at']=datetime.now(timezone.utc).isoformat()
    LEDGER.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(d,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
