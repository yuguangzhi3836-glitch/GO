"""Production transport signature verifier regression; no external secrets."""
import base64
import pathlib
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hk_agent import transport


def _verified(value, key_path):
    try:
        transport.verify(value, key_path)
        return True
    except transport.Reject:
        return False


def run():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    task = {"schema_version":"1","task_id":"transport-fixture","environment":"HK-STAGING-01","action_id":"CONTROL_PLANE_HEALTH","issued_at":"2026-01-01T00:00:00.000000+00:00","expires_at":"2099-01-01T00:00:00.000000+00:00","nonce":"transport-fixture-nonce","parameters":{},"authority":"GO-COMMAND-CENTER"}
    task["signature"] = private.sign(transport.canonical(task)).hex()
    with tempfile.TemporaryDirectory(prefix="go-hk-transport-regression-") as raw:
        key_path = pathlib.Path(raw) / "task-verify.pub"
        key_path.write_bytes(public + b"\n")
        base64_task = dict(task); base64_task["signature"] = base64.b64encode(bytes.fromhex(task["signature"])).decode("ascii")
        uppercase_task = dict(task); uppercase_task["signature"] = task["signature"].upper()
        short_task = dict(task); short_task["signature"] = task["signature"][:-1]
        invalid_task = dict(task); invalid_task["signature"] = "g" * 128
        wrong_task = dict(task); wrong_task["signature"] = "00" * 64
        tampered_task = dict(task); tampered_task["environment"] = "OTHER"
        evidence = {"task_id":"e","signature":"placeholder"}
        signed_evidence = transport.sign(evidence, _private_pem(private, raw))
        evidence_base64_preserved = len(base64.b64decode(signed_evidence["signature"], validate=True)) == 64
        folder = pathlib.Path(raw) / "tasks"
        folder.mkdir()
        for name in ("historical-task-a", "historical-task-b", "target-task"):
            (folder / (name + ".json")).write_text("{}")
        selected = transport.select_task_sources(folder, "target-task")
        def rejected_selector(value):
            try:
                transport.select_task_sources(folder, value)
                return False
            except transport.Reject:
                return True
        selector_only_target = [x.name for x in selected] == ["target-task.json"]
        return {
            "PRODUCTION_VALID_HEX_SIGNATURE": _verified(task, key_path),
            "PRODUCTION_BASE64_SIGNATURE": not _verified(base64_task, key_path),
            "PRODUCTION_UPPERCASE_HEX_SIGNATURE": not _verified(uppercase_task, key_path),
            "PRODUCTION_WRONG_LENGTH_SIGNATURE": not _verified(short_task, key_path),
            "PRODUCTION_INVALID_HEX_SIGNATURE": not _verified(invalid_task, key_path),
            "PRODUCTION_WRONG_SIGNATURE": not _verified(wrong_task, key_path),
            "PRODUCTION_TAMPERED_MANIFEST": not _verified(tampered_task, key_path),
            "EVIDENCE_BASE64_PROTOCOL_PRESERVED": evidence_base64_preserved,
            "EXACT_SELECTOR_TARGET_ONLY": selector_only_target,
            "EXACT_SELECTOR_PATH_TRAVERSAL_REJECT": rejected_selector("../x"),
            "EXACT_SELECTOR_ABSOLUTE_PATH_REJECT": rejected_selector("/x"),
            "EXACT_SELECTOR_GLOB_REJECT": rejected_selector("*"),
        }


def _private_pem(private, raw):
    path = pathlib.Path(raw) / "test-evidence.pem"
    path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()))
    return path
