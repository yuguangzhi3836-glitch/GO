"""Exercise an existing immutable image in disposable loopback-only isolation."""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "image-acceptance-evidence"
IMAGE = "sha256:47bb66c429868689e922ecc1bee668e9c12bfa24e2cddca1717e16887f34115d"
PACKAGE = "b297f139a236681019fe894f4f1a94068636649e1235a20502a383a610f16f63"
TREE = "995d0d83faf883bec980c896fe8a17b0f12360fa"
SOURCE_SHA = "1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4"
SOURCE_COMMIT = "c6ea4dd670db36e71f3839fb31e656a5c8806858"
OUT.mkdir(exist_ok=True)
def run(*args, **kw):
    return subprocess.check_output(args, text=True, **kw).strip()
def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")
spec = importlib.util.spec_from_file_location("package_checker", ROOT / "packaging/canonical-runtime/package.py")
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)
session = uuid.uuid4().hex
state_parent = pathlib.Path(os.environ["RUNNER_TEMP"]) / ("image-session-" + session)
state_parent.mkdir()
private_parent = state_parent / "private"
private_parent.mkdir(mode=0o700)
state = private_parent / "state"
cid = None
status = "HOLD"
failure_type = None
try:
    assert run("git", "rev-parse", "HEAD:application") == TREE, "CHECKOUT_APPLICATION_TREE_MISMATCH"
    archives = list(pathlib.Path(os.environ["FIXED_IMAGE_ARTIFACT"]).rglob("runtime-package.tar.gz"))
    assert len(archives) == 1, "EXACTLY_ONE_RUNTIME_PACKAGE_REQUIRED"
    assert pack.sha(archives[0]) == PACKAGE, "PACKAGE_SHA_MISMATCH"
    extracted = state_parent / "package"
    pack.extract(archives[0], extracted)
    bundle = extracted / "bundle"
    hashes = json.loads((bundle / "SHA256.json").read_text())
    assert set(hashes) == {p.name for p in bundle.iterdir()} - {"SHA256.json"}
    for name, digest in hashes.items():
        assert pack.sha(bundle / name) == digest, name
    meta = json.loads((bundle / "CANDIDATE.json").read_text())
    assert (meta["image_id"], meta["application_git_tree"], meta["source_tree_sha256"], meta["source_commit"]) == (IMAGE, TREE, SOURCE_SHA, SOURCE_COMMIT)
    source = state_parent / "archive-source"
    pack.extract(bundle / "source.tar.gz", source)
    fp = pack.fingerprint(source / "application")
    assert fp == json.loads((bundle / "SOURCE_FINGERPRINT.json").read_text())
    assert pack.check_contract(source) == json.loads((bundle / "DEPLOYMENT_CONTRACT_SHA256.json").read_text())
    runtime_fp = {p:h for p,h in fp.items() if p not in pack.IMAGE_EXCLUSIONS}
    subprocess.run(["docker", "load", "-i", str(bundle / "image.tar.gz")], check=True)
    assert pack.inspect(IMAGE)["Id"] == IMAGE
    write("image-inspect.json", pack.inspect(IMAGE))
    freeze = run("docker", "run", "--rm", "--network", "none", "--entrypoint", "python", IMAGE, "-m", "pip", "freeze", "--all")
    (OUT / "pip-freeze-before.txt").write_text(freeze + "\n")
    assert freeze == (bundle / "pip-freeze.txt").read_text().strip(), "PACKAGED_DEPENDENCY_MISMATCH"
    unit_results = []
    for label, test_path in (("pagination", "/harness/test_pagination.py"),
                             ("original-refund", "/app/tests/test_depth41_transaction_views.py::test_admin_hotel_refund_amount_is_real_column")):
        with (OUT / (label + ".log")).open("w") as log:
            result = subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only",
                "--tmpfs", "/tmp:rw,nosuid,size=256m", "-w", "/tmp",
                "-e", "PYTHONPATH=/app/src", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-e", "GO_MEDIA_CACHE_DIR=/tmp/media", "-e", "DATABASE_URL=sqlite:////tmp/unit.db",
                "--mount", f"type=bind,source={ROOT / 'ci/admin-pagination/test_pagination.py'},target=/harness/test_pagination.py,readonly",
                "--mount", f"type=bind,source={OUT},target=/evidence",
                "--entrypoint", "python", IMAGE, "-B", "-m", "pytest", "-p", "no:cacheprovider",
                "--junitxml=/evidence/" + label + ".xml", test_path], stdout=log, stderr=subprocess.STDOUT)
        print((OUT / (label + ".log")).read_text(), flush=True)
        unit_results.append(result.returncode)
    binding = {"candidate_commit": SOURCE_COMMIT, "harness_commit": run("git","rev-parse","HEAD"),
        "application_git_tree": TREE, "source_tree_sha256": SOURCE_SHA,
        "image_runtime_source_sha256": hashlib.sha256("".join(f"{p}\0{h}\n" for p,h in sorted(runtime_fp.items())).encode()).hexdigest(),
        "canonical_source_files":1332,"image_runtime_source_files":1328,"image_id":IMAGE,
        "package_sha256":PACKAGE,"artifact_id":10328889188,"artifact_run":34795198840,
        "session_id":session,"started_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
        "image_network":"none","browser_network":"same network namespace via nsenter",
        "runtime_mode":"image-owned acceptance_runtime fixture launcher; not default CMD or 8 workers",
        "harness_sha256": {p:pack.sha(ROOT / p) for p in ("ci/journey-v2/browser.mjs", "ci/journey-v2/hotel-depth.mjs", "ci/journey-v2/ledger.py", "ci/journey-v2/hotel-ledger.py", "ci/admin-pagination/test_pagination.py")},
        "source_mounted":False,"dependency_install_inside_image":False,
        "cache_exclusions":sorted(pack.IMAGE_EXCLUSIONS),"hong_kong":"NOT_ACCESSED","production":"HOLD"}
    write("source-binding.json", binding)
    cid = run("docker","run","-d","--network","none","--read-only","--tmpfs","/tmp:rw,nosuid,size=128m",
        "--mount",f"type=bind,source={private_parent},target={private_parent}",
        "--mount",f"type=bind,source={bundle / 'SOURCE_FINGERPRINT.json'},target=/harness/SOURCE_FINGERPRINT.json,readonly",
        "--mount",f"type=bind,source={ROOT / 'ci/image-acceptance/runtime.py'},target=/harness/runtime.py,readonly",
        "--entrypoint","python",IMAGE,"-B","/harness/runtime.py",
        "--source","/app","--fingerprint","/harness/SOURCE_FINGERPRINT.json",
        "--expected-tree",SOURCE_SHA,"--state",str(state),"--port","4186",
        "--journey-suppliers","--hotel-price-scenarios")
    info = json.loads(run("docker","inspect",cid))[0]
    pid = str(info["State"]["Pid"])
    write("container-binding.json",{"container_id":cid,"image_id":info["Image"],"network_mode":info["HostConfig"]["NetworkMode"],"readonly_rootfs":info["HostConfig"]["ReadonlyRootfs"],"host_pid":pid,"session_id":session})
    for _ in range(180):
        ready = subprocess.run(["docker","exec",cid,"python","-c","import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:4186/__acceptance/binding',timeout=2)); assert d['source_tree_sha256']=='"+SOURCE_SHA+"'"],capture_output=True)
        if ready.returncode == 0: break
        if run("docker","inspect","-f","{{.State.Running}}",cid) != "true":
            raise RuntimeError("IMAGE_ACCEPTANCE_RUNTIME_EXITED")
        time.sleep(.5)
    else: raise TimeoutError("IMAGE_ACCEPTANCE_NOT_READY")
    with (OUT / "browser.log").open("w") as log:
        browser = subprocess.run(["sudo","nsenter","--target",pid,"--net","--",
            "env",f"HOME={os.environ['HOME']}",f"PATH={os.environ['PATH']}",
            f"GO_JOURNEY_STATE={state}",f"GO_JOURNEY_EVIDENCE={OUT}",
            f"GITHUB_RUN_ID={os.environ.get('GITHUB_RUN_ID','')}",
            f"GITHUB_JOB={os.environ.get('GITHUB_JOB','')}",
            f"RUNNER_OS={os.environ.get('RUNNER_OS','')}",
            "node",str(ROOT / "ci/journey-v2/browser.mjs")],stdout=log,stderr=subprocess.STDOUT)
    print((OUT / "browser.log").read_text(),flush=True)
    audits = []
    for script in ("ledger.py","hotel-ledger.py"):
        with (OUT / (script + ".log")).open("w") as log:
            result = subprocess.run(["sudo","python3","-B",str(ROOT / "ci/journey-v2" / script),str(state),str(OUT)],stdout=log,stderr=subprocess.STDOUT)
        print((OUT / (script + ".log")).read_text(),flush=True)
        audits.append(result.returncode)
    for name in ("runtime-binding.json","fixture-identities.json","hotel-price-fixtures.json"):
        subprocess.run(["sudo","cp",str(state / name),str(OUT / name)],check=True)
    after = run("docker","exec",cid,"python","-m","pip","freeze","--all")
    (OUT / "pip-freeze-after.txt").write_text(after + "\n")
    assert freeze == after, "DEPENDENCY_DRIFT"
    # Recheck original image bytes after acceptance: no committed changes allowed.
    assert pack.inspect(IMAGE)["Id"] == IMAGE
    assert browser.returncode == 0 and not any(audits + unit_results), "BROWSER_LEDGER_OR_UNIT_FAILED"
    status = "PASS_SCOPED"
except Exception as exc:
    status = "FAIL"
    failure_type = type(exc).__name__
    raise
finally:
    if cid:
        result = subprocess.run(["docker","logs",cid],capture_output=True,text=True)
        (OUT / "runtime.log").write_text(result.stdout + result.stderr)
        subprocess.run(["docker","rm","-f",cid],check=False)
    write("RESULT.json",{"result":status,"failure_type":failure_type,"image_id":IMAGE,"package_sha256":PACKAGE,"source_tree_sha256":SOURCE_SHA,
        "session_id":session,"finished_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
        "postgres":"NOT_RUN","worker_liveness":"NOT_RUN","physical_device":"NOT_RUN",
        "default_entrypoint":"NOT_RUN","sealed_node":"HOLD","final_release":"HOLD","deployment":"NOT_RUN","production":"HOLD"})
    # Private credentials/database remain outside public evidence and are removed.
    subprocess.run(["sudo","chown","-R",f"{os.getuid()}:{os.getgid()}",str(OUT)],check=False)
    write("SHA256.json",{p.relative_to(OUT).as_posix():pack.sha(p) for p in sorted(OUT.rglob("*")) if p.is_file() and p.name!="SHA256.json"})
    subprocess.run(["sudo","rm","-rf",str(state_parent)],check=False)
