"""Fail-closed HK-STAGING rollback runtime.

The agent may fetch source metadata, but this module independently verifies
the signed task/evidence and derives all rollback targets from an immutable
DEPLOY_RECORD_V2.  Production uses only fixed filesystem paths and fixed
Docker compose argv; tests inject a runner and paths.
"""
import base64, hashlib, json, os, pathlib, re, tempfile, time
from cryptography.hazmat.primitives import serialization

PROJECT="go-822-staging"
COMPOSE="/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml"
ENV_FILE="/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env"
TASK_KEY="/etc/go-hk-agent/keys/task-verify.pub"
EVIDENCE_KEY="/etc/go-hk-agent/keys/evidence-signing.pub"
HANDOFF_DIR="/var/lib/go-hk-agent/rollback-source-handoff"
DEPLOY_RECORD_DIR="/var/lib/go-hk-deployctl/deploy-records"
ROLLBACK_RECORD_DIR="/var/lib/go-hk-deployctl/rollback-records"
TEMP_DIR="/run/go-hk-deployctl"
SERVICES=("api","recovery-worker","outbox-worker","mobile-push-receipt-worker","reconciliation-worker","mobile-push-worker","mobile-engagement-worker","judgment-worker")
PROTECTED=("redis","caddy")
HEX=re.compile(r"^[0-9a-f]{64}$")
API_READINESS_ATTEMPTS=12
API_READINESS_INTERVAL_SECONDS=5

class Reject(ValueError): pass

def canonical(obj):
    return json.dumps({k:v for k,v in obj.items() if k!="signature"},sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")

def _key(path):
    with open(path,"rb") as f: return serialization.load_ssh_public_key(f.read())

def _verify(obj,path,hex_signature):
    try:
        sig=obj.get("signature")
        raw=bytes.fromhex(sig) if hex_signature else base64.b64decode(sig.encode("ascii"),validate=True)
        if len(raw)!=64: raise ValueError("signature length")
        _key(path).verify(raw,canonical(obj))
    except Exception as exc: raise Reject("signature") from exc

def _read_regular(path,max_bytes=1024*1024):
    p=pathlib.Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>max_bytes: raise Reject("fixed path")
    return json.loads(p.read_text(encoding="utf-8"))

def _sha(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def resolve_source(release,source_task_id,rollback_task_id, *, handoff_dir=HANDOFF_DIR, deploy_dir=DEPLOY_RECORD_DIR, task_key=TASK_KEY, evidence_key=EVIDENCE_KEY):
    if not isinstance(source_task_id,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",source_task_id): raise Reject("source task")
    handoff=_read_regular(pathlib.Path(handoff_dir)/(rollback_task_id+".json"))
    if set(handoff)!={"schema_version","rollback_task_id","source_task","source_evidence","source_deploy_task_id","deploy_record_id","deploy_record_sha256","history"} or handoff["schema_version"]!="1" or handoff["rollback_task_id"]!=rollback_task_id or handoff["source_deploy_task_id"]!=source_task_id: raise Reject("handoff")
    task=handoff["source_task"]; evidence=handoff["source_evidence"]
    _verify(task,task_key,True); _verify(evidence,evidence_key,False)
    if task.get("schema_version")!="1" or task.get("action_id")!="HK_STAGING_DEPLOY" or task.get("environment")!="HK-STAGING-01" or task.get("authority")!="GO-COMMAND-CENTER" or task.get("task_id")!=source_task_id: raise Reject("source task binding")
    if evidence.get("schema_version")!="1" or evidence.get("task_id")!=task["task_id"] or evidence.get("nonce")!=task.get("nonce") or evidence.get("action_id")!="HK_STAGING_DEPLOY" or evidence.get("environment")!="HK-STAGING-01" or evidence.get("status")!="SUCCESS" or evidence.get("executor_result")!="DEPLOY_OK": raise Reject("source evidence binding")
    record_id=handoff["deploy_record_id"]; record_sha=handoff["deploy_record_sha256"]
    if evidence.get("deploy_record_id")!=record_id or evidence.get("deploy_record_sha256")!=record_sha or not HEX.fullmatch(record_id) or not HEX.fullmatch(record_sha): raise Reject("record evidence binding")
    record_path=pathlib.Path(deploy_dir)/(record_id+".json")
    record=_read_regular(record_path)
    if hashlib.sha256(record_path.read_bytes()).hexdigest()!=record_sha or record.get("deploy_record_schema_version")!="2" or record.get("record_id")!=record_id: raise Reject("record integrity")
    if record.get("task_id")!=task["task_id"] or record.get("nonce")!=task["nonce"] or record.get("authority")!=task["authority"] or record.get("task_canonical_sha256")!=hashlib.sha256(canonical(task)).hexdigest(): raise Reject("record task binding")
    targets=record.get("targets")
    protected=record.get("protected_non_target_inventory")
    if not isinstance(targets,list) or [x.get("service") for x in targets]!=list(SERVICES) or not isinstance(protected,list) or sorted(x.get("service") for x in protected)!=sorted(PROTECTED): raise Reject("record scope")
    if any(not isinstance(x.get("image_id"),str) or not x["image_id"].startswith("sha256:") for x in targets): raise Reject("record targets")
    history=handoff["history"]
    if not isinstance(history,list) or not history or len(history)>256: raise Reject("lineage")
    found=False
    source_issued=task.get("issued_at")
    for entry in history:
        if not isinstance(entry,dict) or set(entry)!={"task","evidence"} or not isinstance(entry["task"],dict): raise Reject("lineage")
        prior=entry["task"]; _verify(prior,task_key,True)
        prior_evidence=entry["evidence"]
        if prior_evidence is not None:
            if not isinstance(prior_evidence,dict): raise Reject("lineage")
            _verify(prior_evidence,evidence_key,False)
            if prior_evidence.get("task_id")!=prior.get("task_id") or prior_evidence.get("nonce")!=prior.get("nonce"): raise Reject("lineage")
        if prior.get("task_id")==source_task_id: found=True
        # Any newer DEPLOY (successful or with no evidence) makes this source
        # non-latest/ambiguous.  A successful rollback of this source also does.
        if prior.get("issued_at","")>source_issued and prior.get("action_id")=="HK_STAGING_DEPLOY": raise Reject("later deployment")
        if prior.get("action_id")=="HK_STAGING_ROLLBACK" and prior_evidence and prior_evidence.get("status")=="SUCCESS" and prior_evidence.get("source_deploy_task_id")==source_task_id: raise Reject("already rolled back")
    if not found: raise Reject("lineage")
    return task,evidence,record,targets

def _run(runner,argv,code="docker read"):
    out=runner.run(argv)
    if getattr(out,"returncode",None)!=0: raise Reject(code)
    return getattr(out,"stdout","")

def _override(targets):
    """Pin the eight services to the immutable ids the source record carries.

    The frozen R3.1.5 base file names its services by tag and this host holds the
    images by id only, so the base file on its own makes Compose resolve a tag that
    is not present and attempt a pull.  DEPLOY already merges such an override for
    its candidate; a rollback needs the same shape for the ids it restores.
    """
    root=TEMP_DIR
    pathlib.Path(root).mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,path=tempfile.mkstemp(prefix="rollback-",suffix=".yaml",dir=root,text=True)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,"w") as f:
        f.write("services:\n")
        for target in targets: f.write("  "+target["service"]+":\n    image: "+target["image_id"]+"\n")
    return path

def _await_api_health(runner,collector,expected,sleeper,
                      attempts=API_READINESS_ATTEMPTS,interval=API_READINESS_INTERVAL_SECONDS):
    """The eight are not restored until the api the record names is answering."""
    for attempt in range(attempts):
        try:
            collector.collect_api(runner,expected); return
        except ValueError:
            if attempt+1==attempts: raise Reject("rollback readiness")
            sleeper(interval)

def _inventory(runner,services):
    result=[]
    for service in services:
        ids=[x for x in _run(runner,["/usr/bin/docker","ps","-aq","--filter","label=com.docker.compose.project="+PROJECT,"--filter","label=com.docker.compose.service="+service]).splitlines() if x]
        if len(ids)!=1: raise Reject("container selection")
        raw=_run(runner,["/usr/bin/docker","inspect",ids[0]])
        try: item=json.loads(raw)[0]
        except Exception as exc: raise Reject("inspect") from exc
        result.append({"service":service,"container_id":item.get("Id"),"image_id":item.get("Image"),"started_at":item.get("State",{}).get("StartedAt"),"restart_count":item.get("RestartCount"),"running":item.get("State",{}).get("Running"),"status":item.get("State",{}).get("Status")})
    return result

def _atomic_record(record, directory=ROLLBACK_RECORD_DIR):
    raw=json.dumps(record,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); rid=hashlib.sha256(raw).hexdigest(); record["rollback_record_id"]=rid
    raw=json.dumps(record,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); sha=hashlib.sha256(raw).hexdigest()
    root=pathlib.Path(directory); root.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=root/(rid+".json")
    if target.exists(): raise Reject("record exists")
    fd,path=tempfile.mkstemp(prefix=".rollback-",dir=str(root));
    try:
        os.fchmod(fd,0o400)
        with os.fdopen(fd,"wb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(path,target)
    except Exception:
        try: os.unlink(path)
        except OSError: pass
        raise Reject("record persist")
    return rid,sha

def run_rollback(release,source_task_id,binding,runner,collector, *, handoff_dir=HANDOFF_DIR, deploy_dir=DEPLOY_RECORD_DIR, rollback_dir=ROLLBACK_RECORD_DIR, task_key=TASK_KEY, evidence_key=EVIDENCE_KEY, sleeper=time.sleep):
    if not isinstance(binding,dict) or set(binding)!={"task_id","nonce","authority","canonical_sha256"}: raise Reject("binding")
    source_task,source_evidence,source_record,targets=resolve_source(release,source_task_id,binding["task_id"],handoff_dir=handoff_dir,deploy_dir=deploy_dir,task_key=task_key,evidence_key=evidence_key)
    # A durable pre-mutation record is consuming even if a later Agent parser
    # fails.  Missing success Evidence must never make a source reusable.
    prior=pathlib.Path(rollback_dir)
    if prior.exists():
        for item in prior.glob("*.json"):
            try:
                if not item.is_symlink() and _read_regular(item).get("source_deploy_task_id")==source_task_id: raise Reject("source consumed")
            except Reject: raise
            except Exception: raise Reject("source consumed")
    # Fresh drift: fixed hashes, target identity and protected inventory must still match source current state.
    if hashlib.sha256(pathlib.Path(COMPOSE).read_bytes()).hexdigest()!=source_record.get("compose_sha256") or hashlib.sha256(pathlib.Path(ENV_FILE).read_bytes()).hexdigest()!=source_record.get("env_sha256"): raise Reject("baseline drift")
    current=_inventory(runner,SERVICES); protected=_inventory(runner,PROTECTED)
    if any(x["running"] is not True or x["status"]!="running" for x in current+protected): raise Reject("runtime drift")
    expected_current=source_record.get("candidate_image_id")
    if not isinstance(expected_current,str) or any(x["image_id"]!=expected_current for x in current): raise Reject("target drift")
    if [x["image_id"] for x in protected] != [x.get("image_id") for x in source_record["protected_non_target_inventory"]]: raise Reject("protected drift")
    for target in targets:
        if _run(runner,["/usr/bin/docker","image","inspect",target["image_id"],"--format","{{.Id}} "]).strip()!=target["image_id"]: raise Reject("immutable image missing")
    source_sha=hashlib.sha256((pathlib.Path(deploy_dir)/("%s.json" % source_record["record_id"])).read_bytes()).hexdigest()
    record={"schema_version":"1","task_id":binding["task_id"],"nonce":binding["nonce"],"authority":binding["authority"],"canonical_task_sha256":binding["canonical_sha256"],"release_id":release,"source_deploy_task_id":source_task_id,"source_deploy_record_id":source_record["record_id"],"source_deploy_record_sha256":source_sha,"current_targets":current,"target_images":[{"service":x["service"],"image_id":x["image_id"],"repo_digest":x.get("repo_digest")} for x in targets],"protected_non_target_inventory":protected}
    rid,rsha=_atomic_record(record,rollback_dir)
    # Fixed argv, exactly eight services; no pull/migration/non-target path exists.
    # The base file addresses those services by tag and this host holds the images
    # by id only, so the override below is what makes the argv resolvable at all.
    override=None
    try:
        override=_override(targets)
        _run(runner,["/usr/bin/docker","compose","--env-file",ENV_FILE,"-p",PROJECT,"-f",COMPOSE,"-f",override,"up","-d","--no-deps","--force-recreate",*SERVICES],"docker rollback")
    finally:
        if override is not None:
            # Best effort: the file holds nothing but image ids, and a cleanup failure
            # must never replace the real reason a rollback was refused.
            try: os.unlink(override)
            except OSError: pass
    _await_api_health(runner,collector,targets[0]["image_id"],sleeper)
    after=_inventory(runner,SERVICES); after_protected=_inventory(runner,PROTECTED)
    if any(x["running"] is not True or x["status"]!="running" for x in after) or [x["container_id"] for x in after_protected] != [x["container_id"] for x in protected]: raise Reject("postcheck")
    return {"rollback_source":"PASS","lineage":"PASS","target_derivation":"PASS","fresh_drift":"PASS","rollback_record":"PASS","fixed_scope":"PASS","postcheck":"PASS","source_deploy_task_id":source_task_id,"source_deploy_record_id":source_record["record_id"],"source_deploy_record_sha256":source_sha,"rollback_record_id":rid,"rollback_record_sha256":rsha}
