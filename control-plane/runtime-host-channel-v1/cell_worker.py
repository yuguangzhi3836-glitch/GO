"""C2-C14 worker instances over the existing claim/dispatch/resume/result loop.

AI_TASK_V1 returns advisory model text, not code execution or an independent formal
C13/C14 verdict. Result authorizes_any_action stays false. Development and review
executors retain their own existing authority and acceptance requirements.
"""
import time

from c1_execution_contract import REAL_TASK_KIND, Refused, canonical
from c1_worker import (build_client, credential_refusal, open_outbox, open_runtime,
                       tick, STATUS_FIELDS)
from cell_channel import arguments, cell_config


def tick_cell(config, runtime, outbox, client):
    return dict(tick(runtime, outbox, client, owner_c=config["cell"],
                     worker_id=config["worker_id"], claim_kinds=(REAL_TASK_KIND,), lease_s=180),
                cell=config["cell"])


def main(argv=None):
    args = arguments(argv)
    try:
        config = cell_config(args.cell)
    except Refused as exc:
        print(canonical({"status": "REFUSED", "reason": exc.reason}))
        return 1
    refusal = credential_refusal()
    if refusal:
        print(canonical(dict(refusal, cell=config["cell"])))
        return 1
    if args.check:
        print(canonical({"status": "READY", "cell": config["cell"],
                         "claimed_kinds": [REAL_TASK_KIND], "outbox": config["outbox"],
                         "capability": "ADVISORY_TEXT_ONLY"}))
        return 0
    runtime, outbox, client = open_runtime(), open_outbox(config["outbox"]), build_client()
    while True:
        try:
            result = tick_cell(config, runtime, outbox, client)
        except Exception as exc:
            result = {"status": "BLOCKED", "cell": config["cell"], "reason": type(exc).__name__}
        print(canonical({k: v for k, v in result.items() if k in (*STATUS_FIELDS, "cell")}), flush=True)
        if args.once:
            return 0 if result["status"] not in ("FAILED", "BLOCKED", "REFUSED") else 1
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
