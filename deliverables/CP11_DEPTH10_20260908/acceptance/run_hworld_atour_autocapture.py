#!/usr/bin/env python3
"""Autonomously capture and evaluate H World + Atour public browser inventory traffic.

Runs two independent fresh browser contexts per chain, writes raw HAR-like JSON and
screenshots, analyzes each capture, then requires stable inventory SHA and pagination
proof. This gate is discovery evidence only; it never enables production adapters.
"""
from __future__ import annotations
import argparse,json
from dataclasses import asdict
from pathlib import Path
from go_hotel.services.browser_capture_runner import browser_capture_runner
from go_hotel.services.browser_network_inventory_discovery import browser_network_inventory_discovery
from go_hotel.services.chain_hotel_registry import ChainCode


def main():
    p=argparse.ArgumentParser();p.add_argument("--out",required=True);p.add_argument("--headed",action="store_true");p.add_argument("--max-cycles",type=int,default=80);args=p.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);reports={}
    for chain in (ChainCode.H_WORLD,ChainCode.ATOUR):
        captures=[];capture_meta=[]
        for run in (1,2):
            path=out/f"{chain.value.lower()}_capture_{run}.har.json"
            result=browser_capture_runner.capture(chain=chain,output_path=path,headless=not args.headed,max_cycles=args.max_cycles,actor="HWORLD_ATOUR_AUTOCAPTURE")
            capture_meta.append(asdict(result));captures.append(json.loads(path.read_text(encoding="utf-8")))
        comparison=browser_network_inventory_discovery.compare_independent_captures(chain=chain,captures=captures)
        reports[chain.value]={"captures":capture_meta,"comparison":comparison}
    status="PASS" if all(x["comparison"]["status"]=="PASS" for x in reports.values()) else "HOLD"
    evidence={"gate":"HWORLD_ATOUR_AUTONOMOUS_BROWSER_CAPTURE","status":status,"production_adapter_enabled":False,"reports":reports}
    (out/"autocapture_evidence.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(evidence,ensure_ascii=False,indent=2));return 0 if status=="PASS" else 2
if __name__=="__main__":raise SystemExit(main())
