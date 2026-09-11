from __future__ import annotations
import argparse,hashlib,json,shutil
from pathlib import Path

FILES=[
 'src/go_hotel/agent_gateway/contracts.py','src/go_hotel/agent_gateway/service.py',
 'src/go_hotel/agent_gateway/real_core.py','src/go_hotel/agent_gateway/canonical_core.py',
 'src/go_hotel/agent_gateway/lifecycle_core.py','src/go_hotel/agent_gateway/auth.py',
 'src/go_hotel/agent_gateway/runtime.py','src/go_hotel/agent_gateway/mcp.py',
 'src/go_hotel/agent_gateway/a2a.py','src/go_hotel/agent_gateway/rest.py',
 'src/go_hotel/agent_gateway/protocol_http.py',
 'tests/test_agent_transaction_gateway.py','tests/test_agent_transaction_gateway_real_core.py',
 'tests/test_agent_transaction_gateway_six_vertical.py','tests/test_agent_payment_truth_binding.py',
 'tests/test_agent_transaction_lifecycle_p02.py',
 'mobile/go-app/native/apple/GOTravelTransactionIntents.swift',
 'mobile/go-app/native/apple/GOTransactionLifecycleIntents.swift',
]
IMPORT='from go_hotel.agent_gateway.runtime import install_agent_gateway\n'
INSTALL='install_agent_gateway(app)\n'
ANCHOR='app.include_router(travel_intelligence_router)\n'
def sha(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--overlay',required=True);ap.add_argument('--evidence');a=ap.parse_args()
 source=Path(a.source).resolve();overlay=Path(a.overlay).resolve();before={};after={}
 for rel in FILES:
  src=overlay/rel;dst=source/rel
  if not src.is_file():raise SystemExit('OVERLAY_FILE_MISSING:'+rel)
  before[rel]=sha(dst) if dst.exists() else None;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);after[rel]=sha(dst)
 mainp=source/'src/go_hotel/main.py';text=mainp.read_text()
 if IMPORT not in text:
  marker='from fastapi import FastAPI\n'
  if marker not in text:raise SystemExit('MAIN_IMPORT_ANCHOR_MISSING')
  text=text.replace(marker,marker+IMPORT,1)
 if INSTALL not in text:
  if ANCHOR not in text:raise SystemExit('MAIN_INSTALL_ANCHOR_MISSING')
  text=text.replace(ANCHOR,ANCHOR+INSTALL,1)
 mainp.write_text(text);after['src/go_hotel/main.py']=sha(mainp)
 result={'status':'PASS','copied_files':len(FILES),'main_installed':True,'before':before,'after':after}
 if a.evidence:Path(a.evidence).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':'PASS','copied_files':len(FILES),'main_sha256':after['src/go_hotel/main.py']}))
if __name__=='__main__':main()
