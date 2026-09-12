#!/usr/bin/env python3
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from go_hotel.services.p0_final_closure import p0_final_closure_service as svc

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    status=svc.evaluate();build=os.getenv('P0_FINAL_BUILD_SHA256')
    if build:
        status['sealed_bundle']=svc.seal(build)
    out=Path(os.getenv('P0_FINAL_CLOSURE_EVIDENCE_PATH','verification/p0_final_closure_status.json'));out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(status,indent=2,ensure_ascii=False,default=str)+'\n')
    print(json.dumps(status,indent=2,ensure_ascii=False,default=str))
    return 0 if status['external_sandbox_gate']=='PASS' else 2
if __name__=='__main__':sys.exit(main())
