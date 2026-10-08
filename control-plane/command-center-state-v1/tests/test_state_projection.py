"""Isolated tests for the CONTROL_STATE_V1 projection (scope: state + status only).

Standard library plus cryptography. No network, no Git, no runtime path, no live
Control Plane state.

Identity discipline under test: the Command Center task signer and the Hong Kong
evidence signer are **separate** Ed25519 identities. Every fixture that needs both
generates two independent keys; no fixture uses one key for both roles.
"""
import argparse
import base64
import datetime as dt
import importlib.machinery
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("state_projection", str(ROOT / "state_projection.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
sp = importlib.util.module_from_spec(spec)
loader.exec_module(sp)

AT = sp.parse_time("2026-09-14T12:00:00Z")


# --------------------------------------------------------------------------- #
# The sibling Deploy Readiness evaluator, loaded for real
#
# This component used to be pinned only against a document built from its own
# DEPLOY_READINESS_GATES constant, so the two sides could disagree while every
# test here still passed. They did: the evaluator made every gate mandatory and
# added DEPLOYMENT_AUTHORIZATION and BRIDGE_ACCEPTANCE, and the projector went on
# refusing the real document with DEPLOY_READINESS_UNREADABLE. The tests below
# therefore load the real evaluator and the evaluator's own fixture builder --
# neither of which knows this file's constants -- and pin the contract from the
# outside instead of from a copy of itself.
# --------------------------------------------------------------------------- #
READINESS_COMPONENT = ROOT.parent / "command-center-deploy-readiness-v1"
# The exporter that writes the facts this layer reads, loaded for the same reason
# the readiness evaluator above is: a contract pinned only against a fixture built
# from this component's own constants cannot fail, and therefore protects nothing.
REQUESTS_COMPONENT = ROOT.parent / "command-center-request-visibility-v1"
FACT_EXPORTER = REQUESTS_COMPONENT / "command-center" / "go-request-fact-export"
FACT_CONTRACT = REQUESTS_COMPONENT / "contracts" / "request_fact_v1.schema.json"
# The Bridge is where a Request is accepted or refused, so its channel config is
# the authority for what an action may be. Loaded from the outside for the same
# reason as the two above: a constant compared against a fixture built from that
# constant cannot fail.
BRIDGE_COMPONENT = ROOT.parent / "boss-deploy-request-v1"
READINESS_EVALUATOR = READINESS_COMPONENT / "command-center" / "go-deploy-readiness"
READINESS_FIXTURES = READINESS_COMPONENT / "tests" / "test_deploy_readiness.py"
_SIBLINGS = {}


def sibling(name, path):
    """Load a sibling component module on demand, with a usable failure message.

    Loaded lazily so a copy of this component without its sibling reports one
    clear error instead of an import-time crash naming no test.
    """
    if name not in _SIBLINGS:
        if not path.is_file():
            raise AssertionError(
                "%s is missing at %s. This test pins two components against each other on "
                "purpose, so it cannot run against a copy of only one of them." % (name, path))
        loader = importlib.machinery.SourceFileLoader("sibling_" + name, str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        _SIBLINGS[name] = module
    return _SIBLINGS[name]


def real_evaluator():
    """The real go-deploy-readiness module, not a description of it."""
    return sibling("readiness", READINESS_EVALUATOR)


def real_readiness_fixture():
    """The evaluator's own fixture builder -- the authoritative input constructor."""
    return sibling("readiness_fixture", READINESS_FIXTURES)


def real_fact_exporter():
    """The real go-request-fact-export module."""
    return sibling("fact_exporter", FACT_EXPORTER)


def evaluator_gate_blocks():
    """The evaluator's gate tuples as its source declares them.

    Read from the source rather than imported, so a gate the evaluator adds or
    removes is visible here even when it keeps exporting the same names.
    """
    source = READINESS_EVALUATOR.read_text(encoding="utf-8")
    blocks = {}
    for name in ("MANDATORY_GATES", "ADVISORY_GATES"):
        match = re.search(r"^%s = \(([^)]*)\)" % name, source, re.M)
        if match is None:
            raise AssertionError("the evaluator no longer declares %s" % name)
        blocks[name] = tuple(re.findall(r'"([A-Z_]+)"', match.group(1)))
    return blocks


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def key_pair(name):
    """An Ed25519 key plus its own public key path, in a directory that outlives it."""
    from cryptography.hazmat.primitives import serialization
    directory = pathlib.Path(tempfile.mkdtemp(prefix="ccs-key-"))
    key = __import__("cryptography.hazmat.primitives.asymmetric.ed25519",
                     fromlist=["Ed25519PrivateKey"]).Ed25519PrivateKey.generate()
    private = directory / ("%s.pem" % name)
    public = directory / ("%s.pub" % name)
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return key, str(public)


def sign(obj, key, encoding):
    unsigned = {k: v for k, v in obj.items() if k != "signature"}
    raw = key.sign(sp.canonical(unsigned))
    out = dict(unsigned)
    out["signature"] = raw.hex() if encoding == "hex" else base64.b64encode(raw).decode("ascii")
    return out


def task(action="HK_STAGING_VERIFY", **over):
    issued = AT - dt.timedelta(minutes=30)
    value = {
        "schema_version": "1", "task_id": "task-%s" % action.lower().replace("_", "-"),
        "nonce": "nonce-0001", "issued_at": sp.iso(issued),
        "expires_at": sp.iso(issued + dt.timedelta(minutes=15)),
        "authority": "GO-COMMAND-CENTER", "environment": "HK-STAGING-01", "action_id": action,
        "parameters": {"release_id": "release-1",
                       "candidate_image_id": "sha256:" + "a" * 64,
                       "expected_current_image_id": "sha256:" + "a" * 64},
        # Placeholder envelope. Without a verifier key the projection must degrade
        # to OBSERVED, so a placeholder never buys a PROVEN claim.
        "signature": "0" * 128,
    }
    value.update(over)
    return value


def evidence(tk, **over):
    started = sp.parse_time(tk["issued_at"]) + dt.timedelta(seconds=30)
    value = {
        "schema_version": "1", "task_id": tk["task_id"], "nonce": tk["nonce"],
        "action_id": tk["action_id"], "environment": tk["environment"], "status": "SUCCESS",
        "started_at": sp.iso(started), "completed_at": sp.iso(started + dt.timedelta(seconds=20)),
        "agent_version": "0.5.7-rebuilt", "executor_version": "0.4.3-rollback-runtime",
        "executor_result": "VERIFY_OK", "gate_results": {"api_health": "PASS"},
        "signature": base64.b64encode(b"0" * 64).decode("ascii"),
    }
    value.update(over)
    return value


def health_pair(offset_minutes, completed_at=None):
    issued = AT - dt.timedelta(minutes=offset_minutes + 1)
    tk = task(action="CONTROL_PLANE_HEALTH", task_id="health-1", nonce="nonce-health",
              issued_at=sp.iso(issued), expires_at=sp.iso(issued + dt.timedelta(minutes=15)),
              parameters={})
    stamp = completed_at or sp.iso(AT - dt.timedelta(minutes=offset_minutes))
    ev = evidence(tk, executor_version="0.5.7-rebuilt",
                  executor_result={"hostname": "iZj6ccs8t04f1p4d8pe69zZ",
                                   "agent_version": "0.5.7-rebuilt",
                                   "tasks_repo_connectivity": True,
                                   "evidence_repo_connectivity": True},
                  started_at=stamp, completed_at=stamp)
    return tk, ev


def layout(tasks=(), evidences=(), requests=()):
    root = pathlib.Path(tempfile.mkdtemp(prefix="ccs-bus-"))
    (root / "tasks").mkdir()
    (root / "evidence").mkdir()
    for name, value in tasks:
        (root / "tasks" / name).write_text(json.dumps(value), encoding="utf-8")
    for name, value in evidences:
        (root / "evidence" / name).write_text(json.dumps(value), encoding="utf-8")
    requests_dir = None
    if requests:
        requests_dir = root / "requests"
        requests_dir.mkdir()
        for name, value in requests:
            (requests_dir / name).write_text(json.dumps(value), encoding="utf-8")
    return root, requests_dir


def fake_args(**over):
    base = {"tasks_ref": "main", "tasks_head": "5b7caecd8e47751b13e4661d14b27880f19d1d71",
            "evidence_ref": "permission-test",
            "evidence_head": "350dc628075ebd4cea9a3a2d8040caf23f957f57",
            "go_ref": "main", "go_head": "8ffcde66d36c1bbf849218529ef015f6e81725af"}
    base.update(over)
    return argparse.Namespace(**base)


def ssh_fingerprint(pub_path):
    """The SSH SHA256 fingerprint of a public key file, or None."""
    if not pub_path:
        return None
    return sp.Verifier(pub_path, sp.TASK_VERIFIER_IDENTITY, "hex").ssh_fingerprint


def identity_contract(task_pub=None, evidence_pub=None, task_pin=None, evidence_pin=None):
    """A temporary VERIFIER_IDENTITIES_V1 contract pinning the fixture keys.

    Pins default to the fingerprints of the supplied keys. A role with no key is
    pinned to a distinct placeholder, which is never compared because a verifier
    with no key file reports MISSING_KEY before any fingerprint check.
    """
    directory = pathlib.Path(tempfile.mkdtemp(prefix="ccs-identity-"))
    document = {
        "schema_version": "1",
        "contract": sp.IDENTITY_CONTRACT_NAME,
        "scope": sp.CONTRACT_SCOPE,
        "identities": [
            {"identity_id": "TEST-CC-TASK-SIGNER", "role": sp.ROLE_TASK,
             "display_name": sp.TASK_VERIFIER_IDENTITY, "algorithm": "Ed25519",
             "signature_encoding": "hex",
             "public_key_ssh_sha256": (task_pin or ssh_fingerprint(task_pub)
                                       or "SHA256:no-task-key-in-this-fixture")},
            {"identity_id": "TEST-HK-EVIDENCE-SIGNER", "role": sp.ROLE_EVIDENCE,
             "display_name": sp.EVIDENCE_VERIFIER_IDENTITY, "algorithm": "Ed25519",
             "signature_encoding": "base64",
             "public_key_ssh_sha256": (evidence_pin or ssh_fingerprint(evidence_pub)
                                       or "SHA256:no-evidence-key-in-this-fixture")},
        ],
    }
    path = directory / "VERIFIER_IDENTITIES_V1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def build(root, req_dir=None, task_pub=None, evidence_pub=None, go_repo=None, at=None,
          contract=None, facts_root=None, readiness=None, **flags):
    """Build the state without going through the CLI.

    A contract pinning the fixture keys is generated unless one is supplied, so
    PROVEN in these tests always means "bound to a published identity", never
    merely "a signature verified".
    """
    loaded = sp.Loaded()
    sp.load_tasks(str(root), loaded)
    sp.load_evidence(str(root), loaded)
    sp.load_requests(str(req_dir) if req_dir else None, loaded)
    sp.load_request_facts(str(facts_root) if facts_root else None, loaded)
    sp.load_deploy_readiness(str(readiness) if readiness else None, loaded)
    if contract is None:
        contract = identity_contract(task_pub, evidence_pub)
    identity = sp.IdentityContract(contract)
    task_verifier = sp.Verifier(task_pub, sp.TASK_VERIFIER_IDENTITY, "hex",
                                expected=identity.expected(sp.ROLE_TASK))
    evidence_verifier = sp.Verifier(evidence_pub, sp.EVIDENCE_VERIFIER_IDENTITY, "base64",
                                    expected=identity.expected(sp.ROLE_EVIDENCE))
    separated = sp.separated(task_verifier, evidence_verifier, loaded)
    task_bound, evidence_bound = sp.bind_identities(task_verifier, evidence_verifier, loaded)
    binding_gate = bool(separated and task_bound and evidence_bound)
    if not task_bound or not separated:
        task_verifier = task_verifier.disabled_copy()
    if not evidence_bound or not separated:
        evidence_verifier = evidence_verifier.disabled_copy()
    fail_closed_reasons = sorted({
        "%s:%s" % (role, verifier.binding)
        for role, verifier in (("task", task_verifier), ("evidence", evidence_verifier))
        if verifier.binding != sp.BINDING_BOUND
    } | ({"roles:IDENTITY_COLLISION"} if not separated else set()))
    options = {
        "stale_seconds": flags.pop("stale_seconds", 86400),
        "liveness_window": flags.pop("liveness_window", sp.LIVENESS_FRESHNESS_WINDOW_SECONDS),
        "verification_window": flags.pop("verification_window", 86400),
        "stuck_after": flags.pop("stuck_after", 900),
        "recent_window": flags.pop("recent_window", 604800),
        "go_repo": go_repo,
        "repository_main_sha": flags.pop("repository_main_sha", None),
        "identities_separated": separated,
        "identity_contract": identity,
        "proven_allowed": binding_gate,
        "fail_closed_reasons": fail_closed_reasons,
        "args": fake_args(),
    }
    state = sp.build_state(loaded, task_verifier, evidence_verifier, at or AT, options)
    status = sp.build_status(state, sp.verdict_for(state["control_state"]))
    return loaded, state, status


def project(root, req_dir=None, **flags):
    """Build and return only the state document."""
    return build(root, req_dir, **flags)[1]


# --------------------------------------------------------------------------- #
# CC V1-05 fixtures: Bridge Request facts
#
# The fact shape is pinned here a second time on purpose. If the exported
# contract and the projector ever disagree, these tests fail instead of the
# disagreement reaching a projection.
# --------------------------------------------------------------------------- #
def fact_reason(code=None, name=None, origin="BRIDGE_REJECT_TOKEN"):
    if code is None:
        return {"applicable": False, "code": None, "class": None, "origin": None,
                "preserved_verbatim": True}
    return {"applicable": True, "code": code, "class": name, "origin": origin,
            "preserved_verbatim": True}


def no_binding():
    return {"claimed": False, "task_id": None, "task_sha256": None, "task_commit": None,
            "proof_required": False, "proof": "NOT_APPLICABLE"}


def accepted_binding(task, request_id):
    body = {k: v for k, v in task.items() if not k.startswith("_")}
    return {"claimed": True, "task_id": task["task_id"],
            "task_sha256": sp.digest(body), "task_commit": "c" * 40,
            "proof_required": True, "proof": "TASK_SIGNATURE_AND_DIGEST_PREFIX"}


def request_fact(kind, request_id, action_id="HK_STAGING_VERIFY", legacy=False, **over):
    """A Bridge Request fact.

    The default is the shape the exporter writes now: a semantic identity, an
    id covering the body except the two time fields, and first_observed_at.
    `legacy=True` builds what was written before that: observed_at and no
    semantic_id, with the id covering the whole body. Both shapes are on the
    control bus at once, so both have to be constructible here.
    """
    instant = over.pop("first_observed_at", over.pop("observed_at",
                                                     "2026-09-14T11:30:00Z"))
    fact = {
        "schema_version": "1", "kind": kind, "request_id": request_id, "action_id": action_id,
        "environment": "HK-STAGING-01", "nonce": over.pop("nonce", None),
        "observed_at" if legacy else "first_observed_at": instant,
        "time_source": over.pop("time_source", "POLL_JOURNAL"),
        "submission": over.pop("submission",
                               {"pr_number": "7", "head_sha": "b" * 40,
                                "submission_key": "7:" + "b" * 40}),
        "source": over.pop("source",
                           {"repository": sp.TASKS_REPOSITORY,
                            "ref": "refs/remotes/origin/boss-request-1",
                            "head_sha": "b" * 40, "path": "requests/request-1.json",
                            "request_sha256": "0" * 64}),
        "reason": over.pop("reason", fact_reason()),
        "binding": over.pop("binding", no_binding()),
        "authority": over.pop("authority",
                              {k: False for k in sp.REQUEST_FACT_AUTHORITY_KEYS}),
    }
    fact.update(over)
    if legacy:
        fact["fact_id"] = "request-fact-" + sp.digest(
            {k: v for k, v in fact.items() if k != "fact_id"})[:32]
        return fact
    fact["semantic_id"] = sp.digest({k: fact[k] for k in sp.REQUEST_FACT_IDENTITY_KEYS})
    fact["fact_id"] = "request-fact-" + sp.digest(
        {k: v for k, v in fact.items() if k not in sp.REQUEST_FACT_ID_EXCLUDED})[:32]
    return fact


def facts_root_of(facts=(), index=None):
    """An export root in the shape the read-only exporter writes."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="ccs-facts-"))
    folder = root / sp.REQUEST_FACTS_DIRNAME
    folder.mkdir()
    for fact in facts:
        (folder / (fact["fact_id"] + ".json")).write_text(json.dumps(fact), encoding="utf-8")
    if index is not None:
        (root / sp.REQUEST_FACT_INDEX_NAME).write_text(json.dumps(index), encoding="utf-8")
    return root


def request_file(request_id="request-1", action="HK_STAGING_VERIFY", **over):
    value = {"schema_version": "1", "request_id": request_id, "action_id": action,
             "environment": "HK-STAGING-01", "requested_at": "2026-09-14T11:00:00Z"}
    value.update(over)
    return value


def task_identity(request_id):
    """A Task identity built the way the Bridge builds one, from the request digest."""
    return "go-boss-request-verify-20260914T110000Z-" + __import__("hashlib").sha256(
        request_id.encode()).hexdigest()[:sp.REQUEST_TASK_DIGEST_LINK]


# --------------------------------------------------------------------------- #
class PrimitivesTests(unittest.TestCase):
    def test_canonical_is_key_order_independent(self):
        self.assertEqual(sp.canonical({"b": 1, "a": 2}), sp.canonical({"a": 2, "b": 1}))

    def test_digest_is_stable(self):
        self.assertEqual(sp.digest({"a": [1, 2]}), sp.digest({"a": [1, 2]}))

    def test_unknown_discards_value(self):
        self.assertEqual(sp.unknown("r")["value"], None)
        self.assertEqual(sp.unknown("r")["state"], sp.STATE_UNKNOWN)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            sp.parse_time("2026-09-14T12:00:00")

    def test_scope_is_declared(self):
        self.assertEqual(sp.CONTRACT_SCOPE, "CONTROL_STATE_AND_STATUS_ONLY")

    def test_instance_normalisation_collapses_three_spellings(self):
        for value in ("i-j6ccs8t04f1p4d8pe69z", "iZj6ccs8t04f1p4d8pe69zZ", "j6ccs8t04f1p4d8pe69z"):
            self.assertEqual(sp.normalize_instance(value), "i-j6ccs8t04f1p4d8pe69z")

    def test_instance_normalisation_rejects_other_strings(self):
        self.assertIsNone(sp.normalize_instance("command-center"))
        self.assertIsNone(sp.normalize_instance(None))


# --------------------------------------------------------------------------- #
class VerifierIdentityTests(unittest.TestCase):
    """The task signer and the evidence signer must be different identities."""

    def setUp(self):
        self.task_key, self.task_pub = key_pair("cc-task")
        self.evidence_key, self.evidence_pub = key_pair("hk-evidence")

    def test_two_keys_have_different_fingerprints(self):
        a = sp.Verifier(self.task_pub, sp.TASK_VERIFIER_IDENTITY, "hex")
        b = sp.Verifier(self.evidence_pub, sp.EVIDENCE_VERIFIER_IDENTITY, "base64")
        self.assertTrue(a.available and b.available)
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def test_valid_task_key_and_valid_evidence_key_pass(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertTrue(entry["task_signature_verified"])
        self.assertTrue(entry["evidence"]["signature_verified"])
        self.assertEqual(entry["lifecycle"], "COMPLETE")
        self.assertTrue(state["verification"]["identities_separated"])

    def test_task_signed_with_the_evidence_key_fails(self):
        tk = sign(task(), self.evidence_key, "hex")
        _, state, _ = build(*layout(tasks=[("t.json", tk)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertFalse(entry["task_signature_verified"])
        self.assertEqual(entry["lifecycle"], "POLICY_HOLD")
        self.assertEqual(entry["assertion"]["value"], "TASK_SIGNATURE_INVALID")

    def test_evidence_signed_with_the_task_key_fails(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.task_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertFalse(entry["evidence"]["signature_verified"])
        self.assertEqual(entry["lifecycle"], "EVIDENCE_INVALID")
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_tampered_evidence_is_invalid(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        ev["executor_result"] = "TAMPERED"
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        self.assertFalse(state["tasks"][0]["evidence"]["signature_verified"])
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_INVALID")

    def test_missing_keys_never_yield_proven(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]))
        entry = state["tasks"][0]
        self.assertIsNone(entry["task_signature_verified"])
        self.assertIsNone(entry["evidence"]["signature_verified"])
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)
        self.assertEqual(entry["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["verification"]["task"]["signature_verification"], "NOT_PERFORMED")
        self.assertEqual(state["verification"]["evidence"]["signature_verification"], "NOT_PERFORMED")

    def test_only_the_evidence_key_supplied_leaves_tasks_unverified(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertIsNone(entry["task_signature_verified"])
        self.assertTrue(entry["evidence"]["signature_verified"])
        # The Evidence verifies, but the Task it belongs to was never established.
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_only_the_task_key_supplied_never_yields_proven_evidence(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub)
        entry = state["tasks"][0]
        self.assertTrue(entry["task_signature_verified"])
        self.assertIsNone(entry["evidence"]["signature_verified"])
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_broken_key_file_reports_not_performed(self):
        bad = pathlib.Path(tempfile.mkdtemp(prefix="ccs-bad-")) / "bad.pub"
        bad.write_bytes(b"not a key")
        verifier = sp.Verifier(str(bad), sp.TASK_VERIFIER_IDENTITY, "hex")
        self.assertFalse(verifier.available)
        self.assertIsNone(verifier.verify(task(), "hex"))

    def test_a_shared_key_for_both_roles_is_a_collision(self):
        shared_key, shared_pub = key_pair("shared")
        tk = sign(task(), shared_key, "hex")
        ev = sign(evidence(task()), shared_key, "base64")
        loaded, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                                 task_pub=shared_pub, evidence_pub=shared_pub)
        self.assertIn("VERIFIER_IDENTITY_COLLISION", [a["kind"] for a in loaded.anomalies])
        self.assertFalse(state["verification"]["identities_separated"])
        self.assertEqual(state["verification"]["task"]["signature_verification"], "NOT_PERFORMED")
        self.assertNotEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_PROVEN)

    def test_verifier_describe_exposes_identity_and_encoding(self):
        described = sp.Verifier(self.task_pub, sp.TASK_VERIFIER_IDENTITY, "hex").describe()
        self.assertEqual(described["encoding"], "hex")
        self.assertEqual(described["identity"], sp.TASK_VERIFIER_IDENTITY)
        self.assertEqual(described["signature_verification"], "PERFORMED")


# --------------------------------------------------------------------------- #
class PublishedVerifierIdentityTests(unittest.TestCase):
    """CC V1-01. The published verifier identities and the binding they enable.

    A key that merely loads is not the right key: PROVEN additionally requires the
    supplied key to be the identity published in VERIFIER_IDENTITIES_V1.
    """

    REPO_ROOT = ROOT.parents[1]
    IDENTITY_DIR = ROOT / "identity"
    CONTRACT = IDENTITY_DIR / "VERIFIER_IDENTITIES_V1.json"
    TASK_KEY = IDENTITY_DIR / "keys" / "cc-task-manifest-signing.pub"
    EVIDENCE_KEY = IDENTITY_DIR / "keys" / "hk-evidence-signing.pub"
    REAL = ROOT / "tests" / "fixtures" / "real"

    TASK_SSH = "SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns"
    EVIDENCE_SSH = "SHA256:WZ2gG4WHnO5zmijyK8TSOHFpY+EBkk8TWbSbfbRjFNw"

    def project_real(self, task_key=None, evidence_key=None, contract=None):
        return build(str(self.REAL), task_pub=task_key, evidence_pub=evidence_key,
                     contract=str(self.CONTRACT) if contract is None else contract)

    def assert_no_success_claim(self, state):
        """No Task may reach a verified-complete lifecycle or a PROVEN result.

        ``execution_started`` is deliberately excluded: it records that the
        Evidence carries a started_at for this task/nonce, which stays true even
        when the Task's own identity was never established.
        """
        for entry in state["tasks"]:
            self.assertNotEqual(entry["lifecycle"], "COMPLETE", entry["task_id"])
            self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN, entry["task_id"])

    # -- the publication itself ------------------------------------------------
    def test_the_published_contract_pins_two_distinct_identities(self):
        identity = sp.IdentityContract(str(self.CONTRACT))
        self.assertTrue(identity.available, identity.reason)
        task = identity.expected(sp.ROLE_TASK)
        evidence = identity.expected(sp.ROLE_EVIDENCE)
        self.assertEqual(task["ssh_sha256"], self.TASK_SSH)
        self.assertEqual(evidence["ssh_sha256"], self.EVIDENCE_SSH)
        self.assertNotEqual(task["ssh_sha256"], evidence["ssh_sha256"])
        self.assertEqual(task["encoding"], "hex")
        self.assertEqual(evidence["encoding"], "base64")
        self.assertEqual(task["identity_id"], "GO-CC-TASK-MANIFEST-SIGNER")
        self.assertEqual(evidence["identity_id"], "HK-AGENT-EVIDENCE-SIGNER")

    def test_the_published_key_files_match_their_published_fingerprints(self):
        identity = sp.IdentityContract(str(self.CONTRACT))
        for role, key_file in ((sp.ROLE_TASK, self.TASK_KEY), (sp.ROLE_EVIDENCE, self.EVIDENCE_KEY)):
            verifier = sp.Verifier(str(key_file), identity.expected(role)["display_name"],
                                   identity.expected(role)["encoding"],
                                   expected=identity.expected(role))
            self.assertTrue(verifier.available)
            self.assertEqual(verifier.binding, sp.BINDING_BOUND, verifier.binding_reason)
            self.assertEqual(verifier.ssh_fingerprint, identity.expected(role)["ssh_sha256"])
            self.assertEqual(verifier.fingerprint, identity.expected(role)["raw_sha256"])

    def test_the_published_key_file_hashes_match_the_contract(self):
        document = json.loads(self.CONTRACT.read_text(encoding="utf-8"))
        for entry in document["identities"]:
            path = ROOT / entry["public_key_path"]
            digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, entry["public_key_file_sha256"], entry["identity_id"])

    def test_the_published_fingerprints_match_the_archived_audit_files(self):
        command_center = (self.REPO_ROOT / "command-center/audit/20260911/KEY_FINGERPRINTS.txt"
                          ).read_text(encoding="utf-8")
        hong_kong = (self.REPO_ROOT / "hk-staging/audit/20260911/KEY_FINGERPRINTS.txt"
                     ).read_text(encoding="utf-8")
        # The Command Center signs Tasks with this key.
        self.assertIn(self.TASK_SSH, command_center)
        # The Hong Kong agent verifies Tasks with the SAME key: two-sided binding.
        self.assertIn(self.TASK_SSH, hong_kong)
        self.assertIn(self.EVIDENCE_SSH, hong_kong)
        self.assertNotIn(self.EVIDENCE_SSH, command_center.replace(
            "/etc/go-command-center/deployment-plans-v1/hk-evidence.pub", ""))

    def test_no_private_key_material_is_published(self):
        markers = (b"PRIVATE KEY", b"OPENSSH PRIVATE", b"BEGIN RSA", b"BEGIN EC", b"BEGIN DSA")
        for path in sorted(self.IDENTITY_DIR.rglob("*")):
            if not path.is_file():
                continue
            blob = path.read_bytes()
            for marker in markers:
                self.assertNotIn(marker, blob, "%s carries private key material" % path.name)
            if path.suffix == ".pub":
                self.assertLess(len(blob), 200, "%s is not a single public key line" % path.name)
        published = {p.name for p in (self.IDENTITY_DIR / "keys").iterdir() if p.is_file()}
        self.assertEqual(published,
                         {"cc-task-manifest-signing.pub", "hk-evidence-signing.pub"})

    # -- the upgrade the publication buys --------------------------------------
    def test_real_control_bus_history_reaches_proven_with_the_published_keys(self):
        _, state, _ = self.project_real(str(self.TASK_KEY), str(self.EVIDENCE_KEY))
        verification = state["verification"]
        self.assertTrue(verification["proven_allowed"])
        self.assertEqual(verification["task"]["identity_binding"], sp.BINDING_BOUND)
        self.assertEqual(verification["evidence"]["identity_binding"], sp.BINDING_BOUND)
        self.assertEqual(verification["fail_closed_reasons"], [])
        self.assertEqual(verification["identity_contract"]["state"], "LOADED")
        self.assertEqual(len(state["tasks"]), 24)
        for entry in state["tasks"]:
            self.assertIs(entry["task_signature_verified"], True, entry["task_id"])
            self.assertIs(entry["evidence"]["signature_verified"], True, entry["task_id"])
            self.assertEqual(entry["lifecycle"], "COMPLETE", entry["task_id"])
            self.assertEqual(entry["assertion"]["state"], sp.STATE_PROVEN, entry["task_id"])
        actions = {entry["action_id"] for entry in state["tasks"]}
        self.assertEqual(actions, {"CONTROL_PLANE_HEALTH", "HK_STAGING_CANARY",
                                   "HK_STAGING_DEPLOY", "HK_STAGING_ROLLBACK",
                                   "HK_STAGING_TEST_PR", "HK_STAGING_VERIFY"})
        self.assertEqual(sp.LOCAL_PATH_RE.findall(json.dumps(state)), [])

    def test_real_control_bus_history_is_capped_at_observed_without_the_keys(self):
        _, state, _ = self.project_real()
        self.assertFalse(state["verification"]["proven_allowed"])
        for entry in state["tasks"]:
            self.assertIsNone(entry["task_signature_verified"], entry["task_id"])
            self.assertIsNone(entry["evidence"]["signature_verified"], entry["task_id"])
            self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)
        self.assert_no_success_claim(state)

    # -- the four fail-closed cases --------------------------------------------
    def test_a_wrong_key_is_fail_closed_and_reaches_no_proven(self):
        _, wrong_pub = key_pair("wrong-task")
        _, state, _ = self.project_real(wrong_pub, str(self.EVIDENCE_KEY))
        verification = state["verification"]
        self.assertEqual(verification["task"]["identity_binding"], sp.BINDING_IDENTITY_MISMATCH)
        self.assertEqual(verification["evidence"]["identity_binding"], sp.BINDING_BOUND)
        self.assertFalse(verification["proven_allowed"])
        self.assertIn("task:IDENTITY_MISMATCH", verification["fail_closed_reasons"])
        self.assert_no_success_claim(state)

    def test_a_crossed_published_identity_is_fail_closed(self):
        _, state, _ = self.project_real(str(self.EVIDENCE_KEY), str(self.TASK_KEY))
        verification = state["verification"]
        self.assertEqual(verification["task"]["identity_binding"], sp.BINDING_IDENTITY_MISMATCH)
        self.assertEqual(verification["evidence"]["identity_binding"], sp.BINDING_IDENTITY_MISMATCH)
        self.assertFalse(verification["proven_allowed"])
        self.assert_no_success_claim(state)

    def test_the_published_key_for_both_roles_is_a_collision(self):
        _, state, _ = self.project_real(str(self.TASK_KEY), str(self.TASK_KEY))
        verification = state["verification"]
        self.assertFalse(verification["identities_separated"])
        self.assertFalse(verification["proven_allowed"])
        self.assertIn("roles:IDENTITY_COLLISION", verification["fail_closed_reasons"])
        self.assert_no_success_claim(state)

    def test_a_missing_key_is_never_proven(self):
        _, state, _ = self.project_real(str(self.TASK_KEY), None)
        verification = state["verification"]
        self.assertEqual(verification["evidence"]["identity_binding"], sp.BINDING_MISSING_KEY)
        self.assertEqual(verification["task"]["identity_binding"], sp.BINDING_BOUND)
        self.assertFalse(verification["proven_allowed"])
        self.assertIn("evidence:MISSING_KEY", verification["fail_closed_reasons"])
        self.assert_no_success_claim(state)

    def test_an_unreadable_key_is_fail_closed(self):
        bad = pathlib.Path(tempfile.mkdtemp(prefix="ccs-bad-")) / "bad.pub"
        bad.write_bytes(b"not a key")
        _, state, _ = self.project_real(str(bad), str(self.EVIDENCE_KEY))
        verification = state["verification"]
        self.assertEqual(verification["task"]["identity_binding"], sp.BINDING_KEY_UNREADABLE)
        self.assertFalse(verification["proven_allowed"])
        self.assert_no_success_claim(state)

    # -- contract integrity -----------------------------------------------------
    def test_a_contract_publishing_one_key_for_both_roles_is_rejected(self):
        directory = pathlib.Path(tempfile.mkdtemp(prefix="ccs-contract-"))
        path = directory / "VERIFIER_IDENTITIES_V1.json"
        path.write_text(json.dumps({
            "schema_version": "1", "contract": sp.IDENTITY_CONTRACT_NAME,
            "identities": [
                {"identity_id": "A", "role": sp.ROLE_TASK, "public_key_ssh_sha256": self.TASK_SSH},
                {"identity_id": "B", "role": sp.ROLE_EVIDENCE,
                 "public_key_ssh_sha256": self.TASK_SSH}]}), encoding="utf-8")
        identity = sp.IdentityContract(str(path))
        self.assertFalse(identity.available)
        self.assertIn("one key for both roles", identity.reason)
        self.assertIsNone(identity.expected(sp.ROLE_TASK))

    def test_an_unresolvable_contract_never_yields_proven(self):
        missing = pathlib.Path(tempfile.mkdtemp(prefix="ccs-none-")) / "absent.json"
        identity = sp.IdentityContract(str(missing))
        self.assertFalse(identity.available)
        self.assertIn("unreadable", identity.reason)
        _, state, _ = self.project_real(str(self.TASK_KEY), str(self.EVIDENCE_KEY),
                                        contract=str(missing))
        verification = state["verification"]
        self.assertEqual(verification["identity_contract"]["state"], "UNRESOLVED")
        self.assertEqual(verification["task"]["identity_binding"], sp.BINDING_IDENTITY_UNRESOLVED)
        self.assertFalse(verification["proven_allowed"])
        self.assert_no_success_claim(state)

    def test_the_contract_is_reported_without_a_workstation_path(self):
        published = sp.IdentityContract(str(self.CONTRACT))
        self.assertEqual(published.describe()["path"], sp.IDENTITY_CONTRACT_RELPATH)
        self.assertTrue(published.describe()["is_the_published_contract"])
        outside = sp.IdentityContract("D:/somewhere/else/identities.json")
        self.assertEqual(outside.describe()["path"], "<caller-supplied contract>")
        self.assertFalse(outside.describe()["is_the_published_contract"])
        self.assertFalse(outside.describe()["publishes_private_keys"])

    def test_the_derived_state_declares_the_identity_gate(self):
        _, state, _ = self.project_real(str(self.TASK_KEY), str(self.EVIDENCE_KEY))
        verification = state["verification"]
        self.assertIs(verification["proven_requires_both_keys"], True)
        self.assertIs(verification["proven_requires_both_identities_bound"], True)
        for binding in sp.FAIL_CLOSED_BINDINGS:
            self.assertNotEqual(binding, sp.BINDING_BOUND)


# --------------------------------------------------------------------------- #
class ValidationTests(unittest.TestCase):
    def test_valid_task_passes(self):
        self.assertEqual(sp.validate_task(task())["_parameter_contract"], "CURRENT")

    def test_unknown_field_rejected(self):
        with self.assertRaises(sp.Malformed):
            sp.validate_task(task(extra="x"))

    def test_wrong_authority_and_environment_rejected(self):
        for patch in ({"authority": "SOMEONE-ELSE"}, {"environment": "PRODUCTION"}):
            with self.assertRaises(sp.Malformed):
                sp.validate_task(task(**patch))

    def test_unknown_action_rejected(self):
        with self.assertRaises(sp.Malformed):
            sp.validate_task(task(action="HK_STAGING_ERASE"))

    def test_parameter_drift_is_preserved_not_dropped(self):
        legacy = task()
        legacy["parameters"] = {"release_id": "release-1"}
        self.assertEqual(sp.validate_task(legacy)["_parameter_contract"], "LEGACY_OR_UNKNOWN")

    def test_test_pr_source_must_be_the_fixed_shape(self):
        value = task(action="HK_STAGING_TEST_PR")
        value["parameters"] = {"builder_profile": "go-application-python-v1",
                               "source": {"repository": "git@github.com:yuguangzhi3836-glitch/GO.git",
                                          "pr_number": "47", "commit_sha": "c" * 40}}
        self.assertEqual(sp.validate_task(value)["_parameter_contract"], "CURRENT")
        value["parameters"]["source"]["commit_sha"] = "not-a-sha"
        with self.assertRaises(sp.Malformed):
            sp.validate_task(value)

    def test_a_task_under_the_superseded_delivery_identity_stays_readable(self):
        """The 2026-09-16 re-contract renamed the candidate delivery identity.

        History signed under the old name must stay readable and keep its Evidence.
        Holding it would silently erase real proof; accepting an unknown shape would
        be a wildcard.  The two named shapes are exact, and a third is still held.
        """
        legacy = task(action="HK_STAGING_CANARY")
        legacy["parameters"] = {"release_id": "release-1",
                                "candidate_image_id": "sha256:" + "a" * 64,
                                "candidate_repo_digest": "go-hotel@sha256:" + "a" * 64,
                                "expected_current_image_id": "sha256:" + "b" * 64}
        self.assertEqual(sp.validate_task(legacy)["_parameter_contract"], "SUPERSEDED")
        current = task(action="HK_STAGING_CANARY")
        current["parameters"] = {"release_id": "release-1",
                                 "candidate_image_id": "sha256:" + "a" * 64,
                                 "candidate_package_sha256": "c" * 64,
                                 "expected_current_image_id": "sha256:" + "b" * 64}
        self.assertEqual(sp.validate_task(current)["_parameter_contract"], "CURRENT")
        neither = task(action="HK_STAGING_CANARY")
        neither["parameters"] = {"release_id": "release-1",
                                 "candidate_image_id": "sha256:" + "a" * 64,
                                 "candidate_repo_digest": "go-hotel@sha256:" + "a" * 64,
                                 "candidate_package_sha256": "c" * 64,
                                 "expected_current_image_id": "sha256:" + "b" * 64}
        self.assertEqual(sp.validate_task(neither)["_parameter_contract"], "LEGACY_OR_UNKNOWN")

    def test_the_superseded_shapes_are_names_the_deploy_entry_no_longer_emits(self):
        for action, shapes in sp.SUPERSEDED_PARAMETERS.items():
            self.assertIn(action, sp.ACTION_PARAMETERS)
            for shape in shapes:
                self.assertNotEqual(shape, sp.ACTION_PARAMETERS[action])

    def test_evidence_generations_normalise(self):
        current = sp.normalize_evidence(evidence(task()))
        self.assertEqual(current["_generation"], "v2")
        self.assertEqual(current["_completed_at"], evidence(task())["completed_at"])
        legacy = evidence(task())
        legacy["finished_at"] = legacy.pop("completed_at")
        legacy.pop("executor_result")
        legacy["result"] = {"hostname": "iZj6ccs8t04f1p4d8pe69zZ"}
        normalised = sp.normalize_evidence(legacy)
        self.assertEqual(normalised["_generation"], "v1")
        self.assertEqual(normalised["_completed_at"], legacy["finished_at"])

    def test_evidence_without_any_terminal_timestamp_rejected(self):
        value = evidence(task())
        value.pop("completed_at")
        with self.assertRaises(sp.Malformed):
            sp.normalize_evidence(value)

    def test_request_extras_are_action_scoped(self):
        base = {"schema_version": "1", "request_id": "boss-hk-verify-1",
                "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                "requested_at": sp.iso(AT)}
        self.assertEqual(sp.validate_request(base)["action_id"], "HK_STAGING_VERIFY")
        with self.assertRaises(sp.Malformed):
            sp.validate_request(dict(base, pr_number="47"))
        with self.assertRaises(sp.Malformed):
            sp.validate_request(dict(base, plan_id="plan-1"))

    def test_deploy_request_takes_only_the_five_common_fields(self):
        # A deploy is the same shape as a verify, a canary and a rollback. The plan
        # is derived by the Command Center, so a plan_id is not a field at all: it
        # names a caller-chosen deployment, and the Bridge refuses it on the exact
        # field set rather than reading around it.
        value = {"schema_version": "1", "request_id": "boss-deploy-1",
                 "action_id": "HK_STAGING_DEPLOY", "environment": "HK-STAGING-01",
                 "requested_at": sp.iso(AT)}
        self.assertEqual(sp.validate_request(value)["action_id"], "HK_STAGING_DEPLOY")
        self.assertEqual(sp.REQUEST_EXTRA_FIELDS["HK_STAGING_DEPLOY"], set())
        with self.assertRaises(sp.Malformed):
            sp.validate_request(dict(value, plan_id="reviewed-plan-1"))
        value["image"] = "sha256:" + "a" * 64
        with self.assertRaises(sp.Malformed):
            sp.validate_request(value)


# --------------------------------------------------------------------------- #
class LifecycleTests(unittest.TestCase):
    def test_published_task_without_evidence_is_observed_not_failed(self):
        tk = task(expires_at=sp.iso(AT + dt.timedelta(minutes=5)))
        state = project(*layout(tasks=[("t.json", tk)]))
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "TASK_PUBLISHED")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_OBSERVED)
        self.assertEqual(entry["hk_agent_picked_up"]["state"], sp.STATE_UNKNOWN)

    def test_expired_task_without_evidence_is_distinct_from_success(self):
        tk = task(expires_at=sp.iso(AT - dt.timedelta(minutes=1)))
        state = project(*layout(tasks=[("t.json", tk)]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "TASK_EXPIRED")
        self.assertEqual(state["counts"]["by_lifecycle"], {"TASK_EXPIRED": 1})

    def test_unverified_evidence_reaches_published_not_complete(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_OBSERVED)

    def test_verified_evidence_reaches_complete(self):
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        tk = sign(task(), task_key, "hex")
        ev = sign(evidence(task()), evidence_key, "base64")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        task_pub=task_pub, evidence_pub=evidence_pub)
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "COMPLETE")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_non_success_status_is_execution_failed(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)],
                                evidences=[("e.json", evidence(tk, status="REJECTED"))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EXECUTION_FAILED")

    def test_evidence_after_expiry_is_timeout(self):
        tk = task()
        late = evidence(tk)
        late["completed_at"] = sp.iso(sp.parse_time(tk["expires_at"]) + dt.timedelta(minutes=1))
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", late)]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_TIMEOUT")

    def test_executor_result_mismatch_is_flagged_without_a_key(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)],
                                evidences=[("e.json", evidence(tk, executor_result="DEPLOY_OK"))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["tasks"][0]["assertion"]["value"], "EXECUTOR_RESULT_MISMATCH")

    def test_executor_result_mismatch_is_failed_with_the_evidence_key(self):
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        tk = sign(task(), task_key, "hex")
        ev = sign(evidence(task(), executor_result="DEPLOY_OK"), evidence_key, "base64")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        task_pub=task_pub, evidence_pub=evidence_pub)
        self.assertEqual(state["tasks"][0]["lifecycle"], "EXECUTION_FAILED")

    def test_nonce_reuse_is_replay_rejected(self):
        first, second = task(), task(task_id="task-two", nonce="nonce-0001")
        loaded, state, _ = build(*layout(tasks=[("a.json", first), ("b.json", second)]))
        self.assertIn("REPLAY_REJECTED", [a["kind"] for a in loaded.anomalies])
        self.assertIn("REPLAY_REJECTED", [a["kind"] for a in state["anomalies"]])

    def test_duplicate_task_id_is_reported(self):
        loaded, _, _ = build(*layout(tasks=[("a.json", task()), ("b.json", task())]))
        self.assertIn("TASK_ID_REUSED", [a["kind"] for a in loaded.anomalies])

    def test_legacy_parameter_contract_is_held_not_dropped(self):
        legacy = task()
        legacy["parameters"] = {"release_id": "release-1"}
        loaded, state, _ = build(*layout(tasks=[("legacy.json", legacy)]))
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["tasks"][0]["lifecycle"], "POLICY_HOLD")
        self.assertEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_UNKNOWN)
        self.assertIn("TASK_PARAMETER_CONTRACT_DRIFT", [a["kind"] for a in loaded.anomalies])

    def test_malformed_task_is_reported_not_silently_ignored(self):
        loaded, _, _ = build(*layout(tasks=[("bad.json", {"schema_version": "1"})]))
        self.assertEqual(loaded.tasks, [])
        self.assertIn("TASK_UNREADABLE", [a["kind"] for a in loaded.anomalies])

    def test_lifecycle_vocabulary_is_closed(self):
        for needed in ("REQUEST_CREATED", "REQUEST_VALIDATED", "REQUEST_REJECTED",
                       "TASK_SIGNED", "TASK_PUBLISHED", "HK_AGENT_PICKED_UP",
                       "EXECUTION_STARTED", "EVIDENCE_PUBLISHED", "EVIDENCE_VERIFIED", "COMPLETE",
                       "TASK_EXPIRED", "TASK_NOT_PICKED_UP", "EXECUTION_FAILED",
                       "EVIDENCE_INVALID", "EVIDENCE_TIMEOUT", "REPLAY_REJECTED", "POLICY_HOLD"):
            self.assertIn(needed, sp.LIFECYCLE_TASK | sp.LIFECYCLE_REQUEST)


# --------------------------------------------------------------------------- #
class StuckTaskClassificationTests(unittest.TestCase):
    def test_fresh_published_task_is_active_but_not_stuck(self):
        tk = task(issued_at=sp.iso(AT - dt.timedelta(minutes=2)),
                  expires_at=sp.iso(AT + dt.timedelta(minutes=13)))
        _, state, status = build(*layout(tasks=[("t.json", tk)]))
        self.assertEqual(len(state["control_state"]["active_tasks"]), 1)
        self.assertEqual(state["control_state"]["active_stuck_tasks"], [])
        self.assertEqual(status["answers"]["stuck_tasks"]["answer"]["value"], "NO")

    def test_overdue_published_task_is_active_stuck(self):
        tk = task(issued_at=sp.iso(AT - dt.timedelta(minutes=20)),
                  expires_at=sp.iso(AT + dt.timedelta(minutes=5)))
        _, state, status = build(*layout(tasks=[("t.json", tk)]))
        self.assertEqual(len(state["control_state"]["active_tasks"]), 1)
        self.assertEqual(len(state["control_state"]["active_stuck_tasks"]), 1)
        self.assertEqual(status["answers"]["stuck_tasks"]["answer"]["value"], "YES")

    def test_expired_history_never_counts_as_stuck(self):
        old = task(task_id="task-old", nonce="nonce-old",
                   issued_at="2026-08-01T00:00:00Z", expires_at="2026-08-01T00:15:00Z")
        recent = task(task_id="task-recent", nonce="nonce-recent",
                      issued_at="2026-09-13T00:00:00Z", expires_at="2026-09-13T00:15:00Z")
        _, state, status = build(*layout(tasks=[("old.json", old), ("recent.json", recent)]))
        stuck = status["answers"]["stuck_tasks"]
        self.assertEqual(stuck["answer"]["value"], "NO")
        self.assertEqual(stuck["active_stuck_tasks"], [])
        self.assertEqual([t["task_id"] for t in stuck["recent_expired_tasks"]], ["task-recent"])
        self.assertEqual([t["task_id"] for t in stuck["historical_expired_tasks"]], ["task-old"])
        self.assertEqual(stuck["default_lookup"], "active_stuck_tasks")
        self.assertEqual(len(state["control_state"]["historical_expired_tasks"]), 1)

    def test_last_failure_distinguishes_expiry_from_proven_failure(self):
        expired = task(task_id="task-expired", nonce="nonce-a",
                       issued_at="2026-08-01T00:00:00Z", expires_at="2026-08-01T00:15:00Z")
        _, _, status = build(*layout(tasks=[("x.json", expired)]))
        self.assertEqual(status["answers"]["last_failure"]["value"]["kind"],
                         "EXPIRED_WITHOUT_EVIDENCE")

    def test_last_failure_with_evidence_is_a_failed_record(self):
        tk = task()
        _, _, status = build(*layout(tasks=[("t.json", tk)],
                                     evidences=[("e.json", evidence(tk, status="REJECTED"))]))
        self.assertEqual(status["answers"]["last_failure"]["value"]["kind"], "FAILED_RECORD")


# --------------------------------------------------------------------------- #
class LivenessTests(unittest.TestCase):
    def test_no_health_evidence_is_unknown(self):
        state = project(*layout(tasks=[("t.json", task())]))
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(state["control_state"]["hk_agent_last_activity"]["state"], sp.STATE_UNKNOWN)

    def test_fresh_unverified_probe_is_observed_never_proven(self):
        tk, ev = health_pair(5)
        state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_OBSERVED)
        self.assertEqual(liveness["value"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")

    def test_fresh_verified_probe_is_proven(self):
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        tk, ev = health_pair(5)
        state = project(*layout(tasks=[("h.json", sign(tk, task_key, "hex"))],
                                evidences=[("he.json", sign(ev, evidence_key, "base64"))]),
                        task_pub=task_pub, evidence_pub=evidence_pub)
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_PROVEN)

    def test_stale_probe_is_unknown_and_reports_last_seen(self):
        tk, ev = health_pair(60 * 24 * 8)
        state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(liveness["value"])
        self.assertEqual(liveness["last_seen"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")
        self.assertGreater(liveness["age_seconds"], 1800)

    def test_stale_probe_still_reports_last_activity(self):
        tk, ev = health_pair(60 * 24 * 8)
        state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        activity = state["control_state"]["hk_agent_last_activity"]
        self.assertEqual(activity["state"], sp.STATE_OBSERVED)
        self.assertEqual(activity["value"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")

    def test_successful_verify_never_implies_agent_online(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))]))
        self.assertEqual(state["control_state"]["verify_status"]["state"], sp.STATE_OBSERVED)
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_UNKNOWN)


class LivenessWindowTests(unittest.TestCase):
    """P1: the freshness window carries transport margin over the probe interval.

    A probe issued exactly on schedule still has to travel GitHub -> Bridge ->
    Hong Kong -> Evidence -> Projection before it can be read here. A window
    equal to the interval would declare the agent stale for the whole time its
    own Evidence is in flight, which is a mis-report, not caution. The grace is
    delivery slack and nothing else: every answer below still requires
    signature-verified Evidence, and nothing infers liveness from a transport
    success.
    """

    def proven_at(self, seconds):
        """A signature-verified probe whose Evidence is exactly `seconds` old."""
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        # issued 42 minutes before AT, so a probe 2399 s old is still after issue.
        tk, ev = health_pair(41, completed_at=sp.iso(AT - dt.timedelta(seconds=seconds)))
        return build(*layout(tasks=[("h.json", sign(tk, task_key, "hex"))],
                             evidences=[("he.json", sign(ev, evidence_key, "base64"))]),
                     task_pub=task_pub, evidence_pub=evidence_pub)

    def test_the_window_is_the_interval_plus_the_transport_grace(self):
        self.assertEqual(sp.LIVENESS_PROBE_INTERVAL_SECONDS, 1800)
        self.assertEqual(sp.LIVENESS_TRANSPORT_GRACE_SECONDS, 600)
        self.assertEqual(sp.LIVENESS_FRESHNESS_WINDOW_SECONDS, 2400)
        self.assertEqual(sp.LIVENESS_FRESHNESS_WINDOW_SECONDS,
                         sp.LIVENESS_PROBE_INTERVAL_SECONDS + sp.LIVENESS_TRANSPORT_GRACE_SECONDS)
        # Neither the cadence nor the daily budget is raised to buy freshness.
        self.assertEqual(sp.LIVENESS_MAX_PROBES_PER_24H, 48)

    def test_the_window_is_reported_so_a_reader_can_see_the_margin(self):
        state = project(*layout())
        freshness = state["freshness"]
        self.assertEqual(freshness["liveness_window_seconds"], 2400)
        self.assertEqual(freshness["liveness_probe_interval_seconds"], 1800)
        self.assertEqual(freshness["liveness_transport_grace_seconds"], 600)
        self.assertEqual(freshness["liveness_max_probes_per_24h"], 48)

    def test_2399_seconds_is_still_proven(self):
        _, state, status = self.proven_at(2399)
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_PROVEN)
        self.assertEqual(liveness["value"]["age_seconds"], 2399)
        self.assertEqual(status["answers"]["hk_agent_online"]["state"], sp.STATE_PROVEN)

    def test_2401_seconds_is_not_online(self):
        _, state, status = self.proven_at(2401)
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(liveness["value"])
        self.assertEqual(liveness["age_seconds"], 2401)
        self.assertEqual(status["answers"]["hk_agent_online"]["state"], sp.STATE_UNKNOWN)
        # The margin does not lose the observation: last_seen is still reported.
        self.assertEqual(liveness["last_seen"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")
        # And activity, which is a different question, is still answered.
        self.assertEqual(state["control_state"]["hk_agent_last_activity"]["state"],
                         sp.STATE_PROVEN)

    def test_a_transport_success_alone_is_never_online(self):
        """SSH success, an HTTP 200 and a past Task success are all absent here.

        The projector has no SSH client, no HTTP client and no socket: the only
        inputs it is given are the signed Tasks, the signed Evidence and the
        Request files on the control bus. A fresh successful VERIFY, a fresh
        successful TEST_PR and a fresh runtime pointer therefore leave liveness
        exactly where it was.
        """
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        verify_task = task()
        test_pr = task(action="HK_STAGING_TEST_PR", task_id="test-pr-52",
                       parameters={"builder_profile": "go-application-python-v1",
                                   "source": {"repository": "yuguangzhi3836-glitch/GO",
                                              "pr_number": "52",
                                              # the real PR 52 head, so the fixture is a
                                              # fixture of something that exists
                                              "commit_sha": "bd25d7acca1b5f54a7fb555008ed60b76ee45f21"}})
        # Inside each task's own validity window, which opens 30 minutes before AT.
        stamp = sp.iso(AT - dt.timedelta(minutes=20))
        evidences = [("v.json", sign(evidence(verify_task, executor_result="VERIFY_OK",
                                              started_at=stamp, completed_at=stamp),
                                     evidence_key, "base64")),
                     ("p.json", sign(evidence(test_pr, executor_result="TEST_PR_OK",
                                              started_at=stamp, completed_at=stamp),
                                     evidence_key, "base64"))]
        tasks = [("v.json", sign(verify_task, task_key, "hex")),
                 ("p.json", sign(test_pr, task_key, "hex"))]
        _, state, status = build(*layout(tasks=tasks, evidences=evidences),
                                 task_pub=task_pub, evidence_pub=evidence_pub)
        # The strongest non-liveness signals available are present and fresh...
        self.assertIn(state["control_state"]["verify_status"]["state"],
                      (sp.STATE_OBSERVED, sp.STATE_PROVEN))
        self.assertIn(state["control_state"]["test_pr_status"]["state"],
                      (sp.STATE_OBSERVED, sp.STATE_PROVEN))
        # ...and liveness has not moved, because none of them is liveness Evidence.
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["hk_agent_online"]["state"], sp.STATE_UNKNOWN)

    def test_only_signed_liveness_evidence_can_answer_the_online_question(self):
        """An unverified probe is OBSERVED, never PROVEN, and never ONLINE."""
        tk, ev = health_pair(1)
        _, state, status = build(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_OBSERVED)
        self.assertNotEqual(status["answers"]["hk_agent_online"]["state"], sp.STATE_PROVEN)


# --------------------------------------------------------------------------- #
class RuntimeSeparationTests(unittest.TestCase):
    DECLARED = "sha256:" + "d" * 64
    VERIFIED = "sha256:" + "a" * 64

    def go_repo(self, with_stray_pointer=False):
        """A checkout that carries only the candidate pointer.

        `with_stray_pointer` additionally writes a file at the retired path, to prove
        the projection does not read it even if somebody recreates one.
        """
        root = pathlib.Path(tempfile.mkdtemp(prefix="ccs-go-"))
        base = root / "docs" / "canonical-baseline"
        base.mkdir(parents=True)
        (base / "CURRENT_CANDIDATE.json").write_text(
            json.dumps({"source_commit": "c" * 40, "final_release": "HOLD",
                        "production": "HOLD"}), encoding="utf-8")
        if with_stray_pointer:
            (base / "CURRENT_HK_RUNTIME.json").write_text(json.dumps({
                "schema": "go.current-hk-runtime.v1", "status": "ACTIVE",
                "environment": "HK-STAGING", "host": "i-j6ccs8t04f1p4d8pe69z",
                "runtime_generation": "DEPTH48",
                "canonical_runtime_identity": {"canonical_main_commit": "b" * 40},
                "product_source_identity": {"source_commit": "e" * 40},
                "image": {"image_tag": "go-hotel:depth48", "image_config_id": self.DECLARED},
                "release_acceptance": {"gate": "HOLD", "production": "UNTOUCHED_HOLD"},
            }), encoding="utf-8")
        return str(root)

    def verify_pair(self, image, completed_at, status="SUCCESS"):
        issued = sp.parse_time(completed_at) - dt.timedelta(minutes=5)
        tk = task(task_id="task-verify", nonce="nonce-verify",
                  issued_at=sp.iso(issued), expires_at=sp.iso(issued + dt.timedelta(minutes=10)),
                  parameters={"release_id": "release-1", "candidate_image_id": image,
                              "expected_current_image_id": image})
        ev = evidence(tk, status=status, started_at=completed_at, completed_at=completed_at)
        return tk, ev

    def test_the_repository_declares_no_runtime(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo())
        declared = state["control_state"]["repository_runtime_pointer"]
        self.assertEqual(declared["state"], sp.STATE_UNKNOWN)
        self.assertIn("no runtime pointer", declared["reason"])

    def test_a_stray_runtime_pointer_is_never_read(self):
        """Even if somebody recreates the retired file, it is not an authority here.

        This is the regression that matters: the retired pointer must not be able to
        steer anything, so a file at the old path changes nothing. The stray file below
        declares the image the VERIFY Evidence proves; if it were read, the declared and
        proven images would "agree" and the projection would say so. It does not.
        """
        tk, ev = self.verify_pair(self.DECLARED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(with_stray_pointer=True))
        control = state["control_state"]
        self.assertEqual(control["repository_runtime_pointer"]["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(control["runtime_verification"]["value"]["repository_declared_image"])
        self.assertEqual(control["runtime_verification"]["value"]["image_relation"], "UNKNOWN")

    def test_verification_rests_on_signed_evidence_not_on_a_declaration(self):
        """Fresh signed VERIFY establishes the live runtime with no pointer in the tree.

        `runtime_verification_state` used to mean "the live image equals the declared image".
        With nothing declared it now means "the live runtime is established by fresh signed
        Evidence" -- which is the only runtime fact the repository can still publish. The
        declared image stays absent, so the two questions cannot be confused.
        """
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo())
        control = state["control_state"]
        self.assertEqual(control["runtime_verification_state"], sp.RUNTIME_MATCH)
        self.assertEqual(control["runtime_verification"]["value"]["verdict"], sp.RUNTIME_MATCH)
        self.assertIsNone(control["runtime_verification"]["value"]["repository_declared_image"])
        self.assertEqual(control["live_verified_runtime"]["value"]["image_config_id"],
                         self.VERIFIED)

    def test_live_runtime_is_proven_from_signed_evidence_alone(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo())
        live = state["control_state"]["live_verified_runtime"]
        # The rank depends on whether this fixture's Evidence reaches a COMPLETE
        # terminal state; what must hold either way is that the identity comes from
        # the signed VERIFY and from nothing else.
        self.assertIn(live["state"], (sp.STATE_PROVEN, sp.STATE_OBSERVED))
        self.assertEqual(live["value"]["image_config_id"], self.VERIFIED)

    def test_not_recently_verified_when_the_proof_is_old(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-08T00:00:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(), verification_window=3600)
        self.assertEqual(state["control_state"]["runtime_verification_state"],
                         sp.RUNTIME_NOT_RECENTLY_VERIFIED)
        self.assertEqual(state["control_state"]["runtime_verification"]["value"]["verdict"],
                         sp.RUNTIME_NOT_RECENTLY_VERIFIED)

    def test_unknown_when_no_verify_evidence_exists(self):
        _, state, status = build(*layout(), go_repo=self.go_repo())
        self.assertEqual(state["control_state"]["runtime_verification"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(state["control_state"]["runtime_verification_state"], sp.RUNTIME_UNKNOWN)
        self.assertEqual(status["answers"]["repository_declared_runtime"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["live_verified_runtime"]["state"], sp.STATE_UNKNOWN)

    def test_repository_main_is_never_substituted_by_a_runtime_sha(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(with_stray_pointer=True))
        control = state["control_state"]
        self.assertEqual(control["repository_main_sha"]["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(control["repository_main_sha"]["value"])
        # The retired pointer used to hand both of these SHAs out. Now nothing may:
        # a signed live VERIFY is the only record of what a host is running.
        self.assertIsNone(control["runtime_built_from_main_sha"]["value"])
        self.assertIsNone(control["runtime_canonical_main_sha"]["value"])

    def test_repository_main_is_reported_when_supplied(self):
        state = project(*layout(), repository_main_sha="f" * 40)
        repository_main = state["control_state"]["repository_main_sha"]
        self.assertEqual(repository_main["state"], sp.STATE_OBSERVED)
        self.assertEqual(repository_main["value"], "f" * 40)

    def test_release_gate_facts_stay_informational_only(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        _, state, status = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                                 go_repo=self.go_repo(self.VERIFIED))
        informational = state["control_state"]["informational"]
        self.assertFalse(informational["contract"])
        self.assertEqual(informational["production"]["state"], sp.STATE_HOLD)
        self.assertIn("readiness_evaluation", state["control_state"]["deploy_capability"]["value"])
        # Release-gate facts must not surface as a contract answer.
        self.assertNotIn("release_gates", status["answers"])
        self.assertNotIn("can_deploy", status["answers"])


# --------------------------------------------------------------------------- #
class RequestChannelTests(unittest.TestCase):
    def request(self, action, **extra):
        value = {"schema_version": "1", "request_id": "boss-%s-1" % action.lower().replace("_", "-"),
                 "action_id": action, "environment": "HK-STAGING-01",
                 "requested_at": sp.iso(AT)}
        value.update(extra)
        return value

    def test_a_health_request_cannot_carry_any_parameter(self):
        # The platform action's request field set is the five common fields and
        # nothing else, so there is no image, service, path or command to carry.
        self.assertEqual(sp.REQUEST_EXTRA_FIELDS["CONTROL_PLANE_HEALTH"], set())
        for extra in ("image_id", "candidate_image_id", "plan_id", "pr_number",
                      "service", "path", "env", "command", "parameters"):
            payload = self.request("CONTROL_PLANE_HEALTH")
            payload[extra] = "x"
            with self.assertRaises(sp.Malformed, msg=extra):
                sp.validate_request(payload)

    def test_a_health_request_in_the_wrong_environment_is_refused(self):
        with self.assertRaises(sp.Malformed):
            sp.validate_request(self.request("CONTROL_PLANE_HEALTH", environment="PRODUCTION"))

    def test_an_unknown_action_is_still_refused(self):
        # HK_STAGING_CANARY and HK_STAGING_ROLLBACK each left this list when it became
        # a requestable action; every unknown token is still refused outright.
        for bogus in ("CONTROL_PLANE_HEALTH_V2", "HK_STAGING_ROLLBACK_V2", "HK_STAGING_CANARY_V2",
                      "canary", "HK_STAGING_CANARY "):
            with self.assertRaises(sp.Malformed, msg=bogus):
                sp.validate_request(self.request(bogus))

    def test_a_rollback_request_carries_the_five_common_fields_and_no_target(self):
        # The Request names no deployment, no image and no service: the Command
        # Center derives all three from its own side. The contract must therefore
        # refuse every field a caller could use to aim a rollback of its own
        # choosing, even though it can ask for the undo.
        payload = self.request("HK_STAGING_ROLLBACK")
        self.assertEqual(sorted(sp.validate_request(payload)), sorted(sp.REQUEST_REQUIRED))
        self.assertEqual(sp.REQUEST_EXTRA_FIELDS["HK_STAGING_ROLLBACK"], set())
        for extra in ("release_id", "source_deploy_task_id", "approval_id", "canary_evidence_id",
                      "image", "image_id", "service", "services", "compose_file", "target",
                      "path", "force_recreate", "plan_id", "pr_number", "rollback_image",
                      "expected_current_image_id", "candidate_image_id"):
            payload = self.request("HK_STAGING_ROLLBACK")
            payload[extra] = "x"
            with self.assertRaises(sp.Malformed, msg=extra):
                sp.validate_request(payload)

    def test_health_can_never_be_read_as_one_of_the_execution_actions(self):
        """A platform probe is not a degraded VERIFY / TEST_PR / DEPLOY."""
        for execution in ("HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", "HK_STAGING_DEPLOY"):
            self.assertNotEqual(sp.REQUEST_ACTION_SOURCE_CLASS["CONTROL_PLANE_HEALTH"],
                                sp.REQUEST_ACTION_SOURCE_CLASS[execution])
            self.assertNotEqual(sp.ACTION_PARAMETERS["CONTROL_PLANE_HEALTH"],
                                sp.ACTION_PARAMETERS[execution])

    def test_the_human_and_platform_classes_are_separate(self):
        self.assertEqual(list(sp.HUMAN_REQUEST_ACTIONS),
                         ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", "HK_STAGING_DEPLOY",
                          "HK_STAGING_CANARY", "HK_STAGING_ROLLBACK"])
        self.assertEqual(list(sp.PLATFORM_REQUEST_ACTIONS), ["CONTROL_PLANE_HEALTH"])
        self.assertEqual(set(sp.HUMAN_REQUEST_ACTIONS) & set(sp.PLATFORM_REQUEST_ACTIONS), set())

    def test_health_is_enabled_for_the_platform_class_and_never_for_the_human_one(self):
        self.assertNotIn("CONTROL_PLANE_HEALTH", sp.ENABLED_HUMAN_REQUEST_ACTIONS)
        self.assertIn("CONTROL_PLANE_HEALTH", sp.ENABLED_PLATFORM_REQUEST_ACTIONS)
        self.assertEqual(list(sp.ENABLED_REQUEST_ACTIONS),
                         ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", "HK_STAGING_DEPLOY",
                          "HK_STAGING_CANARY", "HK_STAGING_ROLLBACK", "CONTROL_PLANE_HEALTH"])
        # There is no deploy switch. Its absence from this set would be a claim
        # that the contract refuses the action, and a connector reads absence
        # exactly that way -- so the one direction this constant must never take
        # is the one it used to.
        self.assertIn("HK_STAGING_DEPLOY", sp.ENABLED_REQUEST_ACTIONS)

    def test_the_enabled_set_is_pinned_to_the_bridge_channel_contract(self):
        """Measured on 2026-09-17, the failure this pins was live.

        These constants said DEPLOY was not requestable for as long as the
        deployment authorisation model had been different, and CONTROL_STATUS_V1
        told the connector not to deploy -- the one action V1 exists for. Nothing
        caught it, because nothing tied the constant to the contract it describes.
        The Bridge's own shipped config is that contract, and the
        request-visibility component already pins its action registry to it.
        """
        config = json.loads((BRIDGE_COMPONENT / "config.json").read_text(encoding="utf-8"))
        allowed = config["allowed_actions"]
        self.assertEqual(sorted(sp.ENABLED_REQUEST_ACTIONS), sorted(allowed))
        self.assertEqual(sorted(list(sp.HUMAN_REQUEST_ACTIONS) + list(sp.PLATFORM_REQUEST_ACTIONS)),
                         sorted(allowed))
        self.assertEqual(set(sp.PLATFORM_REQUEST_ACTIONS),
                         set(allowed) - set(sp.HUMAN_REQUEST_ACTIONS))
        # The set the connector is told it may write for is the human half, and it
        # has to be the enabled half too -- otherwise "enabled" and "allowed to
        # write" disagree, which is precisely how the wrong answer was produced.
        self.assertEqual(set(sp.ENABLED_HUMAN_REQUEST_ACTIONS) & set(sp.HUMAN_REQUEST_ACTIONS),
                         set(sp.ENABLED_HUMAN_REQUEST_ACTIONS))

    def test_a_real_health_request_is_not_reported_as_forbidden(self):
        root, req = layout(requests=[("h.json", self.request("CONTROL_PLANE_HEALTH"))])
        state = project(root, req)
        entry = state["requests"][0]
        self.assertTrue(entry["requestable_by_current_channel"])
        self.assertEqual(entry["request_source_class"], "PLATFORM_AUTOMATION")
        self.assertFalse(entry["holding_execution_authority"])

    def test_health_is_not_promoted_into_a_human_execution_right(self):
        _, _, status = build(*layout())
        channel = status["answers"]["request_channel"]
        self.assertNotIn("CONTROL_PLANE_HEALTH", channel["human_request_actions"])
        self.assertIn("CONTROL_PLANE_HEALTH", channel["platform_request_actions"])
        self.assertEqual(channel["request_action_source_class"]["CONTROL_PLANE_HEALTH"],
                         "PLATFORM_AUTOMATION")
        properties = channel["platform_action_properties"]["CONTROL_PLANE_HEALTH"]
        self.assertEqual(properties["source_class"], "PLATFORM_AUTOMATION")
        self.assertEqual(properties["parameters"], {})
        self.assertIs(properties["read_only"], True)
        self.assertIs(properties["human_deploy_authority"], False)
        self.assertEqual(channel["capability_classification"]["CONTROL_PLANE_HEALTH"],
                         "SUPPORTED_PROVEN_PLATFORM_ONLY")
        self.assertTrue(channel["deploy_request_enabled"])

    def test_the_platform_properties_are_constants_not_read_from_a_request(self):
        for action, properties in sp.PLATFORM_ACTION_PROPERTIES.items():
            self.assertIn(action, sp.PLATFORM_REQUEST_ACTIONS)
            self.assertEqual(properties["parameters"], {})
            self.assertIs(properties["human_deploy_authority"], False)
            self.assertIs(properties["read_only"], True)

    def test_every_human_request_action_is_classified_as_human(self):
        _, _, status = build(*layout())
        source = status["answers"]["request_channel"]["request_action_source_class"]
        for action in sp.HUMAN_REQUEST_ACTIONS:
            self.assertEqual(source[action], "HUMAN_REQUEST", action)

    def test_deploy_is_a_known_capability_that_is_enabled(self):
        # The capability/enablement split this test exists for is still the point.
        # What changed is which side DEPLOY is on: the channel contract enables it
        # and there is no switch, so the report must say so, while the live-host
        # half stays UNKNOWN because this projection cannot observe it.
        _, _, status = build(*layout())
        channel = status["answers"]["request_channel"]
        self.assertIn("HK_STAGING_DEPLOY", channel["known_capabilities"])
        self.assertIn("HK_STAGING_DEPLOY", channel["enabled_request_actions"])
        self.assertIn("HK_STAGING_DEPLOY", channel["enabled_human_request_actions"])
        self.assertEqual(channel["capability_classification"]["HK_STAGING_DEPLOY"],
                         "SUPPORTED_PROVEN")
        self.assertTrue(channel["deploy_request_enabled"])
        self.assertEqual(channel["live_request_switch"]["state"], sp.STATE_UNKNOWN)

    def test_canary_and_rollback_are_requestable_without_a_separate_switch(self):
        # CANARY left "not requestable" when it became a channel action.  It stays
        # outside the deploy switch on purpose: a canary is what a deployment plan
        # must cite, so it has to be obtainable before a plan can exist at all.
        # ROLLBACK left it in the revision that connected the proven rollback chain:
        # it is the undo of a deployment, so it is gated by the same declaration that
        # gates one rather than by a switch of its own.
        _, _, status = build(*layout())
        channel = status["answers"]["request_channel"]
        classification = channel["capability_classification"]
        self.assertEqual(classification["HK_STAGING_CANARY"], "CAPABILITY_PRESENT_REQUESTABLE")
        self.assertEqual(classification["HK_STAGING_ROLLBACK"], "CAPABILITY_PRESENT_REQUESTABLE")
        self.assertIn("HK_STAGING_CANARY", channel["enabled_human_request_actions"])
        self.assertIn("HK_STAGING_ROLLBACK", channel["enabled_human_request_actions"])
        self.assertIn("HK_STAGING_CANARY", channel["known_capabilities"])
        self.assertIn("HK_STAGING_ROLLBACK", channel["human_request_actions"])
        self.assertEqual(channel["request_action_source_class"]["HK_STAGING_CANARY"], "HUMAN_REQUEST")
        self.assertEqual(channel["request_action_source_class"]["HK_STAGING_ROLLBACK"], "HUMAN_REQUEST")
        # A rollback is not read-only and must never be classified as a probe.
        self.assertNotIn("HK_STAGING_ROLLBACK", channel["platform_action_properties"])
        # The canary carries the candidate binding, and nothing else.
        self.assertEqual(sp.ACTION_PARAMETERS["HK_STAGING_CANARY"],
                         {"release_id", "candidate_image_id", "candidate_package_sha256",
                          "expected_current_image_id"})

    def test_a_canary_request_is_reported_as_requestable_and_is_not_deploy(self):
        root, req = layout(requests=[("c.json", self.request("HK_STAGING_CANARY"))])
        state = project(root, req)
        entry = state["requests"][0]
        self.assertTrue(entry["requestable_by_current_channel"])
        self.assertEqual(entry["request_source_class"], "HUMAN_REQUEST")
        self.assertEqual(entry["capability_classification"], "CAPABILITY_PRESENT_REQUESTABLE")
        self.assertFalse(entry["holding_execution_authority"])
        self.assertEqual(entry["target"], {})

    def test_verify_request_is_requestable(self):
        root, req = layout(requests=[("r.json", self.request("HK_STAGING_VERIFY"))])
        state = project(root, req)
        self.assertTrue(state["requests"][0]["requestable_by_current_channel"])

    def test_deploy_request_is_flagged_requestable(self):
        root, req = layout(requests=[("d.json", self.request("HK_STAGING_DEPLOY"))])
        state = project(root, req)
        entry = state["requests"][0]
        self.assertTrue(entry["requestable_by_current_channel"])
        self.assertEqual(entry["capability_classification"], "SUPPORTED_PROVEN")

    def test_requests_never_hold_execution_authority(self):
        root, req = layout(requests=[("r.json", self.request("HK_STAGING_VERIFY"))])
        state = project(root, req)
        self.assertFalse(state["requests"][0]["holding_execution_authority"])
        self.assertEqual(state["requests"][0]["target"], {})


# --------------------------------------------------------------------------- #
class ContractTests(unittest.TestCase):
    def build_contract(self):
        tk = task()
        tpr = task(action="HK_STAGING_TEST_PR", task_id="task-test-pr", nonce="nonce-test-pr",
                   parameters={"builder_profile": "go-application-python-v1",
                               "source": {"repository": "git@github.com:yuguangzhi3836-glitch/GO.git",
                                          "pr_number": "47", "commit_sha": "c" * 40}})
        tasks = [("t.json", tk), ("p.json", tpr)]
        evidences = [("e.json", evidence(tk)),
                     ("pe.json", evidence(tpr, executor_result="TEST_PR_OK",
                                          built_image_id="sha256:" + "e" * 64))]
        request = {"schema_version": "1", "request_id": "boss-hk-verify-1",
                   "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                   "requested_at": sp.iso(AT)}
        root, req = layout(tasks=tasks, evidences=evidences,
                           requests=[("r.json", {"ref": "refs/heads/boss-request-x",
                                                 "head_sha": "f" * 40, "request": request})])
        return build(root, req)

    REQUIRED_ANSWERS = ("hk_agent_recent_activity", "active_tasks", "last_task", "pr_tested",
                        "verify", "repository_declared_runtime", "runtime_verification",
                        "stuck_tasks", "last_failure", "request_channel")

    def test_answers_cover_every_required_question(self):
        _, _, status = self.build_contract()
        for key in self.REQUIRED_ANSWERS:
            self.assertIn(key, status["answers"])

    def test_the_required_answer_set_does_not_leak_beyond_scope(self):
        # Ten status questions plus the request channel. Anything else in answers
        # is explicitly a supporting field, never a required one. request_fate
        # (CC V1-05) is supporting: it says why a Request did not become a Task,
        # and it neither adds nor withholds an execution verdict.
        supporting = {"last_evidence", "live_verified_runtime", "go_is_healthy",
                      "hk_agent_online", "repository_main_sha", "runtime_built_from_main_sha",
                      "request_fate"}
        _, _, status = self.build_contract()
        self.assertEqual(set(status["answers"]) - set(self.REQUIRED_ANSWERS), supporting)

    def test_deploy_readiness_is_not_in_the_contract(self):
        _, _, status = self.build_contract()
        for key in ("can_deploy", "rollback_targets", "release_gates", "deployment_eligibility",
                    "deploy_ready", "rollback_ready"):
            self.assertNotIn(key, status["answers"], "%s must not be a contract answer" % key)
        self.assertEqual(status["out_of_scope"]["deploy_readiness_evaluation"], "NOT_IN_SCOPE")
        self.assertEqual(status["out_of_scope"]["rollback_readiness_evaluation"], "NOT_IN_SCOPE")

    def test_deploy_capability_is_classification_only(self):
        _, state, status = self.build_contract()
        capability = state["control_state"]["deploy_capability"]
        self.assertEqual(capability["value"]["capability"], "SUPPORTED_PROVEN")
        self.assertIs(capability["value"]["request_enabled"], True)
        self.assertEqual(capability["value"]["readiness_evaluation"], "NOT_IN_SCOPE")
        self.assertEqual(status["answers"]["request_channel"]["readiness_evaluation"],
                         "NOT_IN_SCOPE")
        self.assertTrue(status["answers"]["request_channel"]["deploy_request_enabled"])

    def test_no_deploy_readiness_value_is_computed_anywhere(self):
        _, state, status = self.build_contract()
        blob = json.dumps(state) + json.dumps(status)
        for forbidden in ("DEPLOY_READY", "deployment_eligibility", "can_deploy"):
            self.assertNotIn(forbidden, blob.replace("does not compute can_deploy", ""))

    def test_rollback_target_selection_is_not_a_contract_capability(self):
        _, state, status = self.build_contract()
        self.assertNotIn("rollback_targets", status["answers"])
        # Historical DEPLOY proof may remain as an internal fact.
        history = state["control_state"]["informational"]["rollback_candidate_history"]
        self.assertIn(history["state"], (sp.STATE_UNKNOWN, sp.STATE_OBSERVED))
        self.assertFalse(state["control_state"]["informational"]["contract"])

    def test_verify_status_query(self):
        _, _, status = self.build_contract()
        verify = status["answers"]["verify"]
        self.assertEqual(verify["state"], sp.STATE_OBSERVED)
        self.assertEqual(verify["value"]["action_id"], "HK_STAGING_VERIFY")
        self.assertEqual(verify["value"]["lifecycle"], "EVIDENCE_PUBLISHED")

    def test_test_pr_is_queryable_by_pr_number(self):
        _, _, status = self.build_contract()
        index = status["answers"]["pr_tested"]["by_pr_number"]
        self.assertEqual(sorted(index), ["47"])
        entry = index["47"][0]
        self.assertEqual(entry["commit_sha"], "c" * 40)
        self.assertEqual(entry["result"], "TEST_PR_OK")
        self.assertEqual(entry["built_image_id"], "sha256:" + "e" * 64)
        self.assertEqual(entry["state"], sp.STATE_OBSERVED)

    def test_untested_pr_is_absent_from_the_index(self):
        _, _, status = self.build_contract()
        self.assertNotIn("48", status["answers"]["pr_tested"]["by_pr_number"])

    def test_active_task_query_is_zero_when_nothing_is_pending(self):
        _, _, status = self.build_contract()
        self.assertEqual(status["answers"]["active_tasks"]["value"], 0)

    def test_authority_is_always_derived_and_non_authoritative(self):
        _, state, status = self.build_contract()
        self.assertEqual(state["authority"], "DERIVED_NON_AUTHORITATIVE")
        self.assertEqual(status["authority"], "DERIVED_NON_AUTHORITATIVE")
        self.assertIn("never authorizes", state["authority_note"])

    def test_status_contract_carries_no_execution_parameter_keys(self):
        _, _, status = self.build_contract()
        forbidden = {"compose_path", "executor_path", "env_file", "command", "shell",
                     "dockerfile", "image_override", "services", "environment_path",
                     "rollback_image", "signing_key", "private_key", "force_recreate",
                     "source_deploy_task_id", "approval_id", "canary_evidence_id"}

        def walk(node, path=""):
            if isinstance(node, dict):
                for key, value in node.items():
                    self.assertNotIn(key, forbidden, "forbidden key at %s" % (path + "/" + key))
                    walk(value, path + "/" + key)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, "%s[%d]" % (path, index))

        walk(status)

    def test_status_contract_is_bounded(self):
        _, _, status = self.build_contract()
        self.assertLess(len(json.dumps(status)), 65536)

    def test_empty_control_bus_yields_unknown_not_success(self):
        _, state, status = build(*layout())
        self.assertEqual(status["answers"]["go_is_healthy"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["hk_agent_online"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["runtime_verification"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["stuck_tasks"]["answer"]["value"], "NO")
        self.assertEqual(state["control_state"]["deploy_capability"]["value"]["capability"],
                         "SUPPORTED_PROVEN")

    def test_manifest_files_are_not_treated_as_requests(self):
        root, req = layout(requests=[("good.json",
                                      {"schema_version": "1", "request_id": "boss-hk-verify-1",
                                       "action_id": "HK_STAGING_VERIFY",
                                       "environment": "HK-STAGING-01",
                                       "requested_at": sp.iso(AT)})])
        (pathlib.Path(req) / "_MANIFEST.json").write_text('{"entries": []}', encoding="utf-8")
        loaded = sp.Loaded()
        sp.load_requests(str(req), loaded)
        self.assertEqual(len(loaded.requests), 1)
        self.assertEqual(loaded.anomalies, [])


# --------------------------------------------------------------------------- #
class PortabilityTests(unittest.TestCase):
    def test_sources_use_stable_identity_not_local_paths(self):
        state = project(*layout(tasks=[("t.json", task())]))
        sources = state["sources"]
        self.assertEqual(sources["tasks"]["repository"], sp.TASKS_REPOSITORY)
        self.assertEqual(sources["evidence"]["repository"], sp.EVIDENCE_REPOSITORY)
        self.assertEqual(sources["go"]["repository"], sp.GO_REPOSITORY)
        self.assertEqual(sources["tasks"]["head_sha"], "5b7caecd8e47751b13e4661d14b27880f19d1d71")
        # The retired runtime pointer must not appear as a source identity at all.
        self.assertEqual(sources["go"]["canonical_candidate_pointer"],
                         "docs/canonical-baseline/CURRENT_CANDIDATE.json")
        self.assertNotIn("canonical_runtime_pointer", sources["go"])

    def test_no_machine_specific_path_appears_anywhere(self):
        tk = task()
        request = {"schema_version": "1", "request_id": "boss-hk-verify-1",
                   "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                   "requested_at": sp.iso(AT)}
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))],
                           requests=[("r.json", {"request": request})])
        _, state, status = build(root, req)
        blob = json.dumps(state, sort_keys=True) + json.dumps(status, sort_keys=True)
        self.assertEqual(sp.LOCAL_PATH_RE.findall(blob), [])

    def test_rebuild_command_contains_no_local_path(self):
        state = project(*layout())
        command = state["rebuild"]["command"]
        self.assertEqual(sp.LOCAL_PATH_RE.findall(command), [])
        self.assertIn("--task-verify-key", command)
        self.assertIn("--evidence-verify-key", command)

    def test_missing_directory_anomaly_names_the_repository_not_the_disk(self):
        empty = pathlib.Path(tempfile.mkdtemp(prefix="ccs-empty-"))
        loaded = sp.Loaded()
        sp.load_tasks(str(empty), loaded)
        self.assertIn("TASKS_DIRECTORY_MISSING", [a["kind"] for a in loaded.anomalies])
        for anomaly in loaded.anomalies:
            self.assertEqual(sp.LOCAL_PATH_RE.findall(anomaly["detail"]), [])


# --------------------------------------------------------------------------- #
class DeterminismTests(unittest.TestCase):
    def test_same_instant_same_bytes(self):
        tk = task()
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))])
        self.assertEqual(sp.canonical(project(root, req)), sp.canonical(project(root, req)))

    def test_output_carries_no_wall_clock(self):
        root, req = layout(tasks=[("t.json", task())])
        self.assertEqual(project(root, req)["generated_at"], sp.iso(AT))

    def test_generated_at_is_shared_by_both_contracts(self):
        _, state, status = build(*layout())
        self.assertEqual(state["generated_at"], status["generated_at"])


# --------------------------------------------------------------------------- #
class RequestVisibilityFixture:
    """The fixtures the Request visibility suites share.

    A plain mixin, deliberately not a TestCase. Two of the suites below were
    written as subclasses of the third, which quietly re-ran every test in it --
    three times over -- and inflated the number of tests this component
    reports. Sharing fixtures is what was wanted; inheriting test methods was
    not.
    """

    def setUp(self):
        self.task_key, self.task_pub = key_pair("cc-task")
        self.evidence_key, self.evidence_pub = key_pair("hk-evidence")

    # -- helpers --------------------------------------------------------------
    def signed_task(self, request_id="request-1", **over):
        issued = AT - dt.timedelta(minutes=30)
        return sign(task(task_id=task_identity(request_id), nonce="nonce-ccv1-05",
                         issued_at=sp.iso(issued),
                         expires_at=sp.iso(issued + dt.timedelta(minutes=15)), **over),
                    self.task_key, "hex")

    def project_one(self, facts=(), index=None, requests=(("request-1.json", None),),
                    tasks=(), task_pub="auto", evidence_pub=None, facts_root=None):
        request_files = [(name, value if value is not None else request_file())
                         for name, value in requests]
        root, req_dir = layout(tasks=tasks, requests=request_files)
        return build(root, req_dir, task_pub=(self.task_pub if task_pub == "auto" else task_pub),
                     evidence_pub=evidence_pub,
                     facts_root=(facts_root if facts_root is not None
                                 else facts_root_of(facts, index)))



class RequestVisibilityTests(RequestVisibilityFixture, unittest.TestCase):
    """CC V1-05: a Request is a proposal, and only a signed Task proves acceptance.

    Before this, Command Center acceptance was a Bridge-ledger fact that never
    reached the control bus, so every Request could only be reported as CREATED
    and "why was my Request refused?" had no answer. These tests pin the three
    things that must not regress: an acceptance is never believed on a fact's
    word, a refusal never loses the Bridge's reason, and a duplicate or a replay
    is never a success.
    """

    # -- a Request file is not an acceptance ----------------------------------
    def test_a_request_file_alone_is_only_created(self):
        _, state, status = self.project_one()
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_CREATED")
        self.assertEqual(entry["lifecycle_source"], "CONTROL_BUS_ONLY")
        self.assertEqual(entry["why_not_a_task"]["state"], "NO_BRIDGE_FACT_OBSERVED")
        self.assertFalse(entry["binding"]["proof_required"])
        self.assertEqual(status["answers"]["request_fate"]["accepted"], 0)
        self.assertEqual(status["answers"]["request_fate"]["waiting"], 1)

    def test_a_created_fact_is_read_and_is_neither_an_acceptance_nor_a_refusal(self):
        """The Bridge saying "not settled" is a fact, and the weakest one there is.

        The exporter mints REQUEST_CREATED for a non-terminal Bridge record. The
        projection has to read it without turning it into either of the two things
        it is not, and without losing what it does say -- that the Bridge spoke,
        which the no-fact case cannot say.
        """
        _, state, status = self.project_one(facts=[request_fact("REQUEST_CREATED", "request-1")])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_CREATED")
        self.assertEqual(entry["lifecycle_source"], "BRIDGE_FACT")
        self.assertEqual(entry["why_not_a_task"]["state"], "NOT_SETTLED_BY_BRIDGE")
        self.assertEqual(entry["facts"][0]["first_observed_at"], "2026-09-14T11:30:00Z")
        self.assertFalse(entry["binding"]["proof_required"])
        self.assertIsNone(entry["binding"]["task_id"])
        self.assertEqual(entry["binding"]["proof_state"], "NOT_APPLICABLE")
        # Not an acceptance, and not an anomaly either: nothing was refused.
        self.assertEqual(status["answers"]["request_fate"]["accepted"], 0)
        self.assertEqual(status["answers"]["request_fate"]["refused"], 0)
        self.assertEqual([a["kind"] for a in state["anomalies"]
                          if a["kind"].startswith("REQUEST_")], [])
        # And the three answers stay apart: settled, unsettled, never spoken of.
        _, plain, _ = self.project_one()
        self.assertEqual(plain["requests"][0]["why_not_a_task"]["state"],
                         "NO_BRIDGE_FACT_OBSERVED")
        self.assertEqual(plain["requests"][0]["lifecycle_source"], "CONTROL_BUS_ONLY")

    def test_a_settled_fact_outranks_a_created_one_and_the_earlier_one_stays_visible(self):
        """The transition is not a deduplication, and the strongest answer wins.

        One Request, both facts on the bus: the Bridge was publishing at 11:00 and
        published at 11:20. The projection reports the stronger, and still carries
        the weaker, because the weaker is what says the Request was in flight
        first.
        """
        request_id = "request-1"
        tk = self.signed_task(request_id)
        created = request_fact("REQUEST_CREATED", request_id,
                               first_observed_at="2026-09-14T11:00:00Z")
        validated = request_fact("REQUEST_VALIDATED", request_id,
                                 first_observed_at="2026-09-14T11:20:00Z",
                                 binding=accepted_binding(tk, request_id))
        _, state, _ = self.project_one(tasks=[("%s.json" % tk["task_id"], tk)],
                                       facts=[created, validated])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_VALIDATED")
        self.assertEqual(entry["why_not_a_task"]["state"], "BECAME_A_TASK")
        # Both are on the bus and both are reported; neither replaced the other.
        self.assertEqual(sorted(f["kind"] for f in entry["facts"]),
                         ["REQUEST_CREATED", "REQUEST_VALIDATED"])
        self.assertEqual(state["counts"]["request_facts"], 2)
        self.assertEqual(state["counts"]["request_facts_collapsed"], 0)
        # Identity, not time, decides: the two are different facts, not one.
        self.assertNotEqual(created["semantic_id"], validated["semantic_id"])
        self.assertEqual(sp.REQUEST_FACT_RANK["REQUEST_CREATED"], 0)
        self.assertTrue(all(sp.REQUEST_FACT_RANK[k] > 0
                            for k in sp.REQUEST_FACT_KINDS if k != "REQUEST_CREATED"))

    def test_the_closed_lifecycle_set_is_exactly_the_issue_set(self):
        self.assertEqual(set(sp.REQUEST_FACT_KINDS),
                         {"REQUEST_CREATED", "REQUEST_VALIDATED", "REQUEST_REJECTED",
                          "REQUEST_DUPLICATE", "REQUEST_REPLAY_REJECTED"})
        for kind in sp.REQUEST_FACT_KINDS:
            self.assertIn(kind, sp.LIFECYCLE_REQUEST, kind)

    # -- acceptance requires proof --------------------------------------------
    def test_a_corroborated_acceptance_is_reported(self):
        request_id = "request-1"
        tk = self.signed_task(request_id)
        _, state, status = self.project_one(
            tasks=[("%s.json" % tk["task_id"], tk)],
            facts=[request_fact("REQUEST_VALIDATED", request_id,
                                binding=accepted_binding(tk, request_id))])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_VALIDATED")
        self.assertEqual(entry["lifecycle_source"], "BRIDGE_FACT")
        self.assertEqual(entry["why_not_a_task"]["state"], "BECAME_A_TASK")
        self.assertEqual(entry["binding"]["proof_state"], sp.REQUEST_FACT_PROOF)
        self.assertEqual(entry["binding"]["task_id"], tk["task_id"])
        self.assertEqual(status["answers"]["request_fate"]["accepted"], 1)

    def test_an_acceptance_without_the_published_identity_is_not_verified(self):
        """No key means no identity claim, so the acceptance cannot be believed."""
        request_id = "request-1"
        tk = self.signed_task(request_id)
        _, state, _ = self.project_one(
            tasks=[("%s.json" % tk["task_id"], tk)], task_pub=None,
            facts=[request_fact("REQUEST_VALIDATED", request_id,
                                binding=accepted_binding(tk, request_id))])
        entry = state["requests"][0]
        self.assertNotEqual(entry["lifecycle"], "REQUEST_VALIDATED")
        self.assertEqual(entry["why_not_a_task"]["state"], "ACCEPTANCE_CLAIMED_BUT_UNPROVEN")
        self.assertEqual(entry["binding"]["proof_state"], "NOT_ESTABLISHED")
        self.assertIn("REQUEST_BINDING_UNPROVEN", [a["kind"] for a in state["anomalies"]])
        # The ineffective fact is reported, never hidden.
        self.assertEqual(len(entry["facts"]), 1)
        self.assertFalse(entry["facts"][0]["effective"])

    def test_an_acceptance_whose_task_is_absent_is_not_verified(self):
        request_id = "request-1"
        tk = self.signed_task(request_id)
        _, state, _ = self.project_one(
            facts=[request_fact("REQUEST_VALIDATED", request_id,
                                binding=accepted_binding(tk, request_id))])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_CREATED")
        self.assertEqual(entry["why_not_a_task"]["state"], "ACCEPTANCE_CLAIMED_BUT_UNPROVEN")
        self.assertIn("not on the control bus", entry["binding"]["proof_detail"])

    def test_a_task_from_another_request_is_refused(self):
        """The digest link is the whole point: a Task must carry its own Request."""
        request_id = "request-1"
        tk = self.signed_task("a-different-request")
        _, state, _ = self.project_one(
            tasks=[("%s.json" % tk["task_id"], tk)],
            facts=[request_fact("REQUEST_VALIDATED", request_id,
                                binding=accepted_binding(tk, request_id))])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_CREATED")
        self.assertIn("digest of this request_id", entry["binding"]["proof_detail"])

    def test_a_mistyped_task_digest_is_refused(self):
        request_id = "request-1"
        tk = self.signed_task(request_id)
        binding = accepted_binding(tk, request_id)
        binding["task_sha256"] = "f" * 64
        _, state, _ = self.project_one(
            tasks=[("%s.json" % tk["task_id"], tk)],
            facts=[request_fact("REQUEST_VALIDATED", request_id, binding=binding)])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_CREATED")
        self.assertIn("does not describe the Task", state["requests"][0]["binding"]["proof_detail"])

    # -- a refusal never loses its reason -------------------------------------
    def test_a_refusal_keeps_the_bridge_reason_verbatim(self):
        _, state, status = self.project_one(
            facts=[request_fact("REQUEST_REJECTED", "request-1",
                                reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_REJECTED")
        self.assertEqual(entry["why_not_a_task"],
                         {"state": "REFUSED", "reason_code": "pr_head_not_found",
                          "reason_class": "UNRESOLVABLE"})
        self.assertEqual(entry["facts"][0]["reason"]["code"], "pr_head_not_found")
        visible = state["request_visibility"]["rejected_or_refused"]
        self.assertEqual([r["reason_code"] for r in visible], ["pr_head_not_found"])
        self.assertEqual(visible[0]["reason_origin"], "BRIDGE_REJECT_TOKEN")
        self.assertEqual(status["answers"]["request_fate"]["refused"], 1)

    def test_an_unclassified_reason_is_still_reported(self):
        _, state, _ = self.project_one(
            facts=[request_fact("REQUEST_REJECTED", "request-1",
                                reason=fact_reason("a_token_invented_tomorrow",
                                                   "UNCLASSIFIED_REJECT"))])
        entry = state["requests"][0]
        self.assertEqual(entry["why_not_a_task"]["reason_code"], "a_token_invented_tomorrow")
        self.assertEqual(entry["lifecycle"], "REQUEST_REJECTED")

    def test_a_ledger_derived_reason_keeps_its_origin(self):
        _, state, _ = self.project_one(
            facts=[request_fact("REQUEST_REJECTED", "request-1",
                                reason={"applicable": True, "code": "dry_run_no_task_published",
                                        "class": "NOT_ALLOWED", "origin": "BRIDGE_LEDGER_STATE",
                                        "preserved_verbatim": True})])
        visible = state["request_visibility"]["rejected_or_refused"][0]
        self.assertEqual(visible["reason_origin"], "BRIDGE_LEDGER_STATE")

    # -- a duplicate or a replay is never a success ---------------------------
    def test_a_duplicate_is_its_own_lifecycle_and_never_a_success(self):
        _, state, status = self.project_one(
            facts=[request_fact("REQUEST_DUPLICATE", "request-1",
                                reason=fact_reason("duplicate_request_id", "DUPLICATE"))])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_DUPLICATE")
        self.assertEqual(entry["why_not_a_task"]["state"], "DUPLICATE_REQUEST_ID")
        self.assertEqual(status["answers"]["request_fate"]["accepted"], 0)
        self.assertEqual(status["answers"]["request_fate"]["duplicate"], 1)
        counted = state["request_visibility"]["duplicate_or_replay"]
        self.assertEqual([c["counted_as_success"] for c in counted], [False])

    def test_a_replay_is_its_own_lifecycle_and_never_a_success(self):
        _, state, status = self.project_one(
            facts=[request_fact("REQUEST_REPLAY_REJECTED", "request-1",
                                reason=fact_reason("already_seen", "REPLAY",
                                                   origin="BRIDGE_POLL_STATUS"))])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_REPLAY_REJECTED")
        self.assertEqual(entry["why_not_a_task"]["state"], "REPLAYED_SUBMISSION")
        self.assertEqual(status["answers"]["request_fate"]["replayed"], 1)
        self.assertEqual(status["answers"]["request_fate"]["accepted"], 0)

    def test_a_duplicate_does_not_hide_an_earlier_acceptance(self):
        request_id = "request-1"
        tk = self.signed_task(request_id)
        _, state, status = self.project_one(
            tasks=[("%s.json" % tk["task_id"], tk)],
            facts=[request_fact("REQUEST_VALIDATED", request_id,
                                binding=accepted_binding(tk, request_id)),
                   request_fact("REQUEST_DUPLICATE", request_id,
                                observed_at="2026-09-14T11:45:00Z",
                                reason=fact_reason("duplicate_request_id", "DUPLICATE"))])
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "REQUEST_VALIDATED")
        self.assertEqual(len(entry["facts"]), 2)
        self.assertEqual(status["answers"]["request_fate"]["duplicate"], 0)
        self.assertEqual(len(state["request_visibility"]["duplicate_or_replay"]), 1)

    def test_an_acceptance_outranks_a_refusal_for_the_same_request(self):
        request_id = "request-1"
        tk = self.signed_task(request_id)
        _, state, _ = self.project_one(
            tasks=[("%s.json" % tk["task_id"], tk)],
            facts=[request_fact("REQUEST_REJECTED", request_id,
                                observed_at="2026-09-14T11:20:00Z",
                                reason=fact_reason("stale_or_future_request", "INVALID_REQUEST")),
                   request_fact("REQUEST_VALIDATED", request_id,
                                observed_at="2026-09-14T11:40:00Z",
                                binding=accepted_binding(tk, request_id))])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_VALIDATED")

    # -- untrusted facts fail closed ------------------------------------------
    def test_a_malformed_fact_is_refused(self):
        bad = request_fact("REQUEST_REJECTED", "request-1",
                           reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))
        bad["reason"]["class"] = "NOT_A_CLASS"
        bad["fact_id"] = "request-fact-" + sp.digest(
            {k: v for k, v in bad.items() if k not in sp.REQUEST_FACT_ID_EXCLUDED})[:32]
        _, state, _ = self.project_one(facts=[bad])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_CREATED")
        self.assertIn("REQUEST_FACT_UNREADABLE", [a["kind"] for a in state["anomalies"]])

    def test_a_tampered_fact_is_detected(self):
        good = request_fact("REQUEST_REJECTED", "request-1",
                            reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))
        good["reason"]["code"] = "a_reason_it_never_had"      # id not recomputed
        _, state, _ = self.project_one(facts=[good])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_CREATED")
        details = [a["detail"] for a in state["anomalies"] if a["kind"] == "REQUEST_FACT_UNREADABLE"]
        self.assertTrue(any("tampered" in d for d in details), details)

    def test_a_forged_semantic_identity_is_detected_even_with_a_recomputed_id(self):
        """The declared identity must be the identity of the body it declares.

        Forging semantic_id and recomputing fact_id produces a self-consistent
        document that lies about what it is a fact about. The id cannot catch
        that, so the identity is derived from the body and compared.
        """
        good = request_fact("REQUEST_REJECTED", "request-1",
                            reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))
        good["semantic_id"] = "f" * 64
        good["fact_id"] = "request-fact-" + sp.digest(
            {k: v for k, v in good.items() if k not in sp.REQUEST_FACT_ID_EXCLUDED})[:32]
        _, state, _ = self.project_one(facts=[good])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_CREATED")
        details = [a["detail"] for a in state["anomalies"] if a["kind"] == "REQUEST_FACT_UNREADABLE"]
        self.assertEqual(details, ["request_fact_semantic_id"])

    def test_the_two_time_fields_are_outside_the_id_by_design(self):
        """The boundary, stated rather than implied.

        The instant must not define identity -- that is the whole point of the
        semantic identity -- so it is not covered by the id either. What is
        covered is the semantic identity and everything a fact claims about a
        Request; the instant is a claim the projection cannot verify from an
        unsigned fact, and it does not let a fact change what it says happened.
        """
        self.assertEqual(set(sp.REQUEST_FACT_ID_EXCLUDED),
                         {"fact_id", "first_observed_at", "time_source"})
        self.assertIn("reason", sp.REQUEST_FACT_IDENTITY_KEYS)
        self.assertIn("binding", sp.REQUEST_FACT_IDENTITY_KEYS)
        self.assertNotIn("first_observed_at", sp.REQUEST_FACT_IDENTITY_KEYS)

    def test_a_fact_claiming_authority_is_refused(self):
        """A fact that says it authorizes something is not a fact."""
        for key in sp.REQUEST_FACT_AUTHORITY_KEYS:
            authority = {k: False for k in sp.REQUEST_FACT_AUTHORITY_KEYS}
            authority[key] = True
            bad = request_fact("REQUEST_VALIDATED", "request-1", authority=authority,
                               binding={"claimed": True, "task_id": task_identity("request-1"),
                                        "task_sha256": "a" * 64, "task_commit": None,
                                        "proof_required": True,
                                        "proof": sp.REQUEST_FACT_PROOF})
            _, state, _ = self.project_one(facts=[bad])
            self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_CREATED", key)
            self.assertIn("REQUEST_FACT_UNREADABLE", [a["kind"] for a in state["anomalies"]])

    def test_a_non_validated_fact_may_not_claim_a_binding(self):
        bad = request_fact("REQUEST_REJECTED", "request-1",
                           reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"),
                           binding={"claimed": True, "task_id": "x", "task_sha256": None,
                                    "task_commit": None, "proof_required": False,
                                    "proof": "NOT_APPLICABLE"})
        _, state, _ = self.project_one(facts=[bad])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_CREATED")

    def test_a_fact_without_its_request_is_unknown_not_guessed(self):
        _, state, status = self.project_one(
            requests=(),
            facts=[request_fact("REQUEST_REJECTED", "request-that-was-never-collected",
                                reason=fact_reason("request_oversized", "INVALID_REQUEST"))])
        self.assertEqual(len(state["requests"]), 1)
        entry = state["requests"][0]
        self.assertEqual(entry["lifecycle"], "UNKNOWN")
        self.assertEqual(entry["lifecycle_source"], "BRIDGE_FACT_WITHOUT_REQUEST")
        self.assertEqual(entry["why_not_a_task"]["state"], "REQUEST_NOT_ON_THE_BUS")
        self.assertIn("REQUEST_FACT_WITHOUT_REQUEST", [a["kind"] for a in state["anomalies"]])

    # -- submission-level visibility ------------------------------------------
    def test_a_submission_without_a_request_identity_is_reported(self):
        index = {"schema_version": "1", "contract": "REQUEST_FACT_INDEX",
                 "submissions": [{"submission_key": "9:" + "d" * 40, "pr_number": "9",
                                  "head_sha": "d" * 40, "bridge_status": "rejected",
                                  "reason": "malformed_json", "reason_class": "INVALID_REQUEST",
                                  "fact_emitted": False, "detail": "POLL:request_identity_unresolved"}],
                 "counts": {}}
        _, state, status = self.project_one(index=index)
        visible = state["request_visibility"]["submissions_without_a_request_identity"]
        self.assertEqual([s["reason_code"] for s in visible], ["malformed_json"])
        self.assertTrue(state["request_visibility"]["submission_index_collected"])
        self.assertEqual(status["answers"]["request_fate"]["unbound_submissions"], visible)

    def test_a_broken_index_is_refused_and_the_facts_still_count(self):
        index = {"schema_version": "1", "submissions": "not-a-list"}
        _, state, _ = self.project_one(
            index=index,
            facts=[request_fact("REQUEST_REJECTED", "request-1",
                                reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_REJECTED")
        self.assertFalse(state["request_visibility"]["submission_index_collected"])
        self.assertIn("REQUEST_FACT_INDEX_UNREADABLE", [a["kind"] for a in state["anomalies"]])

    # -- boundaries -----------------------------------------------------------
    def test_request_facts_are_never_execution_authority(self):
        request_id = "request-1"
        tk = self.signed_task(request_id)
        _, state, _ = self.project_one(
            tasks=[("%s.json" % tk["task_id"], tk)],
            facts=[request_fact("REQUEST_VALIDATED", request_id,
                                binding=accepted_binding(tk, request_id))])
        visibility = state["request_visibility"]
        self.assertTrue(visibility["acceptance_requires_a_signed_task"])
        self.assertTrue(visibility["rejection_reasons_are_published"])
        self.assertFalse(visibility["duplicate_or_replay_counted_as_success"])
        self.assertFalse(visibility["facts_are_execution_authority"])
        self.assertFalse(visibility["bridge_fact_export_installed"])
        for entry in state["requests"]:
            self.assertFalse(entry["holding_execution_authority"])
            for fact in entry["facts"]:
                self.assertFalse(fact["binding"]["proof_required"]
                                 and fact["binding"]["proof_state"] == "NOT_ESTABLISHED"
                                 and entry["lifecycle"] == "REQUEST_VALIDATED")

    def test_facts_never_change_a_task_answer(self):
        """Adding facts must not move any task-side leaf: they describe Requests."""
        request_id = "request-1"
        tk = self.signed_task(request_id)
        tasks = [("%s.json" % tk["task_id"], tk)]
        _, without, _ = self.project_one(tasks=tasks)
        _, with_facts, _ = self.project_one(
            tasks=tasks,
            facts=[request_fact("REQUEST_VALIDATED", request_id,
                                binding=accepted_binding(tk, request_id))])
        self.assertEqual(without["tasks"], with_facts["tasks"])
        self.assertEqual(without["counts"]["by_lifecycle"], with_facts["counts"]["by_lifecycle"])
        self.assertEqual(without["control_state"]["health"], with_facts["control_state"]["health"])
        self.assertEqual(without["requests"][0]["request_sha256"],
                         with_facts["requests"][0]["request_sha256"])

    def test_the_state_contract_declares_the_request_fact_rules(self):
        schema = json.loads((ROOT / "contracts" / "control_state_v1.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertIn("request_visibility", schema["required"])
        visibility = schema["properties"]["request_visibility"]
        self.assertEqual(visibility["properties"]["acceptance_requires_a_signed_task"]["const"], True)
        self.assertEqual(
            visibility["properties"]["duplicate_or_replay_counted_as_success"]["const"], False)
        self.assertEqual(visibility["properties"]["facts_are_execution_authority"]["const"], False)
        self.assertEqual(visibility["properties"]["bridge_fact_export_installed"]["const"], False)
        lifecycle = schema["properties"]["requests"]["items"]["properties"]["lifecycle"]
        self.assertEqual(set(lifecycle["enum"]), set(sp.LIFECYCLE_REQUEST))
        fate = schema["properties"]["requests"]["items"]["properties"]["why_not_a_task"]
        self.assertEqual(set(fate["properties"]["state"]["enum"]), set(sp.REQUEST_FATE_STATES))

    def test_the_status_contract_carries_the_fate_answer(self):
        schema = json.loads((ROOT / "contracts" / "control_status_v1.schema.json")
                            .read_text(encoding="utf-8"))
        fate = schema["properties"]["answers"]["properties"]["request_fate"]
        for key in ("by_request_id", "unbound_submissions", "answer"):
            self.assertIn(key, fate["required"])
        self.assertIn("carries the Bridge's own reason code",
                      " ".join(schema["x-go-notes"]))
        self.assertIn("why did my Request not become a Task", schema["x-go-question-map"])
        for forbidden in ("can_deploy", "rollback_targets", "release_gates"):
            self.assertNotIn(forbidden, schema["properties"]["answers"]["properties"])


class DeployReadinessTests(unittest.TestCase):
    """CC V1-06: the projection quotes a readiness verdict and never computes one.

    The evaluator is a separate read-only component. What these tests pin is
    that this layer carries its answer verbatim, cannot be made to claim a
    readiness it was not given, and refuses a verdict that claims authority.
    """

    def setUp(self):
        self.task_key, self.task_pub = key_pair("cc-task")
        self.evidence_key, self.evidence_pub = key_pair("hk-evidence")

    def document(self, deploy_ready="NO", gates=None, boundary=None, contract=None, **over):
        # The gate list comes from the evaluator's own declaration, never from
        # this component's constant: a fixture built from the reader's constant
        # can never disagree with the reader, which is how the P0-1 regression
        # stayed invisible.
        evaluator_gates = evaluator_gate_blocks()["MANDATORY_GATES"]
        value = {
            "schema_version": "1",
            "contract": contract or sp.DEPLOY_READINESS_CONTRACT,
            "scope": "READ_ONLY_DEPLOY_READINESS",
            "authority": "DERIVED_NON_AUTHORITATIVE",
            "generated_at": "2026-09-15T00:30:00Z",
            "as_of": "2026-09-15T00:30:00Z",
            "verdict": {"deploy_ready": deploy_ready, "reason": "synthetic",
                        "mandatory_gates": len(evaluator_gates),
                        "failed": ([g for g in evaluator_gates
                                    if g == "TEST_PR"] if deploy_ready == "NO" else []),
                        "unknown": ([g for g in evaluator_gates
                                     if g == "LIVE_DEPLOY_MODE"] if deploy_ready == "UNKNOWN" else []),
                        "advisory_failed": []},
            "gates": gates if gates is not None else [
                {"gate": name, "mandatory": True,
                 "state": ("FAIL" if (name == "TEST_PR" and deploy_ready == "NO")
                           else "UNKNOWN" if (name == "LIVE_DEPLOY_MODE" and deploy_ready == "UNKNOWN")
                           else "PASS"),
                 "reason": "synthetic %s" % name}
                for name in evaluator_gates],
            "blocking_reasons": [{"gate": "TEST_PR", "state": "FAIL", "reason": "synthetic"}]
            if deploy_ready == "NO" else [],
            "authority_boundary": dict(boundary or sp.DEPLOY_READINESS_BOUNDARY),
            "not_evaluated": {"rollback_readiness": "NOT_IN_SCOPE", "note": "synthetic"},
        }
        value.update(over)
        return value

    def write(self, document):
        folder = pathlib.Path(tempfile.mkdtemp(prefix="ccs-readiness-"))
        path = folder / sp.DEPLOY_READINESS_DOCUMENT.split("/")[-1]
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def project(self, document):
        root, req_dir = layout()
        return build(root, req_dir, task_pub=self.task_pub, evidence_pub=self.evidence_pub,
                     readiness=self.write(document))

    def test_without_a_verdict_the_projection_states_nothing(self):
        root, req_dir = layout()
        _, state, _ = build(root, req_dir, task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        readiness = state["control_state"]["deploy_readiness"]
        self.assertEqual(readiness["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(readiness["value"])
        self.assertIn("no deploy readiness verdict was supplied", readiness["reason"])
        self.assertEqual(state["control_state"]["deploy_readiness_gates"], [])
        self.assertEqual(state["control_state"]["out_of_scope"]["deploy_readiness_evaluation"],
                         "NOT_IN_SCOPE")
        self.assertIsNone(state["control_state"]["out_of_scope"]["deploy_readiness_document"])

    def test_a_no_verdict_is_carried_verbatim(self):
        _, state, _ = self.project(self.document("NO"))
        readiness = state["control_state"]["deploy_readiness"]
        self.assertEqual(readiness["state"], sp.STATE_OBSERVED)
        self.assertEqual(readiness["value"], "NO")
        self.assertIn("TEST_PR", readiness["reason"])
        self.assertEqual(state["control_state"]["out_of_scope"]["deploy_readiness_evaluation"],
                         "EVALUATED_READ_ONLY")
        self.assertEqual(state["control_state"]["out_of_scope"]["deploy_readiness_document"],
                         sp.DEPLOY_READINESS_DOCUMENT)
        self.assertEqual([g["gate"] for g in state["control_state"]["deploy_readiness_gates"]],
                         list(sp.DEPLOY_READINESS_GATES))

    def test_a_yes_verdict_is_carried_and_is_not_an_approval(self):
        _, state, _ = self.project(self.document("YES"))
        readiness = state["control_state"]["deploy_readiness"]
        self.assertEqual(readiness["value"], "YES")
        self.assertIn("authorises nothing", readiness["reason"])

    def test_an_unknown_verdict_is_unknown_and_never_yes(self):
        _, state, _ = self.project(self.document("UNKNOWN"))
        readiness = state["control_state"]["deploy_readiness"]
        self.assertEqual(readiness["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(readiness["value"])
        self.assertIn("LIVE_DEPLOY_MODE", readiness["reason"])
        # The per-gate detail is still there: nothing is lost by the null value.
        self.assertEqual(len(state["control_state"]["deploy_readiness_gates"]),
                         len(sp.DEPLOY_READINESS_GATES))

    def test_a_verdict_that_claims_authority_is_refused(self):
        for key in sp.DEPLOY_READINESS_BOUNDARY:
            if sp.DEPLOY_READINESS_BOUNDARY[key] is False:
                boundary = dict(sp.DEPLOY_READINESS_BOUNDARY)
                boundary[key] = True
                _, state, _ = self.project(self.document("YES", boundary=boundary))
                self.assertEqual(state["control_state"]["deploy_readiness"]["state"],
                                 sp.STATE_UNKNOWN, key)
                self.assertIn("DEPLOY_READINESS_UNREADABLE",
                              [a["kind"] for a in state["anomalies"]], key)

    def test_a_document_of_another_contract_is_refused(self):
        _, state, _ = self.project(self.document("YES", contract="SOMETHING_ELSE"))
        self.assertEqual(state["control_state"]["deploy_readiness"]["state"], sp.STATE_UNKNOWN)
        self.assertIn("DEPLOY_READINESS_UNREADABLE", [a["kind"] for a in state["anomalies"]])

    def test_a_verdict_outside_the_closed_set_is_refused(self):
        _, state, _ = self.project(self.document("PROBABLY"))
        self.assertEqual(state["control_state"]["deploy_readiness"]["state"], sp.STATE_UNKNOWN)
        self.assertIn("DEPLOY_READINESS_UNREADABLE", [a["kind"] for a in state["anomalies"]])

    def test_an_incomplete_gate_set_is_refused(self):
        gates = [g for g in self.document()["gates"] if g["gate"] != "TEST_PR"]
        _, state, _ = self.project(self.document("NO", gates=gates))
        self.assertEqual(state["control_state"]["deploy_readiness"]["state"], sp.STATE_UNKNOWN)
        self.assertIn("DEPLOY_READINESS_UNREADABLE", [a["kind"] for a in state["anomalies"]])

    def test_a_gate_outside_the_closed_set_is_refused(self):
        gates = self.document()["gates"]
        gates[-1]["gate"] = "SOMETHING_ELSE"
        _, state, _ = self.project(self.document("NO", gates=gates))
        self.assertEqual(state["control_state"]["deploy_readiness"]["state"], sp.STATE_UNKNOWN)

    def test_a_verdict_never_moves_a_task_side_answer(self):
        root, req_dir = layout()
        _, without, _ = build(root, req_dir, task_pub=self.task_pub,
                              evidence_pub=self.evidence_pub)
        _, with_verdict, _ = build(root, req_dir, task_pub=self.task_pub,
                                   evidence_pub=self.evidence_pub,
                                   readiness=self.write(self.document("YES")))
        self.assertEqual(without["tasks"], with_verdict["tasks"])
        self.assertEqual(without["control_state"]["health"],
                         with_verdict["control_state"]["health"])
        self.assertEqual(without["requests"], with_verdict["requests"])

    def test_rollback_readiness_stays_out_of_scope(self):
        _, state, _ = self.project(self.document("YES"))
        self.assertEqual(
            state["control_state"]["out_of_scope"]["rollback_readiness_evaluation"],
            "NOT_IN_SCOPE")

    def test_the_projection_contract_declares_the_verdict_rules(self):
        schema = json.loads((ROOT / "contracts" / "control_state_v1.schema.json")
                            .read_text(encoding="utf-8"))
        control = schema["properties"]["control_state"]
        for key in ("deploy_readiness", "deploy_readiness_gates"):
            self.assertIn(key, control["required"], key)
        gates = control["properties"]["deploy_readiness_gates"]["items"]["properties"]["gate"]
        self.assertEqual(set(gates["enum"]), set(sp.DEPLOY_READINESS_GATES))
        out_of_scope = control["properties"]["out_of_scope"]["properties"]
        self.assertEqual(set(out_of_scope["deploy_readiness_evaluation"]["enum"]),
                         {"NOT_IN_SCOPE", "EVALUATED_READ_ONLY"})
        self.assertEqual(out_of_scope["rollback_readiness_evaluation"]["const"], "NOT_IN_SCOPE")

    def test_the_status_contract_still_carries_no_readiness_key(self):
        schema = json.loads((ROOT / "contracts" / "control_status_v1.schema.json")
                            .read_text(encoding="utf-8"))
        for forbidden in ("deploy_readiness", "can_deploy", "deployment_eligibility",
                          "release_gates", "rollback_targets"):
            self.assertNotIn(forbidden, schema["properties"]["answers"]["properties"], forbidden)
        note = schema["properties"]["out_of_scope"]["properties"]["note"]
        self.assertTrue(note)


class FailureEvidenceTests(unittest.TestCase):
    """CC V1-02.  A signed failure record is a real answer, and never a permission.

    Before this the failure half of the lifecycle lived only in the agent-local
    ledger, so the control bus could not distinguish "never picked up" from
    "picked up and failed".
    """

    def setUp(self):
        self.task_key, self.task_pub = key_pair("cc-task")
        self.evidence_key, self.evidence_pub = key_pair("hk-evidence")

    def signed_task(self, **over):
        """The fixture Task as it really arrives: signed by the task identity."""
        return sign(task(**over), self.task_key, "hex")

    def failure(self, tk, **over):
        value = evidence(tk, status="FAILED", executor_result="EXECUTION_FAILED",
                         failure={"schema_version": "1", "kind": "RESULT_REJECT",
                                  "stage": "parser", "reason_code": "EXECUTOR_OUTPUT_REJECTED",
                                  "attempt_number": 1, "attempt_budget_exhausted": True,
                                  "execution_attempted": True, "return_code": 1,
                                  "diagnostic": {"stdout": {"length": 0, "sha256": "0" * 64,
                                                            "preview": ""},
                                                 "stderr": {"length": 0, "sha256": "0" * 64,
                                                            "preview": ""}}},
                         retry_permitted=False, replay_authorized=False,
                         authorizes_any_action=False)
        value.update(over)
        return value

    def build_one(self, evidence_value, tk=None):
        tk = tk or task()
        return build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence_value)]),
                     task_pub=self.task_pub, evidence_pub=self.evidence_pub)

    # -- the failure answer ----------------------------------------------------
    def test_a_signed_failure_record_reaches_execution_failed(self):
        tk = self.signed_task()
        loaded, state, status = self.build_one(sign(self.failure(tk), self.evidence_key, "base64"), tk)
        entry = state["tasks"][0]
        self.assertTrue(entry["task_signature_verified"])
        self.assertTrue(entry["evidence"]["signature_verified"])
        self.assertEqual(entry["lifecycle"], "EXECUTION_FAILED")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_FAILED)
        self.assertEqual(entry["assertion"]["value"], "FAILED")
        self.assertIn("RESULT_REJECT", entry["assertion"]["reason"])
        self.assertEqual(entry["failure"]["kind"], "RESULT_REJECT")
        self.assertEqual(entry["failure"]["reason_code"], "EXECUTOR_OUTPUT_REJECTED")
        self.assertEqual(entry["failure"]["stage"], "parser")
        self.assertNotIn("EVIDENCE_CONFLICT", [a["kind"] for a in loaded.anomalies])

    def test_the_last_failure_names_the_task_and_why_it_failed(self):
        tk = self.signed_task()
        _, state, status = self.build_one(sign(self.failure(tk), self.evidence_key, "base64"), tk)
        answer = status["answers"]["last_failure"]
        self.assertEqual(answer["state"], sp.STATE_OBSERVED)
        self.assertEqual(answer["value"]["task_id"], tk["task_id"])
        self.assertEqual(answer["value"]["action_id"], tk["action_id"])
        self.assertEqual(answer["value"]["kind"], "FAILED_RECORD")
        self.assertEqual(answer["value"]["failure"]["reason_code"], "EXECUTOR_OUTPUT_REJECTED")
        # the answer points at both the Task and the failure record it came from
        self.assertIn("tasks/t.json", answer["evidence"])
        self.assertIn("evidence/e.json", answer["evidence"])

    def test_a_failure_outside_the_validity_window_is_still_execution_failed(self):
        # A failure is recorded when the attempt stopped, which may legitimately
        # be after expires_at.  Only a claimed success can time out.
        tk = self.signed_task()
        late = self.failure(tk, completed_at=sp.iso(sp.parse_time(tk["expires_at"])
                                                    + dt.timedelta(minutes=5)))
        _, state, _ = self.build_one(sign(late, self.evidence_key, "base64"), tk)
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "EXECUTION_FAILED")
        self.assertEqual(entry["failure"]["kind"], "RESULT_REJECT")

    def test_a_claimed_success_outside_the_window_still_times_out(self):
        tk = self.signed_task()
        late = evidence(tk, completed_at=sp.iso(sp.parse_time(tk["expires_at"])
                                                + dt.timedelta(minutes=5)))
        _, state, _ = self.build_one(sign(late, self.evidence_key, "base64"), tk)
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_TIMEOUT")

    # -- fail-closed cases -----------------------------------------------------
    def test_a_failure_record_signed_by_the_wrong_identity_is_invalid(self):
        tk = self.signed_task()
        crossed = sign(self.failure(tk), self.task_key, "base64")
        _, state, _ = self.build_one(crossed, tk)
        entry = state["tasks"][0]
        self.assertFalse(entry["evidence"]["signature_verified"])
        self.assertEqual(entry["lifecycle"], "EVIDENCE_INVALID")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_FAILED)
        self.assertNotIn("failure", entry)

    def test_a_failure_record_claiming_an_authorization_is_given_no_effect(self):
        tk = self.signed_task()
        claiming = self.failure(tk, retry_permitted=True, replay_authorized=True,
                                authorizes_any_action=True)
        loaded, state, _ = self.build_one(sign(claiming, self.evidence_key, "base64"), tk)
        self.assertIn("FAILURE_EVIDENCE_AUTHORIZATION_CLAIM",
                      [a["kind"] for a in loaded.anomalies])
        detail = state["tasks"][0]["failure"]
        # the contract answers, not the artifact
        self.assertIs(detail["retry_permitted"], False)
        self.assertIs(detail["replay_authorized"], False)
        self.assertIs(detail["authorizes_any_action"], False)
        self.assertIs(detail["artifact_claimed_retry_permitted"], True)
        self.assertEqual(state["tasks"][0]["lifecycle"], "EXECUTION_FAILED")

    def test_two_distinct_records_for_one_task_identity_fail_closed(self):
        tk = self.signed_task()
        good = sign(evidence(tk), self.evidence_key, "base64")
        bad = sign(self.failure(tk), self.evidence_key, "base64")
        loaded, state, _ = build(*layout(tasks=[("t.json", tk)],
                                         evidences=[("a.json", good), ("b.json", bad)]),
                                 task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        self.assertIn("EVIDENCE_CONFLICT", [a["kind"] for a in loaded.anomalies])
        entry = state["tasks"][0]
        self.assertTrue(entry["evidence_conflict"])
        self.assertEqual(entry["assertion"]["state"], sp.STATE_OBSERVED)
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)
        self.assertNotEqual(entry["lifecycle"], "COMPLETE")

    def test_a_duplicate_byte_identical_record_is_not_a_conflict(self):
        tk = self.signed_task()
        good = sign(evidence(tk), self.evidence_key, "base64")
        loaded, state, _ = build(*layout(tasks=[("t.json", tk)],
                                         evidences=[("a.json", good), ("b.json", dict(good))]),
                                 task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        self.assertNotIn("EVIDENCE_CONFLICT", [a["kind"] for a in loaded.anomalies])
        self.assertEqual(state["tasks"][0]["lifecycle"], "COMPLETE")

    def test_a_malformed_failure_record_is_reported_not_interpreted(self):
        tk = self.signed_task()
        broken = sign(self.failure(tk), self.evidence_key, "base64")
        del broken["action_id"]
        loaded, state, _ = self.build_one(broken, tk)
        self.assertIn("EVIDENCE_UNREADABLE", [a["kind"] for a in loaded.anomalies])
        entry = state["tasks"][0]
        self.assertIsNone(entry.get("failure"))
        self.assertIsNone(entry.get("evidence"))
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_FAILED)

    def test_an_unbound_failure_record_is_reported_not_interpreted(self):
        # The record must name the Task it answers; a record without a binding is
        # not merged onto some Task by guesswork.
        tk = self.signed_task()
        broken = sign(self.failure(tk, task_id="someone-else"), self.evidence_key, "base64")
        loaded, state, _ = self.build_one(broken, tk)
        self.assertIsNone(state["tasks"][0].get("evidence"))

    # -- the success path is untouched -----------------------------------------
    def test_the_success_path_carries_no_failure_block(self):
        tk = self.signed_task()
        _, state, _ = self.build_one(sign(evidence(tk), self.evidence_key, "base64"), tk)
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "COMPLETE")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_PROVEN)
        self.assertNotIn("failure", entry)

    # -- the contract itself ---------------------------------------------------
    def test_the_failure_contract_is_closed(self):
        schema = json.loads((ROOT / "contracts" / "failure_evidence_v1.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["status"]["const"], "FAILED")
        self.assertEqual(schema["properties"]["executor_result"]["const"], "EXECUTION_FAILED")
        for key in ("retry_permitted", "replay_authorized", "authorizes_any_action"):
            self.assertEqual(schema["properties"][key]["const"], False, key)
        block = schema["properties"]["failure"]
        for key in ("task_id", "nonce", "action_id", "environment"):
            self.assertIn(key, schema["required"])
        self.assertIn("UNCLASSIFIED_REJECT",
                      block["properties"]["reason_code"]["enum"])
        self.assertIn("AGENT_REJECT", block["properties"]["kind"]["enum"])
        self.assertIn("attempt_budget_exhausted", block["required"])


# --------------------------------------------------------------------------- #
# P0-1: the projector's gate set is the evaluator's gate set, and the real
# evaluator's document is consumed by the real projector.
#
# Both halves used to be pinned only against documents built from this
# component's own constants. That is a check that cannot fail: it compares a
# constant with a fixture derived from it. When the evaluator made every gate
# mandatory and added DEPLOYMENT_AUTHORIZATION and BRIDGE_ACCEPTANCE, the
# projector silently went on refusing the real document, and no test here
# noticed. The tests below take their gate list from the evaluator's source and
# their document from the evaluator's own run.
# --------------------------------------------------------------------------- #
class DeployReadinessContractTests(unittest.TestCase):
    """The evaluator decides what a gate is; this side may only carry the verdict."""

    def test_the_projector_carries_exactly_the_evaluators_mandatory_gates(self):
        self.assertEqual(tuple(sp.DEPLOY_READINESS_GATES),
                         evaluator_gate_blocks()["MANDATORY_GATES"])

    def test_the_projector_has_no_advisory_gate_that_the_evaluator_dropped(self):
        self.assertEqual(tuple(sp.DEPLOY_READINESS_ADVISORY_GATES),
                         evaluator_gate_blocks()["ADVISORY_GATES"])

    def test_the_evaluator_has_no_advisory_gate_left(self):
        self.assertEqual(evaluator_gate_blocks()["ADVISORY_GATES"], ())

    def test_canary_is_mandatory_on_both_sides_and_release_gates_is_gone(self):
        evaluator = evaluator_gate_blocks()["MANDATORY_GATES"]
        self.assertIn("CANARY", evaluator)
        self.assertIn("CANARY", sp.DEPLOY_READINESS_MANDATORY)
        self.assertNotIn("CANARY", sp.DEPLOY_READINESS_ADVISORY_GATES)
        # The four product-release declarations were removed from the deploy contract, so
        # neither side may carry RELEASE_GATES: not as mandatory, and not as advisory.
        self.assertNotIn("RELEASE_GATES", evaluator)
        self.assertNotIn("RELEASE_GATES", sp.DEPLOY_READINESS_MANDATORY)
        self.assertNotIn("RELEASE_GATES", sp.DEPLOY_READINESS_ADVISORY_GATES)

    def test_every_gate_the_projector_knows_is_mandatory(self):
        self.assertEqual(set(sp.DEPLOY_READINESS_MANDATORY), set(sp.DEPLOY_READINESS_GATES))
        self.assertEqual(len(sp.DEPLOY_READINESS_GATES), 12)


class DeployReadinessIntegrationTests(unittest.TestCase):
    """The real evaluator's DEPLOY_READINESS.json, read by the real projector.

    No copy of the document is written here: the evaluator builds it from its own
    authoritative inputs and this side only reads it. That is what makes the two
    components pinned against each other instead of each against itself.
    """

    def produced(self, **fixture_flags):
        """Run the real evaluator and place its document where the projector looks."""
        fixture = real_readiness_fixture().Fixture(**fixture_flags)
        document = fixture.evaluate()
        path = fixture.go / sp.DEPLOY_READINESS_DOCUMENT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        return document, path

    def load(self, path):
        loaded = sp.Loaded()
        sp.load_deploy_readiness(str(path), loaded)
        return loaded

    def test_a_gate_removed_from_the_document_is_refused_not_partially_quoted(self):
        """This is what makes the drift guard bite rather than merely compare.

        The reader requires the whole gate set, so a gate the evaluator adds and
        the projector lacks does not degrade into a partial quotation -- the
        document is refused outright. Together with the guard above, a gate added
        on one side only fails CI here instead of silently mis-reading live state.
        """
        document, path = self.produced()
        document["gates"] = [entry for entry in document["gates"]
                             if entry["gate"] != "BRIDGE_ACCEPTANCE"]
        path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        loaded = self.load(path)
        self.assertIsNone(loaded.deploy_readiness)
        self.assertEqual([a["kind"] for a in loaded.anomalies],
                         ["DEPLOY_READINESS_UNREADABLE"])

    def test_the_real_document_is_read_without_a_single_anomaly(self):
        _, path = self.produced()
        loaded = self.load(path)
        self.assertEqual([a["kind"] for a in loaded.anomalies], [])
        self.assertIsNotNone(loaded.deploy_readiness)

    def test_the_real_gate_set_survives_the_contract_unchanged(self):
        document, path = self.produced()
        loaded = self.load(path)
        carried = [entry["gate"] for entry in loaded.deploy_readiness["gates"]]
        self.assertEqual(carried, [entry["gate"] for entry in document["gates"]])
        self.assertEqual(carried, list(sp.DEPLOY_READINESS_GATES))
        self.assertEqual(len(carried), document["verdict"]["mandatory_gates"])
        # Twelve gates: RELEASE_GATES was removed from the deploy contract on
        # 2026-09-17, so the evaluator reports twelve and this projection carries twelve.
        self.assertEqual(len(carried), 12)

    def test_every_gate_of_the_real_document_is_mandatory_here_too(self):
        _, path = self.produced()
        loaded = self.load(path)
        self.assertTrue(loaded.deploy_readiness["gates"])
        for entry in loaded.deploy_readiness["gates"]:
            self.assertTrue(entry["mandatory"], entry["gate"])
            self.assertIn(entry["gate"], sp.DEPLOY_READINESS_MANDATORY)

    def test_a_real_yes_verdict_is_carried_verbatim_and_is_not_an_approval(self):
        document, path = self.produced()
        self.assertEqual(document["verdict"]["deploy_ready"], "YES")
        loaded = self.load(path)
        self.assertEqual(loaded.deploy_readiness["deploy_ready"], "YES")
        root, req_dir = layout()
        state = project(root, req_dir, readiness=path)
        readiness = state["control_state"]["deploy_readiness"]
        self.assertEqual(readiness["state"], sp.STATE_OBSERVED)
        self.assertEqual(readiness["value"], "YES")
        self.assertIn("authorises nothing", readiness["reason"])
        self.assertEqual(state["control_state"]["out_of_scope"]["deploy_readiness_evaluation"],
                         "EVALUATED_READ_ONLY")

    def test_a_real_no_verdict_is_carried_verbatim(self):
        document, path = self.produced(channel_value="suspended")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")
        loaded = self.load(path)
        self.assertEqual(loaded.deploy_readiness["deploy_ready"], "NO")
        root, req_dir = layout()
        state = project(root, req_dir, readiness=path)
        self.assertEqual(state["control_state"]["deploy_readiness"]["value"], "NO")
        self.assertIn("LIVE_DEPLOY_MODE", state["control_state"]["deploy_readiness"]["reason"])

    def test_a_real_unknown_verdict_is_unknown_and_never_yes(self):
        document, path = self.produced(bundle=False)
        self.assertEqual(document["verdict"]["deploy_ready"], "UNKNOWN")
        loaded = self.load(path)
        self.assertEqual(loaded.deploy_readiness["deploy_ready"], "UNKNOWN")
        root, req_dir = layout()
        state = project(root, req_dir, readiness=path)
        self.assertEqual(state["control_state"]["deploy_readiness"]["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(state["control_state"]["deploy_readiness"]["value"])
        # The per-gate detail is not lost when the verdict is unknown.
        self.assertEqual(len(state["control_state"]["deploy_readiness_gates"]), 12)

    def test_the_full_projection_reports_the_real_gates_and_the_real_verdict(self):
        document, path = self.produced()
        root, req_dir = layout()
        state = project(root, req_dir, readiness=path)
        self.assertEqual([a["kind"] for a in state["anomalies"]
                          if a["kind"] == "DEPLOY_READINESS_UNREADABLE"], [])
        gates = state["control_state"]["deploy_readiness_gates"]
        self.assertEqual([entry["gate"] for entry in gates],
                         [entry["gate"] for entry in document["gates"]])
        self.assertTrue(all(entry["mandatory"] for entry in gates))
        self.assertEqual(state["control_state"]["deploy_readiness"]["value"],
                         document["verdict"]["deploy_ready"])


# --------------------------------------------------------------------------- #
# Semantic identity on the reading side
#
# The exporter now mints one immutable fact per semantic identity, at the earliest
# instant it was observed. The bus, however, still carries every fact the earlier
# exporter wrote -- one per observation -- so the same outcome can be present in
# both shapes at once. They are one business fact, and the projection has to say
# so rather than count the same outcome twice.
# --------------------------------------------------------------------------- #
class RequestFactSemanticDedupTests(RequestVisibilityFixture, unittest.TestCase):
    """Reading both shapes, and folding them into one fact per identity."""

    def test_a_legacy_fact_is_still_read(self):
        _, state, _ = self.project_one(
            facts=[request_fact("REQUEST_REJECTED", "request-1", legacy=True,
                                reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))])
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_REJECTED")
        entry = state["requests"][0]["facts"][0]
        self.assertEqual(entry["identity_rule"], "LEGACY_TIMESTAMP")
        self.assertEqual(entry["first_observed_at"], "2026-09-14T11:30:00Z")
        self.assertNotIn("REQUEST_FACT_UNREADABLE", [a["kind"] for a in state["anomalies"]])

    def test_a_current_fact_reports_its_rule_and_its_instant(self):
        _, state, status = self.project_one(
            facts=[request_fact("REQUEST_REJECTED", "request-1",
                                reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))])
        entry = state["requests"][0]["facts"][0]
        self.assertEqual(entry["identity_rule"], "SEMANTIC")
        self.assertEqual(entry["observations_on_bus"], 1)
        self.assertEqual(entry["first_observed_at"], "2026-09-14T11:30:00Z")
        self.assertEqual(status["answers"]["request_fate"]["by_request_id"]["request-1"]
                         ["lifecycle"], "REQUEST_REJECTED")

    def test_the_same_outcome_in_both_shapes_is_one_fact(self):
        """One outcome, five observations of it, one business fact."""
        facts = [request_fact("REQUEST_VALIDATED", "request-1", legacy=True,
                              observed_at="2026-09-14T11:30:00Z",
                              binding=accepted_binding(self.signed_task("request-1"), "request-1")),
                 request_fact("REQUEST_VALIDATED", "request-1", legacy=True,
                              observed_at="2026-09-14T11:35:00Z",
                              binding=accepted_binding(self.signed_task("request-1"), "request-1")),
                 request_fact("REQUEST_VALIDATED", "request-1",
                              first_observed_at="2026-09-14T11:30:00Z",
                              binding=accepted_binding(self.signed_task("request-1"), "request-1"))]
        tk = self.signed_task("request-1")
        _, state, status = self.project_one(tasks=[("%s.json" % tk["task_id"], tk)], facts=facts)
        visibility = state["request_visibility"]
        self.assertEqual(visibility["facts_collected"], 1)
        self.assertEqual(visibility["fact_observations_folded_into_a_semantic_fact"], 2)
        self.assertEqual(state["counts"]["request_facts"], 1)
        self.assertEqual(state["counts"]["request_fact_observations"], 3)
        self.assertEqual(state["counts"]["request_facts_collapsed"], 2)
        entry = state["requests"][0]["facts"][0]
        self.assertEqual(entry["observations_on_bus"], 3)
        self.assertEqual(len(entry["collapsed_fact_ids"]), 2)
        # And the answer is unchanged by the duplicates.
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_VALIDATED")

    def test_the_earliest_observation_of_an_identity_is_the_one_kept(self):
        early = request_fact("REQUEST_REJECTED", "request-1", legacy=True,
                             observed_at="2026-09-14T11:00:00Z",
                             reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))
        late = request_fact("REQUEST_REJECTED", "request-1",
                            first_observed_at="2026-09-14T11:30:00Z",
                            reason=fact_reason("pr_head_not_found", "UNRESOLVABLE"))
        _, state, _ = self.project_one(facts=[late, early])
        entry = state["requests"][0]["facts"][0]
        self.assertEqual(entry["first_observed_at"], "2026-09-14T11:00:00Z")
        self.assertEqual(entry["fact_id"], early["fact_id"])
        self.assertEqual(entry["identity_rules"], ["LEGACY_TIMESTAMP", "SEMANTIC"])

    def test_a_different_reason_is_a_different_fact_not_a_duplicate(self):
        _, state, _ = self.project_one(
            facts=[request_fact("REQUEST_REJECTED", "request-1",
                                reason=fact_reason("pr_head_not_found", "UNRESOLVABLE")),
                   request_fact("REQUEST_REJECTED", "request-1",
                                first_observed_at="2026-09-14T11:45:00Z",
                                reason=fact_reason("request_oversized", "INVALID_REQUEST"))])
        self.assertEqual(state["counts"]["request_facts"], 2)
        self.assertEqual(state["counts"]["request_facts_collapsed"], 0)
        self.assertEqual(len(state["requests"][0]["facts"]), 2)

    def test_dedup_never_hides_a_claim_that_could_not_be_proven(self):
        """Folding observations must not turn an unproven claim into an acceptance."""
        _, state, status = self.project_one(
            facts=[request_fact("REQUEST_VALIDATED", "request-1", legacy=True,
                                binding={"claimed": True, "task_id": "a-task-that-is-not-on-the-bus",
                                         "task_sha256": "a" * 64, "task_commit": None,
                                         "proof_required": True, "proof": sp.REQUEST_FACT_PROOF}),
                   request_fact("REQUEST_VALIDATED", "request-1",
                                binding={"claimed": True, "task_id": "a-task-that-is-not-on-the-bus",
                                         "task_sha256": "a" * 64, "task_commit": None,
                                         "proof_required": True, "proof": sp.REQUEST_FACT_PROOF})])
        by_id = status["answers"]["request_fate"]["by_request_id"]
        self.assertNotEqual(by_id["request-1"]["lifecycle"], "REQUEST_VALIDATED")
        self.assertEqual(len(state["request_visibility"][
            "acceptance_claims_without_a_signed_task"]), 1, "the claim was folded away")


# --------------------------------------------------------------------------- #
# The real exporter's output, read by the real projector
#
# Same rule as the readiness contract above, and for the same reason. The fact
# shape, the semantic identity and the aggregation belong to the exporter; this
# layer may only carry what it is given. Pinning that against a fixture built here
# would compare this file's constants with themselves, which is how the readiness
# gate set drifted unnoticed for as long as it did.
# --------------------------------------------------------------------------- #
class RequestFactExporterIntegrationTests(RequestVisibilityFixture, unittest.TestCase):
    """Facts produced by the real exporter, consumed by the real projector."""

    T1, T2 = ("2026-09-14T11:00:00Z", "2026-09-14T11:20:00Z")

    def exported(self, instants=None):
        """Run the real exporter over a small bus. Returns (root, export index)."""
        exporter = real_fact_exporter()
        root = pathlib.Path(tempfile.mkdtemp(prefix="ccs-exporter-"))
        (root / "requests").mkdir()
        request_id = "request-1"
        (root / "requests" / (request_id + ".json")).write_bytes(exporter.canonical(
            {"ref": "refs/remotes/origin/boss-request-" + request_id, "head_sha": "b" * 40,
             "path": "requests/" + request_id + ".json",
             "request": {"schema_version": "1", "request_id": request_id,
                         "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                         "requested_at": "2026-09-14T10:50:00Z"}}) + b"\n")
        (root / "ledger.json").write_bytes(exporter.canonical(
            {"version": 1, "requests": {}}) + b"\n")
        polls = []
        for index, instant in enumerate(instants if instants is not None else (self.T1, self.T2)):
            path = root / ("poll-%02d.json" % index)
            path.write_bytes(exporter.canonical(
                {"schema_version": "1", "journaled_at": instant,
                 "bridge_output": {"bridge_version": "synthetic", "channel_mode": "PERSISTENT",
                                   "publish_enabled": True,
                                   "results": [{"pr": "7", "head": "b" * 40, "status": "rejected",
                                                "reason": "pr_head_not_found"}]}}) + b"\n")
            polls.append(str(path))
        index = exporter.export([str(root / "ledger.json")], polls, str(root / "requests"),
                                str(root / "export"), str(FACT_CONTRACT),
                                sp.parse_time("2026-09-14T12:00:00Z"),
                                str(root / "observations.json"))
        return root, index

    def test_the_real_export_is_read_without_a_single_anomaly(self):
        root, _ = self.exported()
        _, state, _ = self.project_one(facts_root=(root / "export"))
        self.assertEqual([a for a in state["anomalies"]
                          if a["kind"].startswith("REQUEST_FACT")], [])

    def test_the_real_semantic_fact_carries_the_earliest_observation(self):
        root, index = self.exported(instants=(self.T2, self.T1))   # newest read first
        exporter = real_fact_exporter()
        self.assertEqual(index["counts"]["facts"], 1, index["counts"])
        fact = exporter.read_json(root / "export" / exporter.FACTS_DIR
                                  / (index["facts"][0]["fact_id"] + ".json"))
        self.assertEqual(fact["first_observed_at"], self.T1)
        # Two observations, one fact document: the aggregation already happened on
        # the exporting side, and how many instants it folded is in the index and
        # in the exporter's own local ledger, not in a second fact.
        self.assertEqual(index["facts"][0]["observation_count"], 2)
        self.assertEqual(index["facts"][0]["last_seen_at"], self.T2)
        _, state, _ = self.project_one(facts_root=(root / "export"))
        entry = state["requests"][0]["facts"][0]
        self.assertEqual(entry["first_observed_at"], self.T1)
        self.assertEqual(entry["identity_rule"], "SEMANTIC")
        self.assertEqual(entry["observations_on_bus"], 1)
        self.assertEqual(state["counts"]["request_facts"], 1)
        self.assertEqual(state["counts"]["request_facts_collapsed"], 0)

    def test_a_real_export_and_a_historical_fact_for_one_outcome_fold_to_one(self):
        """What the live bus looks like across the change: both shapes at once.

        The store still holds the facts the earlier exporter wrote -- one per
        observation -- alongside the semantic one. They are one business fact, so
        one is counted and the others are reported as folded, not discarded.
        """
        root, index = self.exported()
        semantic = index["facts"][0]
        folder = root / "export" / sp.REQUEST_FACTS_DIRNAME
        written = json.loads((folder / (semantic["fact_id"] + ".json")).read_text(encoding="utf-8"))
        historical = {
            "schema_version": "1", "kind": written["kind"], "request_id": written["request_id"],
            "action_id": written["action_id"], "environment": written["environment"], "nonce": None,
            "observed_at": self.T2, "time_source": "POLL_JOURNAL",
            "submission": written["submission"], "source": written["source"],
            "reason": written["reason"], "binding": written["binding"],
            "authority": written["authority"]}
        historical["fact_id"] = "request-fact-" + sp.digest(
            {k: v for k, v in historical.items() if k != "fact_id"})[:32]
        (folder / (historical["fact_id"] + ".json")).write_text(
            json.dumps(historical), encoding="utf-8")

        _, state, _ = self.project_one(facts_root=(root / "export"))
        self.assertEqual(state["counts"]["request_facts"], 1)
        self.assertEqual(state["counts"]["request_facts_collapsed"], 1)
        self.assertEqual(state["requests"][0]["facts"][0]["observations_on_bus"], 2)
        self.assertEqual(state["requests"][0]["lifecycle"], "REQUEST_REJECTED")


# --------------------------------------------------------------------------- #
# CCV1-85 (WP-4A): the candidate digest, and what a disagreement means
# --------------------------------------------------------------------------- #
class CandidateDigestBindingTests(unittest.TestCase):
    """The Command Center cannot recompute the digest, but it can refuse a contradiction.

    A DEPLOY Task under the current contract states the digest of the candidate it is
    about, and the Hong Kong side reports back the digest it loaded and recomputed. Those
    two agreeing is the finding; this class is about the two not agreeing, and about the
    historical Evidence that predates the field being read rather than broken.
    """

    DIGEST = "c" * 64

    def setUp(self):
        self.task_key, self.task_pub = key_pair("cc-task")
        self.evidence_key, self.evidence_pub = key_pair("hk-evidence")

    def deploy_task(self, **over):
        parameters = {"release_id": "release-1",
                      "candidate_image_id": "sha256:" + "a" * 64,
                      "candidate_package_sha256": "b" * 64,
                      "expected_current_image_id": "sha256:" + "a" * 64,
                      "canary_evidence_id": "canary-1", "approval_id": "approval-1",
                      "candidate_contract_sha256": self.DIGEST}
        value = task(action="HK_STAGING_DEPLOY", parameters=parameters)
        value.update(over)
        return sign(value, self.task_key, "hex")

    def deploy_evidence(self, tk, digest="SENTINEL", **over):
        value = evidence(tk, executor_result="DEPLOY_OK",
                         agent_version="0.5.8-candidate-digest",
                         deploy_record_schema_version="2", deploy_record_id="d" * 64,
                         deploy_record_sha256="e" * 64,
                         result="DEPLOY_OK")
        if digest == "SENTINEL":
            digest = self.DIGEST
        if digest is not None:
            value["candidate_contract_sha256"] = digest
        value.update(over)
        return sign(value, self.evidence_key, "base64")

    def project_one(self, tk, ev):
        return build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                     task_pub=self.task_pub, evidence_pub=self.evidence_pub)

    def test_evidence_naming_the_tasks_candidate_is_accepted(self):
        tk = self.deploy_task()
        _loaded, state, _status = self.project_one(tk, self.deploy_evidence(tk))
        entry = state["tasks"][0]
        self.assertNotEqual(entry["lifecycle"], "EVIDENCE_INVALID")
        self.assertEqual(entry["evidence"]["candidate_contract_sha256"], self.DIGEST)

    def test_evidence_naming_another_candidate_is_refused(self):
        tk = self.deploy_task()
        _loaded, state, _status = self.project_one(
            tk, self.deploy_evidence(tk, digest="9" * 64))
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "EVIDENCE_INVALID")
        self.assertEqual(entry["assertion"]["value"], "EVIDENCE_CANDIDATE_DIGEST_BINDING")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_FAILED)

    def test_evidence_that_omits_the_digest_its_task_states_is_refused(self):
        """The field is required for a Task that carries one, not optional forever."""
        tk = self.deploy_task()
        _loaded, state, _status = self.project_one(tk, self.deploy_evidence(tk, digest=None))
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "EVIDENCE_INVALID")
        self.assertEqual(entry["assertion"]["value"], "EVIDENCE_CANDIDATE_DIGEST_BINDING")

    def test_a_malformed_digest_in_the_evidence_is_refused(self):
        for wrong in ("not-a-digest", "C" * 64, "c" * 63):
            with self.subTest(digest=wrong):
                tk = self.deploy_task()
                _loaded, state, _status = self.project_one(
                    tk, self.deploy_evidence(tk, digest=wrong))
                self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_INVALID")

    def test_historical_evidence_for_a_task_without_the_field_is_still_read(self):
        """LEGACY_EVIDENCE_READ_COMPAT, keyed on the Task rather than on the Evidence.

        A deployment that happened before the field existed is not a disagreement: its
        Task states no digest, so there is nothing for the Evidence to contradict. It is
        marked SUPERSEDED -- the shape CCV1-85 replaced -- and it stays in the projection
        rather than being dropped or re-read as current.
        """
        legacy_parameters = {"release_id": "release-1",
                             "candidate_image_id": "sha256:" + "a" * 64,
                             "candidate_package_sha256": "b" * 64,
                             "expected_current_image_id": "sha256:" + "a" * 64,
                             "canary_evidence_id": "canary-1", "approval_id": "approval-1"}
        tk = sign(task(action="HK_STAGING_DEPLOY", parameters=legacy_parameters),
                  self.task_key, "hex")
        _loaded, state, _status = self.project_one(
            tk, self.deploy_evidence(tk, digest=None, agent_version="0.5.7-rebuilt"))
        entry = state["tasks"][0]
        self.assertEqual(entry["parameter_contract"], "SUPERSEDED")
        self.assertNotEqual(entry["lifecycle"], "EVIDENCE_INVALID")

    def test_the_parameter_contract_carries_the_digest_and_the_old_shape_is_superseded(self):
        self.assertEqual(sp.ACTION_PARAMETERS["HK_STAGING_DEPLOY"],
                         {"release_id", "candidate_image_id", "candidate_package_sha256",
                          "expected_current_image_id", "canary_evidence_id", "approval_id",
                          "candidate_contract_sha256"})
        legacy = {"release_id", "candidate_image_id", "candidate_package_sha256",
                  "expected_current_image_id", "canary_evidence_id", "approval_id"}
        self.assertIn(legacy, sp.SUPERSEDED_PARAMETERS["HK_STAGING_DEPLOY"])

    def test_the_binding_rule_is_a_pure_decision(self):
        """The rule, stated directly, so its edges are visible without a fixture."""
        tk = {"action_id": "HK_STAGING_DEPLOY",
              "parameters": {"candidate_contract_sha256": self.DIGEST}}
        self.assertTrue(sp.candidate_digest_binding(tk, {"candidate_contract_sha256": self.DIGEST}))
        self.assertFalse(sp.candidate_digest_binding(tk, {}))
        self.assertFalse(sp.candidate_digest_binding(tk, {"candidate_contract_sha256": "9" * 64}))
        self.assertFalse(sp.candidate_digest_binding(tk, {"candidate_contract_sha256": None}))
        # a Task that states no digest is not a disagreement, and neither is another action
        self.assertTrue(sp.candidate_digest_binding(
            {"action_id": "HK_STAGING_DEPLOY", "parameters": {}}, {}))
        self.assertTrue(sp.candidate_digest_binding(
            {"action_id": "HK_STAGING_VERIFY", "parameters": {"release_id": "r"}}, {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
