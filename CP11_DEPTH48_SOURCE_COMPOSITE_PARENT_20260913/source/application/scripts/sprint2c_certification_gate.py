from __future__ import annotations
import argparse, json, os, socket, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GATES=["PG16","REDIS","PSP","CONNECTOR","APNS","FCM","UNIVERSAL_LINK","APP_LINK","APPLE_SIGNING","GOOGLE_SIGNING","TESTFLIGHT","PLAY_INTERNAL","IPHONE_E2E","ANDROID_E2E","STORE_CHECKLIST"]

def tcp(host,port,timeout=2):
    try:
        with socket.create_connection((host,int(port)),timeout=timeout): return True
    except Exception:return False

def http(url,timeout=5):
    try:
        with urllib.request.urlopen(url,timeout=timeout) as r:return 200 <= r.status < 400
    except Exception:return False

def truthy(name): return os.getenv(name,"").lower() in {"1","true","yes","pass"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",default=str(ROOT/"staging/certification/status.generated.json")); args=ap.parse_args()
    status={g:{"status":"BLOCKED","evidence":None} for g in GATES}
    # These checks intentionally require real environment evidence rather than accepting local mocks.
    pg_host=os.getenv("STAGING_POSTGRES_HOST"); pg_port=os.getenv("STAGING_POSTGRES_PORT","5432")
    if pg_host and tcp(pg_host,pg_port) and truthy("PG16_CERTIFIED"): status["PG16"]={"status":"PASS","evidence":os.getenv("PG16_EVIDENCE","real PostgreSQL gate certified")}
    redis_host=os.getenv("STAGING_REDIS_HOST"); redis_port=os.getenv("STAGING_REDIS_PORT","6379")
    if redis_host and tcp(redis_host,redis_port) and truthy("REDIS_CERTIFIED"): status["REDIS"]={"status":"PASS","evidence":os.getenv("REDIS_EVIDENCE","real Redis gate certified")}
    for gate,env in [("PSP","PSP_SANDBOX_CERTIFIED"),("CONNECTOR","CONNECTOR_SANDBOX_CERTIFIED"),("APNS","APNS_CERTIFIED"),("FCM","FCM_CERTIFIED"),("APPLE_SIGNING","APPLE_SIGNING_CERTIFIED"),("GOOGLE_SIGNING","GOOGLE_SIGNING_CERTIFIED"),("TESTFLIGHT","TESTFLIGHT_INSTALL_CERTIFIED"),("PLAY_INTERNAL","PLAY_INTERNAL_INSTALL_CERTIFIED"),("IPHONE_E2E","IPHONE_E2E_CERTIFIED"),("ANDROID_E2E","ANDROID_E2E_CERTIFIED"),("STORE_CHECKLIST","STORE_CHECKLIST_CERTIFIED")]:
        if truthy(env): status[gate]={"status":"PASS","evidence":os.getenv(env+"_EVIDENCE",env)}
    apple_assoc=os.getenv("APPLE_ASSOCIATION_URL")
    if apple_assoc and http(apple_assoc) and truthy("UNIVERSAL_LINK_CERTIFIED"): status["UNIVERSAL_LINK"]={"status":"PASS","evidence":apple_assoc}
    android_assoc=os.getenv("ANDROID_ASSOCIATION_URL")
    if android_assoc and http(android_assoc) and truthy("APP_LINK_CERTIFIED"): status["APP_LINK"]={"status":"PASS","evidence":android_assoc}
    blocked=[g for g,v in status.items() if v["status"]!="PASS"]
    state="INSTALLABLE_INTERNAL" if not blocked else "ENGINEERING_READY"
    out={"release":"GO Mobile Sprint 2C","generated_at":datetime.now(timezone.utc).isoformat(),"state":state,"blocker_count":len(blocked),"blocked":blocked,"gates":status}
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if not blocked else 2
if __name__=="__main__": raise SystemExit(main())
