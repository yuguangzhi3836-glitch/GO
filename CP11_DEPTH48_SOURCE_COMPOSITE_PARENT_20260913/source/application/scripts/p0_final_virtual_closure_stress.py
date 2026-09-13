from __future__ import annotations
import json, time, traceback, os, shutil
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/go_hotel_p0_final_virtual_stress.db")
os.environ.setdefault("SAGA_RETRY_SECONDS", "0")
os.environ.setdefault("OUTBOX_MAX_ATTEMPTS", "5")

from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.security.service import identity_service
from go_hotel.connectors.mock_hotel import connector
from go_hotel.payments.mock import payment_provider
from go_hotel.core.faults import faults
from tests import test_p0_final_virtual_closure_stress as suite

SCENARIOS = [
    suite.test_stress_close_race_requires_reprepare_after_scope_change,
    suite.test_stress_successful_order_forms_closed_loop,
    suite.test_stress_duplicate_payment_attack_is_blocked,
    suite.test_stress_supplier_timeout_stays_unknown_until_reconciled,
    suite.test_stress_payment_webhook_replay_is_idempotent,
    suite.test_stress_cancel_refund_full_path_and_terminal_immutability,
    suite.test_stress_partial_refund_is_bounded_and_can_complete_remaining_refund,
    suite.test_stress_reconciliation_mismatch_blocks_match_and_close,
]

ACTIVE_DB = Path("/tmp/go_hotel_p0_final_virtual_stress.db")
PRISTINE_DB = Path("/tmp/go_hotel_p0_final_virtual_stress_pristine.db")

def prepare_pristine_db():
    engine.dispose()
    for p in (ACTIVE_DB, PRISTINE_DB):
        try: p.unlink()
        except FileNotFoundError: pass
    Base.metadata.create_all(engine)
    identity_service.bootstrap()
    engine.dispose()
    shutil.copyfile(ACTIVE_DB, PRISTINE_DB)

def reset_db():
    faults.clear(); connector.reset(); payment_provider.reset()
    engine.dispose()
    shutil.copyfile(PRISTINE_DB, ACTIVE_DB)

def main(rounds=10, output=None):
    started = datetime.now(timezone.utc)
    prepare_pristine_db()
    results=[]
    passed=failed=0
    for r in range(1, rounds+1):
        reset_db()
        for fn in SCENARIOS:
            print(f'ROUND {r} START {fn.__name__}', flush=True)
            t=time.perf_counter()
            rec={'round':r,'scenario':fn.__name__}
            try:
                fn()
                rec['state']='PASS'; passed+=1
            except Exception as e:
                rec['state']='FAIL'; rec['error']=f'{type(e).__name__}: {e}'; rec['traceback']=traceback.format_exc(); failed+=1
            rec['elapsed_ms']=round((time.perf_counter()-t)*1000,2)
            results.append(rec)
            print(f'ROUND {r} END {fn.__name__} {rec["state"]} {rec["elapsed_ms"]}ms', flush=True)
    try:
        engine.dispose()
    except Exception:
        pass
    payload={
        'kind':'P0_FINAL_VIRTUAL_CLOSURE_STRESS',
        'started_at':started.isoformat(),
        'completed_at':datetime.now(timezone.utc).isoformat(),
        'rounds':rounds,
        'scenario_count':len(SCENARIOS),
        'executions':len(results),
        'passed':passed,
        'failed':failed,
        'all_passed':failed==0,
        'scope':'virtual engineering-contract stress; no real provider/network/bank/PostgreSQL certification',
        'scenarios':[fn.__name__ for fn in SCENARIOS],
        'results':results,
    }
    text=json.dumps(payload,ensure_ascii=False,indent=2)
    if output:
        Path(output).write_text(text)
    print(text)
    return 0 if failed==0 else 1

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--rounds',type=int,default=10); ap.add_argument('--output')
    args=ap.parse_args(); raise SystemExit(main(args.rounds,args.output))
