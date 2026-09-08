#!/usr/bin/env python3
"""Two-round autonomous browser capture + inventory-contract proof for H World/Atour."""
from __future__ import annotations
import argparse,hashlib,json,time
from pathlib import Path
from go_hotel.services.browser_capture_runner import browser_capture_runner
from go_hotel.services.browser_network_inventory_discovery import browser_network_inventory_discovery
from go_hotel.services.chain_hotel_registry import ChainCode

CHAINS=(ChainCode.H_WORLD,ChainCode.ATOUR)

def _load(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def _sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
 p=argparse.ArgumentParser();p.add_argument("--out",required=True);p.add_argument("--headed",action="store_true");p.add_argument("--max-cycles",type=int,default=80);p.add_argument("--settle-ms",type=int,default=1200);p.add_argument("--between-rounds-seconds",type=int,default=5);args=p.parse_args()
 out=Path(args.out);out.mkdir(parents=True,exist_ok=True);summary={"gate":"HWORLD_ATOUR_AUTONOMOUS_BROWSER_CAPTURE","status":"HOLD","production_adapter_enabled":False,"chains":{}}
 for chain in CHAINS:
  captures=[];capture_meta=[]
  for round_no in (1,2):
   path=out/f"{chain.value.lower()}_round{round_no}.har.json"
   result=browser_capture_runner.capture(chain=chain,output_path=path,headless=not args.headed,max_cycles=args.max_cycles,settle_ms=args.settle_ms,actor="HWORLD_ATOUR_BROWSER_CAPTURE")
   captures.append(_load(path));capture_meta.append({**result.__dict__,"capture_sha256":_sha(path)})
   if round_no==1:time.sleep(max(1,args.between_rounds_seconds))
  proof=browser_network_inventory_discovery.compare_independent_captures(chain=chain,captures=captures)
  frozen=out/f"{chain.value.lower()}_frozen_inventory.json"
  inventory=proof["reports"][0].get("inventory") if proof.get("status")=="PASS" else []
  frozen.write_text(json.dumps({"chain":chain.value,"inventory_sha256":proof.get("inventory_sha256"),"property_count":len(inventory),"inventory":inventory},ensure_ascii=False,indent=2),encoding="utf-8")
  summary["chains"][chain.value]={"capture_meta":capture_meta,"proof":proof,"frozen_inventory_path":str(frozen),"frozen_inventory_file_sha256":_sha(frozen),"source_contract_promotion_required":True}
 summary["status"]="PASS" if all(v["proof"]["status"]=="PASS" for v in summary["chains"].values()) else "HOLD"
 (out/"browser_capture_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
 print(json.dumps(summary,ensure_ascii=False,indent=2));return 0 if summary["status"]=="PASS" else 2
if __name__=="__main__":raise SystemExit(main())
