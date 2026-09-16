"""Fixed GitHub pull transport.  All process calls use fixed argument vectors."""
import argparse, base64, datetime as dt, hashlib, json, os, pathlib, re, shutil, sqlite3, subprocess, tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from . import artifact_store, deployment_actions, test_pr

VERSION = "0.5.7-rebuilt"
MAX_EXECUTOR_ATTEMPTS_PER_TASK = 1
ALLOWLIST = {"CONTROL_PLANE_HEALTH", "HK_STAGING_CANARY", "HK_STAGING_DEPLOY", "HK_STAGING_VERIFY", "HK_STAGING_ROLLBACK", "HK_STAGING_TEST_PR"}

# --- CC V1-02 failure closure -------------------------------------------------
# A Task is reported on only once its single execution attempt has been claimed.
# Claiming is what "picked up" means, so the published failure record closes the
# gap between "never picked up" and "picked up and failed" that the agent-local
# ledger could not express.
#
# Anything rejected before the claim publishes nothing.  In particular a Task
# whose own signature never verified is never reported on: otherwise whoever can
# write a task file could cause a write into the control bus.
FAILURE_STATUS = "FAILED"
FAILURE_EVIDENCE_SCHEMA_VERSION = "1"
FAILURE_EXECUTOR_RESULT = "EXECUTION_FAILED"

STAGE_AGENT = "agent_reject"
STAGE_ROLLBACK_HANDOFF = "rollback_handoff"
STAGE_EXECUTOR = "executor"
STAGE_RESULT = "result"
STAGE_EVIDENCE_BUILD = "evidence_build"
STAGE_ARTIFACT_DURABILITY = "artifact_durability"
STAGE_EVIDENCE_PUBLISH = "evidence_publish"

# Stage -> closed failure kind.  An unmapped stage is AGENT_REJECT, never echoed.
FAILURE_KIND_BY_STAGE = {
    STAGE_ROLLBACK_HANDOFF: "HANDOFF_FAILED",
    STAGE_EXECUTOR: "EXECUTION_FAILED",
    "subprocess_nonzero": "EXECUTION_FAILED",
    "subprocess_error": "EXECUTION_FAILED",
    "subprocess": "EXECUTION_FAILED",
    STAGE_RESULT: "RESULT_REJECT",
    "parser": "RESULT_REJECT",
    STAGE_EVIDENCE_BUILD: "EVIDENCE_BUILD_FAILED",
    # "the build succeeded but its artifact is not durable" is its own outcome:
    # it is neither an executor refusal nor a publication failure, and reading it
    # as either would hide the ephemeral-artifact defect.
    STAGE_ARTIFACT_DURABILITY: "ARTIFACT_DURABILITY_FAILED",
    STAGE_EVIDENCE_PUBLISH: "EVIDENCE_PUBLISH_FAILED",
}
FAILURE_KIND_FALLBACK = "AGENT_REJECT"

# Closed set.  A reason code outside it is reported as UNCLASSIFIED_REJECT rather
# than echoed, so no free-form diagnostic text can reach the control bus.
FAILURE_REASON_CODES = frozenset({
    "ARTIFACT_DURABILITY_REJECT", "ATTEMPT_BUDGET_EXHAUSTED", "CONFIG_REJECT",
    "EVIDENCE_DUPLICATE_REJECT", "EVIDENCE_NOT_PUBLISHED", "EXECUTOR_INVOCATION_FAILED",
    "EXECUTOR_NONZERO_EXIT", "EXECUTOR_OUTPUT_REJECTED", "EXECUTOR_RESULT_REJECT",
    "GITHUB_TRANSPORT_REJECT", "ROLLBACK_HANDOFF_REJECT", "ROLLBACK_SOURCE_REJECT",
    "TASK_ID_REJECT", "TASK_NOT_FOUND",
})
FAILURE_REASON_FALLBACK = "UNCLASSIFIED_REJECT"

# Executor refusals carry a human message, not one of the codes above, so the
# stage is what maps them onto the closed reason set.
FAILURE_REASON_BY_STAGE = {
    "subprocess_nonzero": "EXECUTOR_NONZERO_EXIT",
    "subprocess": "EXECUTOR_NONZERO_EXIT",
    "subprocess_error": "EXECUTOR_INVOCATION_FAILED",
    "parser": "EXECUTOR_OUTPUT_REJECTED",
    STAGE_RESULT: "EXECUTOR_RESULT_REJECT",
    STAGE_EVIDENCE_BUILD: "EXECUTOR_RESULT_REJECT",
    STAGE_ARTIFACT_DURABILITY: "ARTIFACT_DURABILITY_REJECT",
    STAGE_EVIDENCE_PUBLISH: "EVIDENCE_NOT_PUBLISHED",
    STAGE_ROLLBACK_HANDOFF: "ROLLBACK_HANDOFF_REJECT",
}

# Stages in which the executor process itself was involved.
EXECUTION_STAGES = frozenset({STAGE_EXECUTOR, STAGE_RESULT, "parser",
                              "subprocess_nonzero", "subprocess_error", "subprocess"})

GATE_ORDER = (("schema", "schema"), ("environment", "environment"), ("authority", "authority"),
              ("signature", "signature"), ("expiry", "expiry"), ("replay", "replay"),
              ("attempt_budget", "attempt_budget"), ("allowlist", "allowlist"),
              ("parameters", "parameters"))

class Reject(Exception):
    """A refusal, carrying the stage at which it happened.

    ``stage`` is what lets the failure record say where the attempt stopped; it is
    a closed internal vocabulary, never caller text.
    """
    def __init__(self, code, stage=None):
        super().__init__(code)
        self.code = code
        self.stage = stage or STAGE_AGENT

def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def canonical(obj):
    return json.dumps({k:v for k,v in obj.items() if k != "signature"}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

def load_json(path):
    with open(path, encoding="utf-8") as f: return json.load(f)

def public_key(path):
    with open(path,"rb") as f: return serialization.load_ssh_public_key(f.read())

def private_key(path):
    with open(path, "rb") as f:
        data = f.read()
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError):
        key = serialization.load_ssh_private_key(data, password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ValueError("evidence signing key must be Ed25519")
    return key

def verify(task, path):
    try:
        signature = task.get("signature")
        if not isinstance(signature, str) or re.fullmatch(r"[0-9a-f]{128}", signature) is None:
            raise ValueError("invalid task signature encoding")
        decoded = bytes.fromhex(signature)
        if len(decoded) != 64:
            raise ValueError("invalid task signature length")
        public_key(path).verify(decoded, canonical(task))
    except Exception as exc:
        raise Reject("SIGNATURE_REJECT") from exc

def verify_evidence(data, path):
    """Verify the existing Ed25519/base64 evidence envelope, unchanged."""
    try:
        signature=data.get("signature")
        if not isinstance(signature,str): raise ValueError("signature")
        decoded=base64.b64decode(signature.encode("ascii"),validate=True)
        if len(decoded)!=64: raise ValueError("length")
        public_key(path).verify(decoded,canonical(data))
    except Exception as exc:
        raise Reject("SOURCE_EVIDENCE_SIGNATURE_REJECT") from exc

def sign(evidence, path):
    evidence["signature"] = base64.b64encode(private_key(path).sign(canonical(evidence))).decode("ascii")
    return evidence

def git(key, args, cwd=None):
    env={"PATH":"/usr/bin:/bin","LC_ALL":"C","GIT_TERMINAL_PROMPT":"0"}
    env["GIT_SSH_COMMAND"]="ssh -i %s -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes" % key
    p=subprocess.run(["/usr/bin/git",*args], cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, check=False)
    if p.returncode: raise Reject("GITHUB_TRANSPORT_REJECT")
    return p.stdout.strip()

def clone(repo,key,target):
    git(key,["clone","--depth=1",repo,str(target)])

class Ledger:
    def __init__(self,path):
        self.path=path; pathlib.Path(path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS processed(task_id TEXT PRIMARY KEY, nonce TEXT UNIQUE NOT NULL, status TEXT NOT NULL, processed_at TEXT NOT NULL, evidence_ref TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS attempts(task_id TEXT PRIMARY KEY, nonce TEXT UNIQUE NOT NULL, attempt_number INTEGER NOT NULL, status TEXT NOT NULL, claimed_at TEXT NOT NULL, diagnostic TEXT)")
    def seen(self,task_id,nonce):
        with sqlite3.connect(self.path) as db: return db.execute("SELECT 1 FROM processed WHERE task_id=? OR nonce=?",(task_id,nonce)).fetchone() is not None
    def attempted(self,task_id,nonce):
        """An already-claimed task has exhausted its one executor attempt."""
        with sqlite3.connect(self.path) as db: return db.execute("SELECT 1 FROM attempts WHERE task_id=? OR nonce=?",(task_id,nonce)).fetchone() is not None
    def commit(self,task_id,nonce,status,ref):
        with sqlite3.connect(self.path) as db: db.execute("INSERT INTO processed VALUES(?,?,?,?,?)",(task_id,nonce,status,utcnow(),ref))
    def claim_attempt(self, task_id, nonce):
        """Durably claim exactly one executor attempt before dispatch."""
        with sqlite3.connect(self.path) as db:
            try:
                db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?)", (task_id,nonce,1,"claimed",utcnow(),None))
            except sqlite3.IntegrityError:
                return False
        return True
    def fail_attempt(self, task_id, nonce, diagnostic):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE attempts SET status=?, diagnostic=? WHERE task_id=? AND nonce=?", ("failed",json.dumps(diagnostic,sort_keys=True,separators=(",",":")),task_id,nonce))

def _safe_stream(value):
    raw = value if isinstance(value,str) else ""
    raw = re.sub(r"(?i)(bearer\s+|token=|password=|api[_ -]?key=)[^\s]+", r"\1[REDACTED]", raw)
    raw = re.sub(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----.*?-----END(?: [A-Z]+)? PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]", raw, flags=re.S)
    raw = raw[:8192]
    return {"length":len(raw),"sha256":hashlib.sha256(raw.encode()).hexdigest(),"preview":raw}

def failure_diagnostic(task, exc):
    audit={"task_id":task["task_id"],"nonce":task["nonce"],"action_id":task["action_id"],"attempt_number":1,
            "return_code":getattr(exc,"returncode",None),"stdout":_safe_stream(getattr(exc,"stdout",None)),
            "stderr":_safe_stream(getattr(exc,"stderr",None)),"failure_stage":getattr(exc,"stage",None) or "agent_reject"}
    # Parser failures occur after a subprocess completed.  Preserve only fixed,
    # independently useful terminal claims; never turn this into success Evidence.
    try:
        raw=getattr(exc,"stdout","").rstrip("\n"); item=json.loads(raw)
        if isinstance(item,dict):
            audit["executor_terminal_success"]=(item.get("status")=="SUCCESS" and item.get("result")=="ROLLBACK_OK")
            for key in ("rollback_record_id","rollback_record_sha256","source_deploy_task_id"):
                if isinstance(item.get(key),str) and len(item[key])<=128: audit[key]=item[key]
    except Exception: pass
    return audit

def failure_gate_results(stage):
    """Which validation gates had passed when the attempt stopped."""
    results={}; stopped=False
    for name,step in GATE_ORDER:
        if step == stage: results[name]="FAIL"; stopped=True
        elif stopped: results[name]="NOT_EVALUATED"
        else: results[name]="PASS"
    if not stopped: return {name:"PASS" for name,_ in GATE_ORDER}
    return results

def failure_kind(stage):
    return FAILURE_KIND_BY_STAGE.get(stage, FAILURE_KIND_FALLBACK)

def failure_reason(code, stage=None):
    """Map a refusal onto the closed reason set; never echo free-form text."""
    if code in FAILURE_REASON_CODES: return code
    if stage and stage in FAILURE_REASON_BY_STAGE: return FAILURE_REASON_BY_STAGE[stage]
    return FAILURE_REASON_FALLBACK

def failure_evidence(task, exc, stage=None):
    """A signed failure record for a Task whose execution attempt was consumed.

    This is Evidence, not a log.  It binds task_id, nonce, action_id and
    environment, it is signed by the same evidence identity as a success record,
    and it states inside itself that it is neither a success nor a permission to
    retry.  Nothing outside the closed vocabularies above can reach the record.
    """
    stage = stage or getattr(exc,"stage",None) or STAGE_AGENT
    stamp = utcnow()
    diagnostic = failure_diagnostic(task, exc)
    record = {
        "schema_version":"1",
        "task_id":task["task_id"],"nonce":task["nonce"],
        "action_id":task["action_id"],"environment":task["environment"],
        "status":FAILURE_STATUS,
        "started_at":stamp,"completed_at":stamp,
        "agent_version":VERSION,
        "executor_version":"unreported" if stage in EXECUTION_STAGES else "not_dispatched",
        "executor_result":FAILURE_EXECUTOR_RESULT,
        "gate_results":failure_gate_results(stage),
        "failure":{
            "schema_version":FAILURE_EVIDENCE_SCHEMA_VERSION,
            "kind":failure_kind(stage),
            "stage":stage,
            "reason_code":failure_reason(str(exc),stage),
            "attempt_number":MAX_EXECUTOR_ATTEMPTS_PER_TASK,
            "attempt_budget_exhausted":True,
            "execution_attempted":stage in EXECUTION_STAGES,
            "return_code":diagnostic.get("return_code"),
            "diagnostic":{"stdout":diagnostic["stdout"],"stderr":diagnostic["stderr"]},
        },
        # Load-bearing.  A failure record authorizes nothing at all: not a retry,
        # not a replay, not an action.  Producer and reader must agree on this.
        "retry_permitted":False,
        "replay_authorized":False,
        "authorizes_any_action":False,
    }
    return record

def publish_failure_evidence(task, exc, stage, cfg, work):
    """Sign and publish one failure record.  Raises rather than pretending."""
    record = sign(failure_evidence(task, exc, stage), cfg["evidence_signing_key"])
    return push_evidence(record, cfg, work, stage=STAGE_EVIDENCE_PUBLISH,
                         refuse_overwrite=True, dirname="evidence-failure")

def attempt_failure_publication(task, exc, stage, cfg, work):
    """Best effort publication that can never be read as success or as a retry.

    A failed publication of a failure record is recorded as exactly that.  It does
    not make the attempt a success, and it does not release the attempt budget:
    the attempt was already claimed durably before dispatch, so the one-attempt
    rule still holds and the next poll refuses the Task as ATTEMPT_BUDGET_REJECT.
    """
    try:
        commit = publish_failure_evidence(task, exc, stage, cfg, work)
        return {"attempted":True,"published":True,"commit":commit,"stage":stage,
                "reason_code":failure_reason(str(exc),stage)}
    except Exception as exc2:
        return {"attempted":True,"published":False,"stage":stage,
                "reason_code":failure_reason(str(exc2),stage),
                "error":type(exc2).__name__,
                "note":("the failure record could not be published; this is not a success and it "
                        "does not authorize a retry or a replay")}

REQUIRED={"schema_version","task_id","environment","action_id","issued_at","expires_at","nonce","parameters","authority","signature"}
def validate(task,cfg,ledger):
    if not isinstance(task,dict) or set(task) != REQUIRED or not isinstance(task.get("parameters"),dict): raise Reject("SCHEMA_REJECT")
    if task["environment"] != "HK-STAGING-01" or task["environment"] != cfg["environment"]: raise Reject("ENVIRONMENT_REJECT")
    if task["authority"] != cfg["authority"]: raise Reject("AUTHORITY_REJECT")
    verify(task,cfg["task_verify_key"])
    try: expired=dt.datetime.fromisoformat(task["expires_at"].replace("Z","+00:00")) <= dt.datetime.now(dt.timezone.utc)
    except Exception as exc: raise Reject("EXPIRY_REJECT") from exc
    if expired: raise Reject("EXPIRY_REJECT")
    if ledger.seen(task["task_id"],task["nonce"]): raise Reject("REPLAY_REJECT")
    if ledger.attempted(task["task_id"],task["nonce"]): raise Reject("ATTEMPT_BUDGET_REJECT")
    if task["action_id"] not in ALLOWLIST: raise Reject("ALLOWLIST_REJECT")
    if task["action_id"] != "CONTROL_PLANE_HEALTH":
        try:
            if task["action_id"] == test_pr.ACTION: test_pr.validate_parameters(task["parameters"])
            else: deployment_actions.validate(task["action_id"], task["parameters"])
        except (deployment_actions.Reject, test_pr.Reject) as exc:
            raise Reject("PARAMETERS_REJECT") from exc

def control_plane_health():
    avail=0
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"): avail=int(line.split()[1])*1024
    return {"agent_version":VERSION,"hostname":os.uname().nodename,"current_time":utcnow(),"disk_free_bytes":shutil.disk_usage("/").free,"memory_available_bytes":avail,"tasks_repo_connectivity":True,"evidence_repo_connectivity":True}

def evidence(task,result):
    stamp=utcnow()
    record = {"schema_version":"1","task_id":task["task_id"],"nonce":task["nonce"],"action_id":task["action_id"],"environment":task["environment"],"status":"SUCCESS","started_at":stamp,"completed_at":stamp,"agent_version":VERSION,"gate_results":{"schema":"PASS","environment":"PASS","authority":"PASS","signature":"PASS","expiry":"PASS","replay":"PASS","allowlist":"PASS"},"executor_result":result}
    if task["action_id"] == test_pr.ACTION:
        required={"schema_version","executor_version","action_id","status","result","source_pr_number","source_commit_sha","task_canonical_sha256","built_image_id","artifact_durability","artifact_package","gate_results","application_health_proven","deployment_performed"}
        if not isinstance(result,dict) or set(result) != required or result["status"] != "SUCCESS" or result["result"] != "TEST_PR_OK" or result["action_id"] != test_pr.ACTION or result["application_health_proven"] is not False or result["deployment_performed"] is not False:
            raise Reject("EXECUTOR_RESULT_REJECT", stage=STAGE_EVIDENCE_BUILD)
        # A build identity is not a deliverable.  The Evidence only carries a
        # deployable artifact claim when the executor also reports a sealed package
        # whose image identity is the one the build produced -- and, because Docker
        # reports an image's id as either the descriptor its index.json names or the
        # image's config digest depending on the host's image store, the package has
        # to say which role matched and which config digests it proved.  A claim that
        # names only the build id cannot be audited later, but a claim that names the
        # role and the config can.
        package=result["artifact_package"]
        if (result["artifact_durability"] != "PROVEN" or not isinstance(package,dict)
                or package.get("schema") != artifact_store.SCHEMA
                or package.get("image_id") != result["built_image_id"]
                or package.get("image_identity_role") not in ("root_descriptor","config")
                or not isinstance(package.get("config_digests"),list) or not package["config_digests"]
                or any(not isinstance(digest,str) or re.fullmatch(r"[0-9a-f]{64}",digest) is None
                       for digest in package["config_digests"])
                or not isinstance(package.get("package_sha256"),str)
                or re.fullmatch(r"[0-9a-f]{64}",package["package_sha256"]) is None):
            raise Reject("ARTIFACT_DURABILITY_REJECT", stage=STAGE_ARTIFACT_DURABILITY)
        record.update({"executor_version":result["executor_version"],"executor_result":result["result"],"source_pr_number":result["source_pr_number"],"source_commit_sha":result["source_commit_sha"],"task_canonical_sha256":result["task_canonical_sha256"],"built_image_id":result["built_image_id"],"artifact_durability":result["artifact_durability"],"artifact_package":package,"gate_results":result["gate_results"],"application_health_proven":False,"deployment_performed":False})
        return record
    if task["action_id"] != "CONTROL_PLANE_HEALTH":
        required={"schema_version","executor_version","action_id","status","release_id","candidate_image_id","expected_current_image_id","result","gate_results"}
        if task["action_id"]=="HK_STAGING_DEPLOY": required |= {"deploy_record_schema_version","deploy_record_id","deploy_record_sha256"}
        if task["action_id"]=="HK_STAGING_ROLLBACK": required |= {"source_deploy_task_id","source_deploy_record_id","source_deploy_record_sha256","rollback_record_id","rollback_record_sha256"}
        if not isinstance(result,dict) or set(result) != required: raise Reject("EXECUTOR_RESULT_REJECT", stage=STAGE_EVIDENCE_BUILD)
        record.update({"executor_version":result["executor_version"],"release_id":result["release_id"],"candidate_image_id":result["candidate_image_id"],"expected_current_image_id":result["expected_current_image_id"],"executor_result":result["result"],"gate_results":result["gate_results"]})
        if task["action_id"]=="HK_STAGING_DEPLOY":
            record.update({"deploy_record_schema_version":result["deploy_record_schema_version"],"deploy_record_id":result["deploy_record_id"],"deploy_record_sha256":result["deploy_record_sha256"]})
        if task["action_id"]=="HK_STAGING_ROLLBACK":
            record.update({key:result[key] for key in ("source_deploy_task_id","source_deploy_record_id","source_deploy_record_sha256","rollback_record_id","rollback_record_sha256")})
    return record

def _handoff_root():
    return pathlib.Path("/var/lib/go-hk-agent/rollback-source-handoff")

def _safe_handoff_write(task_id, bundle):
    """Fixed, task-derived, atomic handoff; no caller path or symlink traversal."""
    if not TASK_ID_PATTERN.fullmatch(task_id): raise Reject("ROLLBACK_HANDOFF_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    root=_handoff_root(); root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.is_symlink() or not root.is_dir(): raise Reject("ROLLBACK_HANDOFF_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    raw=json.dumps(bundle,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    if len(raw)>1024*1024: raise Reject("ROLLBACK_HANDOFF_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    target=root/(task_id+".json")
    if target.exists() or target.is_symlink(): raise Reject("ROLLBACK_HANDOFF_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    temp=root/("."+task_id+".tmp")
    fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(temp,target)
    except Exception:
        try: temp.unlink()
        except OSError: pass
        raise
    return str(target)

def prepare_rollback_handoff(task,cfg,tasks,work):
    """Agent fetches signed metadata; executor independently verifies every byte."""
    source_id=task["parameters"]["source_deploy_task_id"]
    source_path=tasks/"tasks"/(source_id+".json")
    source=load_json(source_path)
    # Production configuration uses the same pinned task key.  The optional
    # source key preserves that default while letting an isolated E2E harness
    # independently sign its synthetic rollback task.
    verify(source,cfg.get("source_task_verify_key",cfg["task_verify_key"]))
    if source.get("action_id")!="HK_STAGING_DEPLOY" or source.get("environment")!=cfg["environment"] or source.get("authority")!=cfg["authority"]: raise Reject("ROLLBACK_SOURCE_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    repo=work/"rollback-source-evidence"; clone(cfg["evidence_repo"],cfg["evidence_key"],repo)
    # Historical signed evidence may live on a protected evidence publication
    # branch.  Read all advertised refs; this is metadata retrieval only.
    git(cfg["evidence_key"],["-C",str(repo),"fetch","--prune","origin","+refs/heads/*:refs/remotes/origin/*"])
    matches={}; all_evidence={}
    refs=git(cfg["evidence_key"],["-C",str(repo),"for-each-ref","--format=%(refname)","refs/remotes/origin"]).splitlines()
    if len(refs)>128: raise Reject("ROLLBACK_SOURCE_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    for ref in refs:
      for name in git(cfg["evidence_key"],["-C",str(repo),"ls-tree","-r","--name-only",ref,"evidence"]).splitlines():
        if not name.startswith("evidence/") or not name.endswith(".json") or len(name)>512: continue
        try:
            raw=git(cfg["evidence_key"],["-C",str(repo),"show",ref+":"+name])
            if len(raw)>1024*1024: continue
            item=json.loads(raw)
            verify_evidence(item,cfg.get("evidence_verify_key","/etc/go-hk-agent/keys/evidence-signing.pub"))
            identity=(item.get("task_id"),item.get("nonce"))
            if all(isinstance(v,str) for v in identity): all_evidence.setdefault(identity,{})[hashlib.sha256(canonical(item)).hexdigest()]=item
            if item.get("task_id")==source_id and item.get("nonce")==source.get("nonce"):
                matches[hashlib.sha256(canonical(item)).hexdigest()]=item
        except (OSError,ValueError,Reject):
            continue
    if len(matches)!=1: raise Reject("ROLLBACK_SOURCE_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    item=next(iter(matches.values()))
    required={"task_id","nonce","action_id","environment","status","release_id","executor_result","deploy_record_id","deploy_record_sha256"}
    if not required <= set(item) or item["status"]!="SUCCESS" or item["executor_result"]!="DEPLOY_OK": raise Reject("ROLLBACK_SOURCE_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    history=[]
    candidates=sorted((tasks/"tasks").glob("*.json"))
    if len(candidates)>256: raise Reject("ROLLBACK_SOURCE_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
    for candidate in candidates:
        try:
            prior=load_json(candidate); verify(prior,cfg["task_verify_key"])
            if prior.get("environment")!=cfg["environment"] or prior.get("authority")!=cfg["authority"]: continue
            key=(prior.get("task_id"),prior.get("nonce")); evidence_values=all_evidence.get(key,{})
            if len(evidence_values)>1: raise Reject("ROLLBACK_SOURCE_REJECT", stage=STAGE_ROLLBACK_HANDOFF)
            history.append({"task":prior,"evidence":next(iter(evidence_values.values()),None)})
        except (OSError,ValueError,Reject):
            # Unsigned or malformed repository files are not accepted Tasks and
            # cannot establish deployment lineage.  They are never forwarded.
            continue
    bundle={"schema_version":"1","rollback_task_id":task["task_id"],"source_task":source,"source_evidence":item,"source_deploy_task_id":source_id,"deploy_record_id":item["deploy_record_id"],"deploy_record_sha256":item["deploy_record_sha256"],"history":history}
    return _safe_handoff_write(task["task_id"],bundle)

def _staged(exc, default_stage):
    """Re-raise an executor refusal as a transport refusal that carries a stage.

    The executor layer reports a human message and a stage such as ``parser`` or
    ``subprocess_nonzero``.  The failure record needs a closed vocabulary, so the
    stage is preserved, the message is only kept for the redacted diagnostic, and
    the exception is normalised to one type the caller already handles.
    """
    stage = getattr(exc, "stage", None) or default_stage
    replacement = Reject(str(exc), stage=stage)
    for attribute in ("stdout", "stderr", "returncode"):
        setattr(replacement, attribute, getattr(exc, attribute, None))
    return replacement

def dispatch_action(task, executor=None):
    if task["action_id"] == "CONTROL_PLANE_HEALTH":
        return control_plane_health()
    if task["action_id"] == test_pr.ACTION:
        try:
            return test_pr.execute(task)
        except test_pr.Reject as exc:
            raise _staged(exc, STAGE_EXECUTOR) from exc
    binding=None
    if task["action_id"] in ("HK_STAGING_DEPLOY","HK_STAGING_ROLLBACK"):
        binding={"task_id":task["task_id"],"nonce":task["nonce"],"authority":task["authority"],"canonical_sha256":hashlib.sha256(canonical(task)).hexdigest()}
    try:
        return deployment_actions.dispatch(task, executor or deployment_actions.ProductionExecutor(),binding)
    except deployment_actions.Reject as exc:
        raise _staged(exc, STAGE_EXECUTOR) from exc

def _publish_workspace(work, dirname, data):
    """A private clone target for one publication.

    A single ``run_once`` publishes every Task it claims, in one order, inside
    one temporary work root.  Publishing into a fixed ``work/<dirname>`` made the
    second publication fail: ``git clone`` refuses a destination that already
    holds a work tree, so the second Evidence of a pass was reported as
    GITHUB_TRANSPORT_REJECT at stage ``evidence_publish`` while its Task had in
    fact executed and succeeded.  Each record therefore gets its own workspace.

    The Task identity is hashed rather than interpolated, so no Task-supplied
    string can become a path component.  This changes where the clone happens,
    not what is published: repository, branch, ``evidence/<task_id>-<nonce>.json``
    filename, signature and signer are all untouched.
    """
    identity = "%s\0%s" % (data.get("task_id", ""), data.get("nonce", ""))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return pathlib.Path(work) / ("%s-%s" % (dirname, digest))

def push_evidence(data,cfg,work,stage=None,refuse_overwrite=False,dirname="evidence"):
    """Publish one record.  ``refuse_overwrite`` never replaces an existing one.

    One Task identity has at most one Evidence record.  A second record for the
    same task/nonce could be read as either outcome, so it is refused instead of
    merged or overwritten.

    Each call publishes from its own clone workspace, so several Tasks can be
    published in the same ``run_once`` pass without colliding.
    """
    try:
        repo=_publish_workspace(work,dirname,data); clone(cfg["evidence_repo"],cfg["evidence_key"],repo)
        out=repo/"evidence"; out.mkdir(exist_ok=True)
        name=(data["task_id"]+"-"+data["nonce"]).replace("/","_")+".json"; path=out/name
        if refuse_overwrite and (path.exists() or path.is_symlink()):
            raise Reject("EVIDENCE_DUPLICATE_REJECT", stage=stage)
        path.write_text(json.dumps(data,sort_keys=True,separators=(",",":")),encoding="utf-8")
        git(cfg["evidence_key"],["-C",str(repo),"config","user.name","GO HK Agent"])
        git(cfg["evidence_key"],["-C",str(repo),"config","user.email","go-hk-agent@localhost"])
        git(cfg["evidence_key"],["-C",str(repo),"add","--",str(path.relative_to(repo))])
        git(cfg["evidence_key"],["-C",str(repo),"commit","-m","evidence: "+data["task_id"]])
        commit=git(cfg["evidence_key"],["-C",str(repo),"rev-parse","HEAD"])
        git(cfg["evidence_key"],["-C",str(repo),"push","origin","HEAD"])
        return commit
    except Reject as exc:
        raise Reject(exc.code,
                     stage=(exc.stage if exc.stage != STAGE_AGENT else stage)) from exc

TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

def select_task_sources(folder, task_id):
    if task_id is None:
        return sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not isinstance(task_id,str) or not TASK_ID_PATTERN.fullmatch(task_id):
        raise Reject("TASK_ID_REJECT")
    source = folder / (task_id + ".json")
    if not source.is_file():
        raise Reject("TASK_NOT_FOUND")
    return [source]

def run_once(config_path,ledger_path,task_id=None):
    cfg=load_json(config_path)
    needed={"environment","authority","tasks_repo","tasks_key","evidence_repo","evidence_key","task_verify_key","evidence_signing_key"}
    if not needed <= set(cfg) or cfg["environment"] != "HK-STAGING-01": raise Reject("CONFIG_REJECT")
    ledger=Ledger(ledger_path); result={"agent_version":VERSION,"mode":"run-once","processed":0,"rejected":0,"evidence_commits":[],"failure_evidence":[]}
    with tempfile.TemporaryDirectory(prefix="go-hk-agent-") as raw:
        work=pathlib.Path(raw); tasks=work/"tasks"; clone(cfg["tasks_repo"],cfg["tasks_key"],tasks)
        folder=tasks/"tasks"
        for source in select_task_sources(folder,task_id):
            task=None
            claimed=False
            try:
                task=load_json(source); validate(task,cfg,ledger)
                if not ledger.claim_attempt(task["task_id"],task["nonce"]):
                    raise Reject("ATTEMPT_BUDGET_EXHAUSTED")
                claimed=True
                if task["action_id"]=="HK_STAGING_ROLLBACK": prepare_rollback_handoff(task,cfg,tasks,work)
                data=sign(evidence(task,dispatch_action(task)),cfg["evidence_signing_key"])
                commit=push_evidence(data,cfg,work,stage=STAGE_EVIDENCE_PUBLISH)
                ledger.commit(task["task_id"],task["nonce"],"completed",commit)
                result["processed"]+=1; result["evidence_commits"].append(commit)
            except (Reject, artifact_store.Reject, deployment_actions.Reject, test_pr.Reject) as exc:
                # CC V1-02.  A Task whose single execution attempt was claimed is
                # reported on even when it fails, so "picked up and failed" stops
                # being invisible.  Anything rejected before the claim publishes
                # nothing: an unauthenticated Task must never cause a write.
                #
                # The store's own refusal type is listed as well, although the
                # TEST_PR builder already converts it at its own boundary: a
                # refusal that reached here uncaught killed the whole pass, so no
                # failure record was published and the ledger attempt stayed
                # claimed forever.  This is the belt to that braces, and it reports
                # an unmapped stage as AGENT_REJECT rather than crashing.
                publication={"attempted":False,"published":False,"reason":"task_not_claimed"}
                if claimed:
                    stage=getattr(exc,"stage",None) or STAGE_AGENT
                    publication=attempt_failure_publication(task,exc,stage,cfg,work)
                    ledger.fail_attempt(task["task_id"],task["nonce"],
                                        dict(failure_diagnostic(task,exc),
                                             evidence_publication=publication))
                    if publication.get("published"):
                        ledger.commit(task["task_id"],task["nonce"],"failed",
                                      publication["commit"])
                result["rejected"]+=1
                result["failure_evidence"].append(publication)
    return result

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--run-once",action="store_true"); p.add_argument("--config",default=os.environ.get("HK_AGENT_CONFIG","/etc/go-hk-agent/agent.json")); p.add_argument("--ledger",default="/var/lib/go-hk-agent/ledger/agent.sqlite3"); p.add_argument("--task-id"); a=p.parse_args(argv)
    if not a.run_once: p.error("--run-once is required")
    try: print(json.dumps(run_once(a.config,a.ledger,a.task_id),sort_keys=True,separators=(",",":"))); return 0
    except Reject as exc: print(json.dumps({"status":str(exc)})); return 1

if __name__ == "__main__": raise SystemExit(main())
