from __future__ import annotations
import argparse, asyncio, json
from go_hotel.connectors.registry import registry
from go_hotel.connectors.resilience import ResilientConnector
from go_hotel.connectors.certification import harness

async def run(connector_id:str):
    report=await harness.certify(ResilientConnector(registry.get(connector_id)))
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    raise SystemExit(0 if report.passed else 2)

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('connector_id'); args=ap.parse_args(); asyncio.run(run(args.connector_id))
