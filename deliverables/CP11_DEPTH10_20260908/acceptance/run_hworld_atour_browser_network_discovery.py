#!/usr/bin/env python3
"""Evaluate two independent normal-browser network captures for H World and Atour.

This is discovery-only and cannot enable production adapters. Captures are expected as
HAR JSON files produced by a normal public website session. PASS here means a stable
public official inventory/pagination contract was observed twice; production promotion
still requires an explicit source-contract change and adapter review.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from go_hotel.services.browser_network_inventory_discovery import browser_network_inventory_discovery
from go_hotel.services.chain_hotel_registry import ChainCode

def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def main():
 p=argparse.ArgumentParser();p.add_argument("--hworld",action="append",required=True);p.add_argument("--atour",action="append",required=True);args=p.parse_args()
 if len(args.hworld)<2 or len(args.atour)<2:raise SystemExit("two independent captures per chain are required")
 reports={}
 for chain,paths in ((ChainCode.H_WORLD,args.hworld),(ChainCode.ATOUR,args.atour)):
  reports[chain.value]=browser_network_inventory_discovery.compare_independent_captures(chain=chain,captures=[load(x) for x in paths])
 status="PASS" if all(x["status"]=="PASS" for x in reports.values()) else "HOLD"
 print(json.dumps({"gate":"HWORLD_ATOUR_BROWSER_NETWORK_DISCOVERY","status":status,"production_adapter_enabled":False,"reports":reports},ensure_ascii=False,indent=2))
 return 0 if status=="PASS" else 2
if __name__=="__main__":raise SystemExit(main())
