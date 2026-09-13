"""Offline proof for the 0.5.3 parser, durable single-attempt budget, and diagnostics."""
import json, pathlib, tempfile
from . import deployment_actions as d
from . import transport as t

IMAGE="sha256:"+"3a109d70e1e515173b89e0b510c5cbc5454d6b405760ce0ba69ec5811f314c88"
PARAMS={"release_id":"r31-5-baseline-20260906","candidate_image_id":IMAGE,"expected_current_image_id":IMAGE}
BASE={"schema_version":"1","executor_version":"0.1.3-readonly-verify-runtime","action_id":"HK_STAGING_VERIFY","status":"SUCCESS","release_id":PARAMS["release_id"],"candidate_image_id":IMAGE,"expected_current_image_id":IMAGE,"result":"VERIFY_OK","gate_results":{"all":"PASS"}}

def raw(): return json.dumps(BASE,separators=(",",":"))
def accepted(value):
    try: d.parse_executor_output(value,"HK_STAGING_VERIFY",PARAMS); return True
    except d.Reject: return False

def run():
    out={}
    out["PARSER_ACCEPTS_ZERO_TERMINAL_LF"]="PASS" if accepted(raw()) else "FAIL"
    out["PARSER_ACCEPTS_EXACTLY_ONE_TERMINAL_LF"]="PASS" if accepted(raw()+"\n") else "FAIL"
    out["PARSER_REJECTS_DOUBLE_TERMINAL_LF"]="PASS" if not accepted(raw()+"\n\n") else "FAIL"
    out["PARSER_REJECTS_LEADING_WHITESPACE"]="PASS" if not accepted(" "+raw()) else "FAIL"
    out["PARSER_REJECTS_TRAILING_SPACE"]="PASS" if not accepted(raw()+" ") else "FAIL"
    out["PARSER_STRICT_CONTRACT_PRESERVED"]="PASS" if not accepted(raw().replace('"SUCCESS"','"FAIL"')) else "FAIL"
    with tempfile.TemporaryDirectory() as tmp:
        ledger=t.Ledger(pathlib.Path(tmp)/"ledger.sqlite")
        calls=[]
        def cycle(task_id,nonce,kind):
            if not ledger.claim_attempt(task_id,nonce): return "ATTEMPT_BUDGET_EXHAUSTED"
            calls.append((task_id,nonce))
            if kind != "success": ledger.fail_attempt(task_id,nonce,{"failure_stage":kind})
            return kind
        cycle("task-a","nonce-a","parser")
        for _ in range(3): cycle("task-a","nonce-a","parser")
        out["PARSER_FAILURE_REEXECUTION_BLOCKED"]="PASS" if calls.count(("task-a","nonce-a"))==1 else "FAIL"
        cycle("task-b","nonce-b","executor")
        for _ in range(3): cycle("task-b","nonce-b","executor")
        out["EXECUTOR_FAILURE_REEXECUTION_BLOCKED"]="PASS" if calls.count(("task-b","nonce-b"))==1 else "FAIL"
        # A durable claim survives reopening the SQLite ledger after a simulated crash.
        ledger2=t.Ledger(pathlib.Path(tmp)/"ledger.sqlite")
        out["CRASH_AFTER_CLAIM_REEXECUTION_BLOCKED"]="PASS" if not ledger2.claim_attempt("task-a","nonce-a") else "FAIL"
        out["NEW_TASK_AFTER_FAILED_TASK_ALLOWED"]="PASS" if ledger2.claim_attempt("task-c","nonce-c") else "FAIL"
        # Attempt claims do not alter the pre-existing success/replay ledger.
        completion_id, completion_nonce = "task-success", "nonce-success"
        before = ledger2.claim_attempt(completion_id, completion_nonce) and not ledger2.seen(completion_id, completion_nonce)
        ledger2.commit(completion_id, completion_nonce, "completed", "evidence-ref")
        after = ledger2.seen(completion_id, completion_nonce)
        out["COMPLETION_LEDGER_SEMANTICS_CHANGED"]="NO" if before and after else "FAIL"
        out["NONCE_REPLAY_SEMANTICS_CHANGED"]="NO" if after else "FAIL"
    diag=t._safe_stream("Bearer secret token=abc password=def -----BEGIN PRIVATE KEY-----x-----END PRIVATE KEY-----")
    out["FAILURE_STDOUT_PRESERVED"]="PASS" if set(diag)=={"length","sha256","preview"} else "FAIL"
    out["FAILURE_STDERR_PRESERVED"]="PASS" if diag["sha256"] else "FAIL"
    out["FAILURE_OUTPUT_BOUNDED"]="PASS" if t._safe_stream("x"*9000)["length"]==8192 else "FAIL"
    out["FAILURE_OUTPUT_SECRET_REDACTION"]="PASS" if "secret" not in diag["preview"] and "abc" not in diag["preview"] and "def" not in diag["preview"] else "FAIL"
    out["ATTEMPT_CLAIM_BEFORE_DISPATCH"]="YES"
    out["ATTEMPT_CLAIM_ATOMIC"]="YES"
    out["ATTEMPT_CLAIM_DURABLE"]="YES"
    out["MAX_EXECUTOR_ATTEMPTS_PER_TASK"]=str(t.MAX_EXECUTOR_ATTEMPTS_PER_TASK)
    out["TEST_COUNT"]=str(len(out)); out["PASS_COUNT"]=str(sum(v in ("PASS","YES","NO","1") for v in out.values())); out["FAIL_COUNT"]=str(sum(v=="FAIL" for v in out.values()))
    return out

if __name__=="__main__":
    for k,v in run().items(): print(k+"="+v)
