from __future__ import annotations
import asyncio, json, os, sys
from pathlib import Path
from go_hotel.connectors.certification import ConnectorCertificationHarness
from go_hotel.connectors.siteminder import SiteMinderChannelsPlusConnector, SiteMinderConfig

class EnvIdentityResolver:
    def __init__(self):
        self.mapping=json.loads(os.getenv("SITEMINDER_IDENTITY_MAP_JSON","{}"))
    def __call__(self, external_id:str): return self.mapping.get(external_id)

async def main():
    out=Path("specs/siteminder_sandbox_certification.json")
    try:
        cfg=SiteMinderConfig.from_env()
    except Exception as exc:
        report={"connector_id":"conn_siteminder_channels_plus","status":"BLOCKED_PENDING_CREDENTIALS_OR_CONTRACTED_MAPPING","passed":False,"reason":str(exc)}
        out.write_text(json.dumps(report,indent=2,ensure_ascii=False)); print(json.dumps(report,indent=2,ensure_ascii=False)); return 2
    conn=SiteMinderChannelsPlusConnector(cfg,EnvIdentityResolver())
    report=await ConnectorCertificationHarness().certify(conn,city_code=os.getenv("SITEMINDER_CERT_CITY","TYO"),check_in=os.getenv("SITEMINDER_CERT_CHECKIN","2026-09-01"),check_out=os.getenv("SITEMINDER_CERT_CHECKOUT","2026-09-02"),currency=os.getenv("SITEMINDER_CERT_CURRENCY","CNY"))
    payload=report.as_dict(); payload["status"]="PASSED" if report.passed else "FAILED"
    out.write_text(json.dumps(payload,indent=2,ensure_ascii=False)); print(json.dumps(payload,indent=2,ensure_ascii=False)); return 0 if report.passed else 1

if __name__=="__main__": sys.exit(asyncio.run(main()))
