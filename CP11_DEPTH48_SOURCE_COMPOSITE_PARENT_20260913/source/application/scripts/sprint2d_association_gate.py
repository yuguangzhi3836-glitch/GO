from __future__ import annotations
import json, os, pathlib, sys, urllib.request, ssl
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'staging'/'bringup'/'association.local.json'

def get_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'GO-Sprint2D-LinkVerifier/1.0'})
    with urllib.request.urlopen(req,timeout=10,context=ssl.create_default_context()) as r:
        return r.status, json.loads(r.read())

def main():
    out={}
    for gate,var in [('UNIVERSAL_LINK','APPLE_ASSOCIATION_URL'),('APP_LINK','ANDROID_ASSOCIATION_URL')]:
        url=os.getenv(var,'').strip()
        if not url: out[gate]={'status':'BLOCKED','error':f'{var} missing'}; continue
        try:
            status,body=get_json(url)
            valid=status==200 and isinstance(body,(dict,list))
            out[gate]={'status':'PASS' if valid else 'FAIL','http_status':status,'json_type':type(body).__name__,'url':url}
        except Exception as e: out[gate]={'status':'BLOCKED','error':type(e).__name__+': '+str(e)[:300],'url':url}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,indent=2)); return 0 if all(v['status']=='PASS' for v in out.values()) else 2
if __name__=='__main__': sys.exit(main())
