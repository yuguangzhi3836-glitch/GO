"""CCV1-145 full-chain acceptance simulation.

The chain this module walks:

    real candidate commit
        -> C14 rule/compliance record
        -> C13 quality acceptance record
        -> CC ReviewVerifier
        -> CC witness  (signed on CC, with CC's own installed key)
        -> HK witness  (signed on HK, with HK's own installed key)
        -> FinalAcceptanceAggregator
        -> FINAL_ROOT
        -> READY_FOR_HUMAN_AUTHORIZATION   (stop)

Two parts are real and two are simulated, and the module keeps them apart **in the
data**, not only in prose:

    REAL       the candidate commit and its application tree, taken from a commit
               that actually exists in the repository
    REAL       the CC and HK witness signatures, each produced on its own host by
               that host's own installed Ed25519 key
    SIMULATED  the C13/C14 verdicts. The local backend produces the bundles; no
               GitHub Actions run was dispatched, so no production C13/C14 verdict
               exists for this candidate.
    SIMULATED  the execution identity inside the bundles (run id, AI execution id).

One consequence is structural rather than cosmetic: because no GitHub run produced
these bundles, there is no artifact to bind. The witness records therefore carry
``artifact_metadata[role].binding = NOT_APPLICABLE`` with every artifact field null.
That is a *different* state from "an artifact exists but could not be verified", and
the two must never be allowed to look alike.

This module never signs anything. Signing happens on the witness hosts, which is
the only place the private halves exist.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from datetime import datetime, timezone

import lw_paths

lw_paths.install()

import lite_canonical  # noqa: E402
import lite_execution_record  # noqa: E402
import lite_fixtures  # noqa: E402
from lite_errors import Reject  # noqa: E402

import lw_aggregate  # noqa: E402
import lw_verifier  # noqa: E402
import lw_witness  # noqa: E402

TASK_PACKAGE_SCHEMA_VERSION = "go.c13c14.witness.task_package.v1"
CHAIN_SCHEMA_VERSION = "go.c13c14.witness.full_chain.v1"

TASK_ID = "CCV1-145-14CELL-FULL-CHAIN-SIMULATION"

EXECUTION_CARRIER_LOCAL = "LOCAL_BACKEND"
EXECUTION_CARRIER_GITHUB = "GITHUB_ACTIONS"

#: The machine-evidence files the C13 bundle commits to by digest. Named separately
#: from the opinion artifacts so a report can state which is which.
MACHINE_EVIDENCE_NAMES = ("junit", "stdout", "manifest")

#: The reviewer opinions the bundle root commits to by digest. The backend recomputes
#: every one of these, so a tampered opinion byte is caught before any witness sees
#: the round. They travel in the task package for exactly that reason.
OPINION_ARTIFACT_NAMES = ("c14_opinion", "c13_opinion")

REQUIRED_PACKAGE_FIELDS = (
    "schema_version",
    "task",
    "execution_carrier",
    "candidate",
    "now",
    "dispatch",
    "implementation_execution_id",
    "c14_bundle",
    "c13_bundle",
    "c14_contract",
    "c13_contract",
    "artifacts",
    "artifact_names",
    "first_seen",
    "labels",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(instant) -> str:
    """Serialise an instant so a task package round-trips through JSON exactly."""
    if isinstance(instant, str):
        return instant
    return instant.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


#: What is real and what is simulated, as machine-readable constants so a reader of
#: the data cannot mistake one for the other.
def labels() -> dict:
    return {
        "REAL_CANDIDATE_COMMIT": True,
        "REAL_CC_WITNESS_SIGNING": True,
        "REAL_HK_WITNESS_SIGNING": True,
        "C13_C14_BUNDLE_SOURCE": EXECUTION_CARRIER_LOCAL,
        "C13_PRODUCTION_WORKFLOW_DISPATCHED": False,
        "C14_PRODUCTION_WORKFLOW_DISPATCHED": False,
        "REAL_C13_C14_VERDICT": "NOT_TESTED",
        "PR247_IS_EVIDENCE": False,
    }


def candidate_from_repository(repo_root, *, rev="origin/main") -> dict:
    """The candidate is a commit that really exists, not a fabricated sha."""
    import subprocess

    def git(*args):
        return subprocess.run(["git", "-C", str(repo_root), *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    return {
        "sha": git("rev-parse", rev),
        "application_tree": git("rev-parse", f"{rev}^{{tree}}"),
        "source": rev,
        "subject": git("log", "-1", "--format=%s", rev),
        "committed_at": git("log", "-1", "--format=%cs", rev),
        "is_real_commit": True,
    }


def first_seen_for(round_, *, at: str | None = None) -> dict:
    """First-seen entry whose content digests are over **real bytes**.

    The execution identity inside it (run ids, AI execution ids) is simulated and
    labelled as such; the artifact digests are not invented — they are the sha256 of
    the sealed bundle bytes the witness will actually be reviewing.
    """
    c14_bytes = lite_canonical.canonical(round_["c14_bundle"])
    c13_bytes = lite_canonical.canonical(round_["c13_bundle"])
    c14_record = lite_execution_record.build(
        round_["c14_bundle"],
        artifact={"name": None, "id": None,
                  "digest": "sha256:" + hashlib.sha256(c14_bytes).hexdigest()},
        evidence_path=None,
    )
    c13_record = lite_execution_record.build(
        round_["c13_bundle"],
        artifact={"name": None, "id": None,
                  "digest": "sha256:" + hashlib.sha256(c13_bytes).hexdigest()},
        evidence_path=None,
    )
    entry = lw_witness.first_seen_from_execution_records(c14_record, c13_record, at=at)
    entry["execution_identity_binding"] = "SIMULATED_LOCAL_BACKEND"
    entry["artifact_digest_binding"] = "SEALED_BUNDLE_BYTES"
    return entry


def build_task_package(round_, *, candidate: dict) -> dict:
    """Everything a witness host needs to re-derive the verification for itself."""
    if round_["c14_bundle"]["candidate_sha"] != candidate["sha"]:
        raise Reject("task_package_candidate_mismatch")
    if round_["c14_bundle"]["application_tree"] != candidate["application_tree"]:
        raise Reject("task_package_application_tree_mismatch")
    if round_["c13_bundle"]["candidate_sha"] != candidate["sha"]:
        raise Reject("task_package_candidate_mismatch", "c13")

    return {
        "schema_version": TASK_PACKAGE_SCHEMA_VERSION,
        "task": TASK_ID,
        "execution_carrier": EXECUTION_CARRIER_LOCAL,
        "candidate": dict(candidate),
        "now": iso(round_["now"]),
        "dispatch": round_["dispatch"],
        "implementation_execution_id": round_["implementation_execution_id"],
        "c14_bundle": round_["c14_bundle"],
        "c13_bundle": round_["c13_bundle"],
        "c14_contract": round_["c14_contract"],
        "c13_contract": round_["c13_contract"],
        # Every artifact the bundle root commits to, not just the machine evidence:
        # the reviewer opinions are bound by digest too, and the host must be able to
        # recompute all of them or it is not really verifying anything.
        "artifacts": {
            name: base64.b64encode(raw).decode("ascii")
            for name, raw in sorted(round_["artifacts"].items())
        },
        "artifact_names": sorted(round_["artifacts"]),
        "machine_evidence_names": [name for name in MACHINE_EVIDENCE_NAMES
                                   if name in round_["artifacts"]],
        "opinion_artifact_names": [name for name in OPINION_ARTIFACT_NAMES
                                   if name in round_["artifacts"]],
        "artifact_binding": lw_witness.ARTIFACT_BINDING_NOT_APPLICABLE,
        "artifact_binding_reason": "execution_carrier_is_local_backend",
        "first_seen": first_seen_for(round_),
        "labels": labels(),
    }


def prepare_task_package(*, repo_root, rev="origin/main", now=None, **round_overrides) -> dict:
    """Build one round for a real candidate commit and package it for the hosts."""
    candidate = candidate_from_repository(repo_root, rev=rev)
    instant = parse_instant(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
    round_ = lite_fixtures.make_round(
        candidate_sha=candidate["sha"],
        application_tree=candidate["application_tree"],
        now=instant,
        **round_overrides,
    )
    return build_task_package(round_, candidate=candidate)


def load_package(path) -> dict:
    package = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    missing = [field for field in REQUIRED_PACKAGE_FIELDS if field not in package]
    if missing:
        raise Reject("task_package_incomplete", ",".join(missing))
    if package["schema_version"] != TASK_PACKAGE_SCHEMA_VERSION:
        raise Reject("task_package_schema_version_mismatch")
    return package


def dump_package(package: dict, path) -> pathlib.Path:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    return target


def verify_from_package(package: dict) -> dict:
    """Run the CC ReviewVerifier from the received package bytes.

    A witness host calls this instead of being handed a verdict, so the verification
    it signs is one it performed itself.
    """
    artifacts = {name: base64.b64decode(raw)
                 for name, raw in package["artifacts"].items()}
    return lw_verifier.verify(
        c14_bundle=package["c14_bundle"],
        c13_bundle=package["c13_bundle"],
        c14_contract=package["c14_contract"],
        c13_contract=package["c13_contract"],
        dispatch=package["dispatch"],
        implementation_execution_id=package["implementation_execution_id"],
        artifacts=artifacts,
        now=parse_instant(package["now"]),
    )


def aggregate_round(*, verification: dict, cc_witness: dict, hk_witness=None) -> dict:
    """FinalAcceptanceAggregator over the two real witnesses. Stops at the human gate."""
    return lw_aggregate.aggregate(
        verification=verification,
        cc_witness=cc_witness,
        hk_witness=hk_witness,
    )


def finalise(*, verification: dict, cc_witness: dict, hk_witness=None) -> dict:
    """Aggregate and fully verify the result, so the caller cannot skip a layer."""
    record = aggregate_round(verification=verification, cc_witness=cc_witness,
                             hk_witness=hk_witness)
    lw_aggregate.verify_record(record, verification=verification)
    return record


def summary(*, package: dict, verification: dict, cc_witness=None, hk_witness=None,
            record=None) -> dict:
    """The round's machine-readable answer, with the labels attached."""
    out = {
        "schema_version": CHAIN_SCHEMA_VERSION,
        "task": TASK_ID,
        "labels": dict(package.get("labels") or labels()),
        "execution_carrier": package.get("execution_carrier"),
        "candidate": package.get("candidate"),
        "c14_root": verification.get("c14_root"),
        "c13_root": verification.get("c13_root"),
        "verification_decision": verification.get("decision"),
        "artifact_metadata_verified": verification.get("artifact_metadata_verified"),
        "artifact_bytes_verified": verification.get("artifact_bytes_verified"),
        "artifact_binding": {
            role: ((cc_witness or {}).get("artifact_metadata") or {}).get(role, {}).get("binding")
            for role in ("c14", "c13")
        },
        "cc_witness_key_id": (cc_witness or {}).get("key_id"),
        "cc_witness_signature_present": bool((cc_witness or {}).get("signature")),
        "hk_witness_key_id": (hk_witness or {}).get("key_id"),
        "hk_witness_signature_present": bool((hk_witness or {}).get("signature")),
        "cc_hk_keys_distinct": bool(
            cc_witness and hk_witness and cc_witness.get("key_id") != hk_witness.get("key_id")),
        "status": (record or {}).get("status"),
        "gate": (record or {}).get("gate"),
        "FINAL_ROOT": (record or {}).get("FINAL_ROOT"),
        "human_authorization_required": (record or {}).get("human_authorization_required"),
        "authorizes_any_action": False,
        "auto_deploy": False,
    }
    return out


__all__ = [
    "CHAIN_SCHEMA_VERSION",
    "EXECUTION_CARRIER_GITHUB",
    "EXECUTION_CARRIER_LOCAL",
    "MACHINE_EVIDENCE_NAMES",
    "OPINION_ARTIFACT_NAMES",
    "TASK_ID",
    "TASK_PACKAGE_SCHEMA_VERSION",
    "aggregate_round",
    "build_task_package",
    "candidate_from_repository",
    "dump_package",
    "finalise",
    "first_seen_for",
    "iso",
    "labels",
    "load_package",
    "parse_instant",
    "prepare_task_package",
    "summary",
    "utc_now",
    "verify_from_package",
]
