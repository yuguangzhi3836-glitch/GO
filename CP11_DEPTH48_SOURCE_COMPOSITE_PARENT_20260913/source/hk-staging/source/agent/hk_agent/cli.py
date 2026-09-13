import argparse,json,os
from pathlib import Path
from .core import ALLOWLIST,ENVIRONMENT,VERSION,health
REQUIRED={'environment','authority','tasks_repo','evidence_repo','task_verify_key','evidence_signing_key','tasks_key','evidence_key'}
def main(argv=None):
 p=argparse.ArgumentParser(prog='go-hk-agent'); p.add_argument('--run-once',action='store_true'); p.add_argument('--self-check',action='store_true'); a=p.parse_args(argv)
 cfg=Path(os.environ.get('HK_AGENT_CONFIG','/etc/go-hk-agent/agent.json'))
 if not cfg.is_file(): raise SystemExit('config unavailable')
 c=json.loads(cfg.read_text())
 if not REQUIRED.issubset(c) or c.get('environment')!=ENVIRONMENT: raise SystemExit('config rejected')
 result={'agent_version':VERSION,'mode':'run-once' if a.run_once else 'self-check','active_allowlist':sorted(ALLOWLIST),'health':health({'tasks':False,'evidence':False})}
 print(json.dumps(result,sort_keys=True,separators=(',',':')))
 return 0
if __name__=='__main__': raise SystemExit(main())
