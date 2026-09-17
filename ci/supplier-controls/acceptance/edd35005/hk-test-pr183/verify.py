import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from cryptography.hazmat.primitives import serialization

root = Path(__file__).resolve().parent
contract = json.loads((root / "identities.json").read_text())
request = json.loads((root / "request.json").read_text())
task = json.loads((root / "task.json").read_text())
identities = {item["role"]: item for item in contract["identities"]}

def verify(obj, role, filename):
    identity = identities[role]
    raw = (root / filename).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == identity["public_key_file_sha256"]
    key = serialization.load_ssh_public_key(raw)
    key_bytes = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert hashlib.sha256(key_bytes).hexdigest() == identity["public_key_raw_sha256"]
    signature = bytes.fromhex(obj["signature"]) if role == "TASK" else base64.b64decode(obj["signature"], validate=True)
    unsigned = {k: v for k, v in obj.items() if k != "signature"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    key.verify(signature, canonical)
    return {"signature": "PASS", "identity": identity["identity_id"],
            "file_sha256": hashlib.sha256((root / ("task.json" if role == "TASK" else "evidence.json")).read_bytes()).hexdigest(),
            "unsigned_canonical_sha256": hashlib.sha256(canonical).hexdigest()}

result = {"task": verify(task, "TASK", "task.pub"), "candidate_sha": task["parameters"]["source"]["commit_sha"]}
assert result["candidate_sha"] == "edd3500575d2f2b81298cc9273025e0a3b734897"
assert task["parameters"]["source"]["pr_number"] == "183"
assert task["action_id"] == request["action_id"] == "HK_STAGING_TEST_PR"
assert task["environment"] == request["environment"] == "HK-STAGING-01"
assert task["task_id"].endswith("-" + hashlib.sha256(request["request_id"].encode()).hexdigest()[:12])
assert identities["TASK"]["public_key_raw_sha256"] != identities["EVIDENCE"]["public_key_raw_sha256"]
result["request_task_binding"] = "PASS"
evidence_file = root / "evidence.json"
if evidence_file.exists():
    evidence = json.loads(evidence_file.read_text())
    result["evidence"] = verify(evidence, "EVIDENCE", "evidence.pub")
    for field in ("task_id", "nonce", "action_id", "environment"):
        assert evidence[field] == task[field], field
    start = datetime.fromisoformat(evidence["started_at"].replace("Z", "+00:00"))
    assert datetime.fromisoformat(task["issued_at"].replace("Z", "+00:00")) <= start <= datetime.fromisoformat(task["expires_at"].replace("Z", "+00:00"))
    result["evidence_task_binding"] = "PASS"
    result["evidence_status"] = evidence["status"]
else:
    result["evidence"] = "NOT_PUBLISHED"
(root / "VERIFICATION.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps(result, sort_keys=True))
