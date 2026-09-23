"""Offline acceptance of the one fixed, Owner-signed C14 registration.

This check produces no C14 receipt and grants no execution permission. Caller
must fetch source bytes and provenance independently from the fixed Git commit.
"""
from __future__ import annotations

import hashlib
import json
import argparse
import sys
from pathlib import Path

from verify_c14_registration import RegistrationError, canonical, load_authority, verify

COMMIT = "a8a1191e8693581bdaf58557313265be75fbe4fa"
PATH = "control-plane/c14-receipt-verifier-v1/C14_REGISTRATION_TO_SIGN.v2.json"
BLOB = "74dc7c9c6cf2da66541876d3de9c9a0549702257"
SHA256 = "07ba520cfb1d782011f6b21a7582b29fd73af68524db9d4c892370475876b6a3"
SIGNATURE = "MEUCIQCSSIbPqkc86-KOMXCfUs_FXJ2_8v-56qmrvDvYKJn-MQIgASGUlFEPlAdTH_IbVgTK0qWlR95d72CbFYqRs9YtL6M"


def accept(source: bytes, envelope: object, public_key: Path, *,
           commit: str, path: str, blob: str, exception_mode: str) -> dict[str, str]:
    if exception_mode != "OWNER_SINGLE_PERSON_EXCEPTION":
        raise RegistrationError("OWNER_EXCEPTION_NOT_DECLARED")
    if (commit, path, blob) != (COMMIT, PATH, BLOB):
        raise RegistrationError("REGISTRATION_SOURCE_MISMATCH")
    if len(source) != 621 or hashlib.sha256(source).hexdigest() != SHA256:
        raise RegistrationError("REGISTRATION_BYTES_MISMATCH")
    if hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest() != BLOB:
        raise RegistrationError("REGISTRATION_BLOB_MISMATCH")
    try:
        value = json.loads(source)
    except (UnicodeError, ValueError) as exc:
        raise RegistrationError("REGISTRATION_JSON_INVALID") from exc
    if source != canonical(value):
        raise RegistrationError("REGISTRATION_BYTES_NOT_CANONICAL")
    if not isinstance(envelope, dict) or envelope.get("registration") != value or envelope.get("signature") != SIGNATURE:
        raise RegistrationError("OWNER_SIGNED_ENVELOPE_MISMATCH")
    registration = verify(envelope, load_authority(public_key))
    return {"mode": exception_mode, "source_commit": commit, "source_blob": blob,
            "source_sha256": SHA256, "signer_key_version": registration["signer_key_version"],
            "status": "REGISTRATION_VERIFIED_ONLY"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline fixed Owner registration check; never issues a receipt")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--signed-envelope", type=Path, required=True)
    parser.add_argument("--trusted-authority-public-key", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--source-blob", required=True)
    parser.add_argument("--exception-mode", required=True)
    args = parser.parse_args()
    try:
        result = accept(args.source.read_bytes(), json.loads(args.signed_envelope.read_bytes()),
                        args.trusted_authority_public_key, commit=args.source_commit,
                        path=args.source_path, blob=args.source_blob,
                        exception_mode=args.exception_mode)
    except (OSError, ValueError, RegistrationError) as exc:
        print(f"VERIFY_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
