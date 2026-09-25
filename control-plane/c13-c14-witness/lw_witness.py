"""CC witness: key handling, the witness record, and the first-seen ledger.

Key discipline (task section 12):

* a **dedicated** Ed25519 key, purpose ``c13c14-acceptance-witness`` — never the
  Task signing key, the HK evidence key or any other existing key;
* the private key is never returned by any attribute, never printed, never
  committed, never written to a log, artifact or Issue. Only the key id, the public
  key and the purpose are recorded.

This module never installs a key. ``from_private_pem`` is for a caller that has
already been authorised to install one; until then the workflow is
``CC_WITNESS_KEY_INSTALLED = NO`` and the ephemeral test key is all that exists.
"""
from __future__ import annotations

import base64
import hashlib
import pathlib

import lw_paths

lw_paths.install()

import lite_canonical  # noqa: E402
from lite_errors import Reject  # noqa: E402

try:  # pragma: no cover - environment dependent
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    HAVE_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTOGRAPHY = False

CC_PURPOSE = "c13c14-acceptance-witness"
HK_PURPOSE = "c13c14-acceptance-witness-hk"

WITNESS_FIELDS = (
    "schema_version",
    "witness_role",
    "witness_purpose",
    "key_id",
    "public_key_pem",
    "candidate_sha",
    "application_tree",
    "C14_ROOT",
    "C13_ROOT",
    "artifact_metadata",
    "verification",
    "first_seen",
    "issued_at",
    "authorizes_any_action",
    "signature",
)

FIRST_SEEN_IDENTITY_FIELDS = (
    "candidate_sha",
    "application_tree",
    "c14_task_id",
    "c14_run_id",
    "c14_execution_id",
    "c14_root",
    "c14_artifact_digest",
    "c13_task_id",
    "c13_run_id",
    "c13_execution_id",
    "c13_root",
    "c13_artifact_digest",
)

#: The *key* is the identity of the execution, not its result. Roots and digests are
#: content: that is what makes "the same execution suddenly reports a different
#: root" a CONFLICT instead of a second, innocent first-seen entry.
FIRST_SEEN_KEY_FIELDS = (
    "candidate_sha",
    "application_tree",
    "c14_task_id",
    "c14_run_id",
    "c14_execution_id",
    "c13_task_id",
    "c13_run_id",
    "c13_execution_id",
)

LEDGER_FIELDS = ("schema_version", "entries", "LEDGER_ROOT")
LEDGER_SCHEMA_VERSION = "go.c13c14.witness.first_seen_ledger.v1"


class WitnessKey:
    """A witness signing key. The private half never leaves this object."""

    def __init__(self, private_key, purpose: str):
        self._private = private_key
        self.purpose = purpose
        self.public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        self.key_id = hashlib.sha256(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).hexdigest()[:16]

    def __repr__(self):  # never leak key material through a repr
        return f"WitnessKey(purpose={self.purpose!r}, key_id={self.key_id!r}, private=<redacted>)"

    @classmethod
    def generate_ephemeral(cls, purpose: str, seed=None) -> "WitnessKey":
        """Deterministic-from-seed when a seed is given, so tests are reproducible."""
        if not HAVE_CRYPTOGRAPHY:
            raise Reject("cryptography_unavailable_for_witness_signing")
        if seed is None:
            private = Ed25519PrivateKey.generate()
        else:
            private = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode("utf-8")).digest())
        return cls(private, purpose)

    @classmethod
    def from_private_pem(cls, path, purpose: str) -> "WitnessKey":
        """Load an already-authorised key. This module never creates the file."""
        if not HAVE_CRYPTOGRAPHY:
            raise Reject("cryptography_unavailable_for_witness_signing")
        raw = pathlib.Path(path).read_bytes()
        private = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(private, Ed25519PrivateKey):
            raise Reject("witness_key_wrong_algorithm", "expected Ed25519")
        return cls(private, purpose)

    def sign(self, payload: bytes) -> str:
        return base64.b64encode(self._private.sign(payload)).decode("ascii")

    @staticmethod
    def verify(public_pem: str, payload: bytes, signature_b64: str) -> bool:
        if not HAVE_CRYPTOGRAPHY:
            raise Reject("cryptography_unavailable_for_witness_signing")
        key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
        if not isinstance(key, Ed25519PublicKey):
            raise Reject("witness_key_wrong_algorithm", "expected Ed25519")
        try:
            key.verify(base64.b64decode(signature_b64), payload)
        except Exception:  # noqa: BLE001 - an invalid signature is simply False
            return False
        return True


def _body(record) -> bytes:
    return lite_canonical.canonical({key: value for key, value in record.items() if key != "signature"})


def build_witness(
    *,
    witness_role: str,
    verification: dict,
    key: WitnessKey,
    first_seen: dict,
    issued_at: str,
    schema_version: str,
) -> dict:
    """Seal one witness record over a verification record and a first-seen entry."""
    if verification.get("decision") != "ACCEPT":
        raise Reject("cannot_witness_a_non_accepted_verification", str(verification.get("decision")))
    record = {
        "schema_version": schema_version,
        "witness_role": witness_role,
        "witness_purpose": key.purpose,
        "key_id": key.key_id,
        "public_key_pem": key.public_pem,
        "candidate_sha": verification["candidate_sha"],
        "application_tree": verification["application_tree"],
        "C14_ROOT": verification["c14_root"],
        "C13_ROOT": verification["c13_root"],
        "artifact_metadata": {
            role: {
                "level_1": verification["artifact"][role]["level_1"],
                "level_2": verification["artifact"][role]["level_2"],
                "artifact_id": verification["artifact"][role]["artifact"]["id"],
                "artifact_name": verification["artifact"][role]["artifact"]["name"],
                "artifact_digest": verification["artifact"][role]["artifact"]["digest"],
                "run_id": verification["artifact"][role]["run"]["id"],
            }
            for role in ("c14", "c13")
        },
        "verification": {
            "decision": verification["decision"],
            "artifact_metadata_verified": verification["artifact_metadata_verified"],
            "artifact_bytes_verified": verification["artifact_bytes_verified"],
        },
        "first_seen": dict(first_seen),
        "issued_at": issued_at,
        "authorizes_any_action": False,
    }
    record["signature"] = key.sign(_body(record))
    return record


def verify_witness(record: dict) -> None:
    """Recompute the signature and the binding; Reject on any mismatch."""
    if not isinstance(record, dict) or set(record) != set(WITNESS_FIELDS):
        raise Reject("witness_field_set_mismatch")
    if record["authorizes_any_action"] is not False:
        raise Reject("authorizes_any_action_must_be_false")
    if not WitnessKey.verify(record["public_key_pem"], _body(record), record["signature"]):
        raise Reject("witness_signature_invalid")
    if record["first_seen"].get("candidate_sha") != record["candidate_sha"]:
        raise Reject("witness_first_seen_candidate_mismatch")


class FirstSeenLedger:
    """Append-only, immutable-semantics first-seen ledger (task section 11)."""

    def __init__(self, entries=None):
        self.entries = list(entries or [])

    @staticmethod
    def key_of(entry) -> str:
        return "|".join(str(entry.get(field)) for field in FIRST_SEEN_KEY_FIELDS)

    def root(self) -> str:
        return lite_canonical.digest(sorted(self.entries, key=self.key_of))

    def as_dict(self) -> dict:
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "entries": sorted(self.entries, key=self.key_of),
            "LEDGER_ROOT": self.root(),
        }

    def observe(self, entry: dict) -> str:
        """``FIRST_SEEN`` / ``UNCHANGED`` / ``CONFLICT``. A conflict is never applied."""
        if not isinstance(entry, dict) or any(field not in entry for field in FIRST_SEEN_IDENTITY_FIELDS):
            raise Reject("first_seen_entry_incomplete")
        key = self.key_of(entry)
        for stored in self.entries:
            if self.key_of(stored) == key:
                if lite_canonical.canonical(stored) != lite_canonical.canonical(entry):
                    return "CONFLICT"
                return "UNCHANGED"
        self.entries.append(dict(entry))
        return "FIRST_SEEN"

    @classmethod
    def load(cls, path) -> "FirstSeenLedger":
        import json

        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if set(raw) != set(LEDGER_FIELDS):
            raise Reject("first_seen_ledger_field_set_mismatch")
        ledger = cls(raw["entries"])
        if ledger.root() != raw["LEDGER_ROOT"]:
            raise Reject("first_seen_ledger_root_mismatch")
        return ledger

    def dump(self, path) -> dict:
        import json

        payload = self.as_dict()
        pathlib.Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
        return payload


def first_seen_from_execution_records(c14_record: dict, c13_record: dict, *, at: str) -> dict:
    entry = {
        "candidate_sha": c14_record["candidate_sha"],
        "application_tree": c14_record["application_tree"],
        "c14_task_id": c14_record["task_id"],
        "c14_run_id": c14_record["github_run_id"],
        "c14_execution_id": c14_record["ai_execution_id"],
        "c14_root": c14_record["root_hash"],
        "c14_artifact_digest": c14_record["artifact"]["digest"],
        "c13_task_id": c13_record["task_id"],
        "c13_run_id": c13_record["github_run_id"],
        "c13_execution_id": c13_record["ai_execution_id"],
        "c13_root": c13_record["root_hash"],
        "c13_artifact_digest": c13_record["artifact"]["digest"],
        "first_seen_at": at,
        "verification_status": "ACCEPT",
    }
    return entry
