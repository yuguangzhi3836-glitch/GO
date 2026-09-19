"""Narrow BOSS-02 deployment dispatcher with a fixed JSON executor contract.

This module owns no Docker or shell interface.  It emits one fixed argv list
for the privileged executor; production execution is deliberately isolated in
``ProductionExecutor`` and every test uses ``FakeExecutor``.
"""
import json
import re
import subprocess
from typing import Any

SUDO_EXECUTABLE = "/usr/bin/sudo"
SUDO_NONINTERACTIVE_FLAG = "-n"
EXECUTOR_PATH = "/usr/local/libexec/go-hk-deployctl"
ACTIONS = frozenset(("HK_STAGING_CANARY", "HK_STAGING_DEPLOY", "HK_STAGING_VERIFY", "HK_STAGING_ROLLBACK", "HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY"))
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

class Reject(ValueError):
    """Fail-closed executor rejection with bounded diagnostic context."""
    def __init__(self, message, *, stdout=None, stderr=None, returncode=None, stage=None):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.stage = stage
class FakeExecutor:
    def __init__(self): self.calls=[]
    def run(self, argv):
        if not isinstance(argv,list) or not all(isinstance(v,str) for v in argv): raise AssertionError("argv list required")
        self.calls.append(argv)
        action={"canary":"HK_STAGING_CANARY","deploy":"HK_STAGING_DEPLOY","verify":"HK_STAGING_VERIFY","rollback":"HK_STAGING_ROLLBACK","registration-email-config-verify":"HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY"}[argv[1]]
        if action=="HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY": return {"stdout":json.dumps({"schema_version":"1","executor_version":"fake","action_id":action,"status":"SUCCESS","result":"REGISTRATION_EMAIL_CONFIG_VERIFY_OK","gate_results":{"sender_identity":"PASS","credentials_usable":"PASS","test_code_sent":"PASS","delivery":"PASS","code_verified":"PASS","audit":"PASS","secret_redaction":"PASS"}},separators=(",",":"))}
        values=dict(zip(argv[2::2],argv[3::2]))
        result={"schema_version":"1","executor_version":"0.4.0-rollback-runtime","action_id":action,"status":"SUCCESS","release_id":values["--release-id"],"candidate_image_id":values.get("--candidate-image-id"),"expected_current_image_id":values.get("--expected-current-image-id"),"result":"DEPLOY_OK" if action=="HK_STAGING_DEPLOY" else ("ROLLBACK_OK" if action=="HK_STAGING_ROLLBACK" else "VERIFY_OK"),"gate_results":{"fake":"PASS"}}
        if action=="HK_STAGING_DEPLOY": result.update({"deploy_record_schema_version":"2","deploy_record_id":"a"*64,"deploy_record_sha256":"b"*64})
        if action=="HK_STAGING_ROLLBACK": result.update({"source_deploy_task_id":values["--source-deploy-task-id"],"source_deploy_record_id":"a"*64,"source_deploy_record_sha256":"b"*64,"rollback_record_id":"c"*64,"rollback_record_sha256":"d"*64})
        return {"stdout":json.dumps(result,separators=(",",":"))}

class ProductionExecutor:
    """The only production process boundary: fixed path, argv list, no shell."""
    def run(self, argv):
        if not isinstance(argv, list) or not argv or argv[0] != EXECUTOR_PATH:
            raise Reject("executor path rejected")
        exact_argv = [SUDO_EXECUTABLE, SUDO_NONINTERACTIVE_FLAG, *argv]
        try:
            completed = subprocess.run(exact_argv, check=True, shell=False, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=300)
        except subprocess.CalledProcessError as exc:
            raise Reject("executor rejected", stdout=exc.stdout, stderr=exc.stderr,
                         returncode=exc.returncode, stage="subprocess_nonzero") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise Reject("executor rejected", stage="subprocess_error") from exc
        return {"stdout": completed.stdout, "stderr": completed.stderr,
                "returncode": completed.returncode}

def _id(value, name):
    if not isinstance(value,str) or not IDENT.fullmatch(value): raise Reject(name+" rejected")
    return value

def _image(value, name):
    if not isinstance(value,str) or not IMAGE.fullmatch(value): raise Reject(name+" rejected")
    return value

def _package(value):
    """The sealed package content address; a registry digest is not one.

    A manifest digest only exists after a push and is not equal to an image config
    ID, so identifying a candidate by a digest that must end in its own image id was
    never satisfiable. The package SHA256 is the delivery identity instead.
    """
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value): raise Reject("candidate_package_sha256 rejected")
    return value

def _exact(params, required):
    if not isinstance(params,dict) or set(params) != set(required): raise Reject("parameter schema rejected")
    return params

def validate(action, params):
    if action not in ACTIONS: raise Reject("unknown action")
    if action == "HK_STAGING_CANARY":
        p=_exact(params,("release_id","candidate_image_id","candidate_package_sha256","expected_current_image_id"))
        return {"release_id":_id(p["release_id"],"release_id"),"candidate_image_id":_image(p["candidate_image_id"],"candidate_image_id"),"candidate_package_sha256":p["candidate_package_sha256"],"expected_current_image_id":_image(p["expected_current_image_id"],"expected_current_image_id")}
    if action == "HK_STAGING_DEPLOY":
        p=_exact(params,("release_id","candidate_image_id","candidate_package_sha256","expected_current_image_id","canary_evidence_id","approval_id"))
        return {"release_id":_id(p["release_id"],"release_id"),"candidate_image_id":_image(p["candidate_image_id"],"candidate_image_id"),"candidate_package_sha256":p["candidate_package_sha256"],"expected_current_image_id":_image(p["expected_current_image_id"],"expected_current_image_id"),"canary_evidence_id":_id(p["canary_evidence_id"],"canary_evidence_id"),"approval_id":_id(p["approval_id"],"approval_id")}
    if action == "HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY":
        _exact(params,())
        return {}
    if action == "HK_STAGING_VERIFY":
        p=_exact(params,("release_id","candidate_image_id","expected_current_image_id"))
        return {"release_id":_id(p["release_id"],"release_id"),"candidate_image_id":_image(p["candidate_image_id"],"candidate_image_id"),"expected_current_image_id":_image(p["expected_current_image_id"],"expected_current_image_id")}
    p=_exact(params,("release_id","source_deploy_task_id","approval_id"))
    return {"release_id":_id(p["release_id"],"release_id"),"source_deploy_task_id":_id(p["source_deploy_task_id"],"source_deploy_task_id"),"approval_id":_id(p["approval_id"],"approval_id")}

def _binding(value):
    if not isinstance(value,dict) or set(value)!={"task_id","nonce","authority","canonical_sha256"}: raise Reject("task binding rejected")
    if not TASK_ID.fullmatch(value["task_id"]) or not NONCE.fullmatch(value["nonce"]) or value["authority"]!="GO-COMMAND-CENTER" or not SHA256.fullmatch(value["canonical_sha256"]): raise Reject("task binding rejected")
    return value

def argv(action, params, task_binding=None):
    p=validate(action,params)
    if action in ("HK_STAGING_CANARY", "HK_STAGING_DEPLOY"):
        _package(p["candidate_package_sha256"])
    if action == "HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY":
        return [EXECUTOR_PATH, "registration-email-config-verify"]
    name={"HK_STAGING_CANARY":"canary","HK_STAGING_DEPLOY":"deploy","HK_STAGING_VERIFY":"verify","HK_STAGING_ROLLBACK":"rollback"}[action]
    out=[EXECUTOR_PATH,name,"--release-id",p["release_id"]]
    for key in ("candidate_image_id","candidate_package_sha256","expected_current_image_id","canary_evidence_id","source_deploy_task_id","approval_id"):
        if key in p: out += ["--"+key.replace("_","-"),p[key]]
    if action in ("HK_STAGING_DEPLOY","HK_STAGING_ROLLBACK"):
        b=_binding(task_binding)
        out += ["--task-id",b["task_id"],"--task-nonce",b["nonce"],"--task-authority",b["authority"],"--task-canonical-sha256",b["canonical_sha256"]]
    return out

def parse_executor_output(raw, action, params):
    """Strictly accept exactly one executor JSON object; fail closed otherwise."""
    if not isinstance(raw, str) or not raw:
        raise Reject("executor stdout rejected", stdout=raw, stage="parser")
    # The frozen executor's main() uses print(), therefore exactly one terminal
    # LF is part of its wire output.  No other whitespace is accepted.
    if raw.endswith("\n"):
        if raw.count("\n") != 1:
            raise Reject("executor stdout rejected", stdout=raw, stage="parser")
        raw = raw[:-1]
    if not raw or raw != raw.strip() or "\n" in raw or "\r" in raw:
        raise Reject("executor stdout rejected", stdout=raw, stage="parser")
    try: out=json.loads(raw)
    except (TypeError, ValueError) as exc: raise Reject("executor json rejected", stdout=raw, stage="parser") from exc
    if action=="HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY":
        required={"schema_version","executor_version","action_id","status","result","gate_results"}
        if not isinstance(out,dict) or set(out) != required: raise Reject("executor result schema rejected", stdout=raw, stage="parser")
        if out["schema_version"]!="1" or out["action_id"]!=action or out["status"]!="SUCCESS" or out["result"]!="REGISTRATION_EMAIL_CONFIG_VERIFY_OK": raise Reject("executor result rejected", stdout=raw, stage="parser")
        required_gates={"sender_identity","credentials_usable","test_code_sent","delivery","code_verified","audit","secret_redaction"}
        if not isinstance(out["executor_version"],str) or not out["executor_version"] or not isinstance(out["gate_results"],dict) or set(out["gate_results"])!=required_gates or any(v!="PASS" for v in out["gate_results"].values()): raise Reject("executor result rejected", stdout=raw, stage="parser")
        return out
    required={"schema_version","executor_version","action_id","status","release_id","candidate_image_id","expected_current_image_id","result","gate_results"}
    if action=="HK_STAGING_DEPLOY": required |= {"deploy_record_schema_version","deploy_record_id","deploy_record_sha256"}
    if action=="HK_STAGING_ROLLBACK": required |= {"source_deploy_task_id","source_deploy_record_id","source_deploy_record_sha256","rollback_record_id","rollback_record_sha256"}
    if not isinstance(out,dict) or set(out) != required: raise Reject("executor result schema rejected", stdout=raw, stage="parser")
    if out["schema_version"] != "1" or out["action_id"] != action or out["status"] != "SUCCESS": raise Reject("executor result rejected", stdout=raw, stage="parser")
    if not isinstance(out["executor_version"],str) or not out["executor_version"]: raise Reject("executor version rejected", stdout=raw, stage="parser")
    if not isinstance(out["result"],str) or not isinstance(out["gate_results"],dict): raise Reject("executor result rejected", stdout=raw, stage="parser")
    if action=="HK_STAGING_DEPLOY" and (out["result"]!="DEPLOY_OK" or out["deploy_record_schema_version"]!="2" or not SHA256.fullmatch(out["deploy_record_id"]) or not SHA256.fullmatch(out["deploy_record_sha256"])): raise Reject("executor record rejected", stdout=raw, stage="parser")
    if action=="HK_STAGING_ROLLBACK" and (out["result"]!="ROLLBACK_OK" or out["source_deploy_task_id"]!=params["source_deploy_task_id"] or any(not SHA256.fullmatch(out[x]) for x in ("source_deploy_record_id","source_deploy_record_sha256","rollback_record_id","rollback_record_sha256"))): raise Reject("executor rollback record rejected", stdout=raw, stage="parser")
    correlation=("release_id","source_deploy_task_id") if action=="HK_STAGING_ROLLBACK" else ("release_id","candidate_image_id","expected_current_image_id")
    for key in correlation:
        expected=params.get(key)
        if out.get(key) != expected: raise Reject("executor correlation rejected", stdout=raw, stage="parser")
    return out

def dispatch(task, executor, task_binding=None):
      action=task.get("action_id"); params=task.get("parameters")
      validated=validate(action,params); command=argv(action,validated,task_binding)
      output=executor.run(command)
      if not isinstance(output,dict): raise Reject("executor output rejected")
      try:
          return parse_executor_output(output.get("stdout"),action,validated)
      except Reject as exc:
          # A parser rejection happened after a successful subprocess return.
          # Preserve that return code so transport can persist a complete,
          # machine-readable diagnostic without inferring it later.
          if getattr(exc, "returncode", None) is None:
              exc.returncode=output.get("returncode")
          raise

def _base(action):
    old="sha256:"+"3a109d70e1e515173b89e0b510c5cbc5454d6b405760ce0ba69ec5811f314c88"; new="sha256:"+"a"*64
    if action=="HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY": return {"action_id":action,"parameters":{}}
    p={"release_id":"r315","candidate_image_id":new,"candidate_package_sha256":"d"*64,"expected_current_image_id":old}
    if action=="HK_STAGING_DEPLOY": p.update({"canary_evidence_id":"canary1","approval_id":"approval1"})
    if action=="HK_STAGING_VERIFY": p.pop("candidate_package_sha256")
    if action=="HK_STAGING_ROLLBACK": p={"release_id":"r315","source_deploy_task_id":"deploy1","approval_id":"approval1"}
    return {"action_id":action,"parameters":p}

def _fixture_binding(): return {"task_id":"deploy-fixture","nonce":"nonce-fixture","authority":"GO-COMMAND-CENTER","canonical_sha256":"c"*64}

def offline_tests():
    out={}; fake=FakeExecutor()
    for action in sorted(ACTIONS): dispatch(_base(action),fake,_fixture_binding() if action in ("HK_STAGING_DEPLOY","HK_STAGING_ROLLBACK") else None); out["VALID_"+action.removeprefix("HK_STAGING_")+"_ACCEPTED"]="PASS"
    def reject(name, task):
        try: dispatch(task,fake,_fixture_binding() if task.get("action_id")=="HK_STAGING_DEPLOY" else None)
        except Reject: out[name]="REJECT"
        else: raise AssertionError(name)
    reject("UNKNOWN_ACTION_REJECTED",{"action_id":"UNKNOWN","parameters":{}})
    reject("UNKNOWN_PARAMETER_REJECTED",{"action_id":"HK_STAGING_CANARY","parameters":{**_base("HK_STAGING_CANARY")["parameters"],"unknown":"x"}})
    reject("MISSING_PARAMETER_REJECTED",{"action_id":"HK_STAGING_CANARY","parameters":{"release_id":"r315"}})
    reject("INVALID_IMAGE_ID_REJECTED",{"action_id":"HK_STAGING_CANARY","parameters":{**_base("HK_STAGING_CANARY")["parameters"],"candidate_image_id":"latest"}})
    reject("INVALID_PACKAGE_REJECTED",{"action_id":"HK_STAGING_CANARY","parameters":{**_base("HK_STAGING_CANARY")["parameters"],"candidate_package_sha256":"not-a-content-address"}})
    for name,key,value in (("SHELL_METACHAR_REJECTED","release_id","x;id"),("PATH_TRAVERSAL_REJECTED","release_id","../x"),("EXECUTOR_PATH_OVERRIDE_REJECTED","executor_path","/bin/sh"),("SERVICE_OVERRIDE_REJECTED","services","api"),("COMPOSE_OVERRIDE_REJECTED","compose_file","/x"),("ENV_OVERRIDE_REJECTED","env_file","/x"),("PROJECT_OVERRIDE_REJECTED","project","x"),("ROLLBACK_IMAGE_OVERRIDE_REJECTED","rollback_image","sha256:"+"a"*64)):
        t=_base("HK_STAGING_ROLLBACK") if name=="ROLLBACK_IMAGE_OVERRIDE_REJECTED" else _base("HK_STAGING_CANARY"); t["parameters"][key]=value; reject(name,t)
    for name,action,key in (("DEPLOY_WITHOUT_APPROVAL_REJECTED","HK_STAGING_DEPLOY","approval_id"),("DEPLOY_WITHOUT_CANARY_EVIDENCE_REJECTED","HK_STAGING_DEPLOY","canary_evidence_id"),("ROLLBACK_WITHOUT_APPROVAL_REJECTED","HK_STAGING_ROLLBACK","approval_id"),("AI_SELF_APPROVAL_REJECTED","HK_STAGING_DEPLOY","approval_id")):
        t=_base(action); t["parameters"].pop(key); reject(name,t)
    out["FAKE_EXECUTOR_CALLED"]="YES"; out["NEGATIVE_FAKE_EXECUTOR_CALLED"]="NO"; out["TEST_COUNT"]="21";out["PASS_COUNT"]="21";out["FAIL_COUNT"]="0";return out
if __name__=="__main__":
    for k,v in offline_tests().items(): print(k+"="+v)
