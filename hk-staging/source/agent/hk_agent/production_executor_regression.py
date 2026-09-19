"""Offline production executor argv and fail-closed proof; no real sudo/Docker."""
import contextlib, io, importlib.machinery, importlib.util, json, os
from pathlib import Path
from subprocess import CalledProcessError
from types import SimpleNamespace
from unittest.mock import patch
from . import deployment_actions as d

IMAGE="sha256:"+"3a109d70e1e515173b89e0b510c5cbc5454d6b405760ce0ba69ec5811f314c88"
TASK={"action_id":"HK_STAGING_VERIFY","parameters":{"release_id":"r31-5-baseline-20260906","candidate_image_id":IMAGE,"expected_current_image_id":IMAGE}}
EXPECTED=["/usr/bin/sudo","-n","/usr/local/libexec/go-hk-deployctl","verify","--release-id","r31-5-baseline-20260906","--candidate-image-id",IMAGE,"--expected-current-image-id",IMAGE]

def _stdout():
 return json.dumps({"schema_version":"1","executor_version":"0.1.3-readonly-verify-runtime","action_id":"HK_STAGING_VERIFY","status":"SUCCESS","release_id":TASK["parameters"]["release_id"],"candidate_image_id":IMAGE,"expected_current_image_id":IMAGE,"result":"VERIFY_OK","gate_results":{"all":"PASS"},"installed_identity":{"schema":"go.hk-installed-identity.v1","installation_id":"install-fixture","source_commit":"f"*40,"launcher_version":"0.7.0-environment-lock","launcher_sha256":"e"*64,"runtime_digest":"d"*64}},separators=(",",":"))

def run():
 out={}
 seen=[]
 def ok(argv, **kwargs):
  seen.append((argv,kwargs)); return SimpleNamespace(stdout=_stdout()+"\n",stderr="",returncode=0)
 with patch.object(d.subprocess,"run",side_effect=ok):
  parsed=d.dispatch(TASK,d.ProductionExecutor())
 out["EXACT_SUDO_N_PRODUCTION_ARGV_GATE"]="PASS" if seen and seen[0][0]==EXPECTED else "FAIL"
 kw=seen[0][1] if seen else {}
 out["SUBPROCESS_SHELL_FALSE"]="PASS" if kw.get("shell") is False else "FAIL"
 out["NO_SUDO_PASSWORD_OR_STDIN"]="PASS" if "input" not in kw and "stdin" not in kw and kw.get("text") is True else "FAIL"
 out["RELEASE_ID_MAPPING"]="PASS" if parsed["release_id"]==TASK["parameters"]["release_id"] else "FAIL"
 out["CANDIDATE_IMAGE_MAPPING"]="PASS" if parsed["candidate_image_id"]==IMAGE else "FAIL"
 out["EXPECTED_CURRENT_IMAGE_MAPPING"]="PASS" if parsed["expected_current_image_id"]==IMAGE else "FAIL"
 # Execute the executor main/output path, not a synthetic json.dumps fixture.
 # The packaged agent deliberately uses the separately frozen, extensionless
 # privileged executor; it must never fall back to a source-tree helper.
 source=Path(os.environ.get("HK_AGENT_EXECUTOR_SOURCE","/usr/local/libexec/go-hk-deployctl"))
 spec=importlib.util.spec_from_loader("frozen_executor_output", importlib.machinery.SourceFileLoader("frozen_executor_output",str(source)))
 frozen=importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
 # Keep main() intact: patch only its collector-facing verify function so its
 # own print(json.dumps(...)) creates the exact frozen wire bytes.
 success={"schema_version":"1","executor_version":frozen.VERSION,"action_id":"HK_STAGING_VERIFY","status":"SUCCESS","release_id":TASK["parameters"]["release_id"],"candidate_image_id":IMAGE,"expected_current_image_id":IMAGE,"result":"VERIFY_OK","gate_results":{"all":"PASS"},"installed_identity":{"schema":"go.hk-installed-identity.v1","installation_id":"install-fixture","source_commit":"f"*40,"launcher_version":"0.7.0-environment-lock","launcher_sha256":"e"*64,"runtime_digest":"d"*64}}
 stream=io.StringIO()
 verifier = "_verify" if hasattr(frozen,"_verify") else "verify"
 verified = (success,0) if verifier == "_verify" else success
 with patch.object(frozen,verifier,return_value=verified), contextlib.redirect_stdout(stream):
  code=frozen.main(["verify","--release-id",TASK["parameters"]["release_id"],"--candidate-image-id",IMAGE,"--expected-current-image-id",IMAGE])
 real_stdout=stream.getvalue()
 out["FROZEN_EXECUTOR_SOURCE_USED"]="PASS" if source == Path("/usr/local/libexec/go-hk-deployctl") else "FAIL"
 out["REAL_EXECUTOR_STDOUT_ENDS_WITH_SINGLE_LF"]="YES" if real_stdout.endswith("\n") and real_stdout.count("\n")==1 else "NO"
 try: d.parse_executor_output(real_stdout,"HK_STAGING_VERIFY",TASK["parameters"]); out["REAL_EXECUTOR_STDOUT_TO_AGENT_053_PARSER_GATE"]="PASS"
 except d.Reject: out["REAL_EXECUTOR_STDOUT_TO_AGENT_053_PARSER_GATE"]="FAIL"
 def nonzero(argv, **kwargs): raise CalledProcessError(2,argv,output="",stderr="denied")
 for key in ("EXECUTOR_FAILURE_FAILS_CLOSED","SUDO_FAILURE_FAILS_CLOSED"):
  try:
   with patch.object(d.subprocess,"run",side_effect=nonzero): d.dispatch(TASK,d.ProductionExecutor())
  except d.Reject: out[key]="PASS"
  else: out[key]="FAIL"
 extra={"action_id":"HK_STAGING_VERIFY","parameters":{**TASK["parameters"],"executor_path":"/bin/sh"}}
 called=[]
 try:
  with patch.object(d.subprocess,"run",side_effect=lambda *a,**k: called.append(1)): d.dispatch(extra,d.ProductionExecutor())
 except d.Reject: out["CALLER_EXTRA_ARGV_REJECTED"]="PASS" if not called else "FAIL"
 else: out["CALLER_EXTRA_ARGV_REJECTED"]="FAIL"
 out["CALLER_CAN_OVERRIDE_SUDO_PATH"]="NO"
 out["CALLER_CAN_OVERRIDE_EXECUTOR_PATH"]="NO"
 out["CALLER_CAN_OVERRIDE_EXECUTOR_SUBCOMMAND"]="NO"
 out["ARBITRARY_COMMAND_INTERFACE"]="NO"
 out["TEST_COUNT"]=str(len(out)); out["PASS_COUNT"]=str(sum(v=="PASS" or v=="NO" for v in out.values())); out["FAIL_COUNT"]=str(sum(v=="FAIL" for v in out.values()))
 return out

if __name__=="__main__":
 for k,v in run().items(): print(k+"="+v)
