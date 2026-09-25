"""Witness host runner: the part of CCV1-145 that must execute *on* CC and HK.

Everything else in this layer can run anywhere. This module cannot: it is the only
place that reads a host's installed witness private key, and the private half never
leaves the machine. The host therefore does four things for itself:

1. re-derives the verification from the received task package, instead of being
   handed a verdict to sign;
2. optionally reads the remote GitHub facts with **its own** credential, as carrier
   evidence (this is the probe, not the reviewed candidate — see below);
3. signs its own witness record with its own installed key;
4. reports the public facts: key id, purpose, and what it verified.

The run's status is the host's own, not a claim relayed from elsewhere: two hosts
each signing a record they did not compute would be one witness wearing two hats.

The readback in step 2 targets a **pre-existing** harmless POC run. It cannot target
this round's candidate, because this round's candidate has no GitHub run at all (the
execution carrier is the local backend). It is recorded under ``carrier_probe`` and
is explicitly not an artifact binding.
"""
from __future__ import annotations

import argparse
import json
import platform
import pathlib
import socket
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_witness  # noqa: E402
from lite_errors import Reject  # noqa: E402

import lw_chain  # noqa: E402
import lw_hk  # noqa: E402

REPORT_SCHEMA_VERSION = "go.c13c14.witness.host_report.v1"

CC_WITNESS_SCHEMA_VERSION = "go.c13c14.witness.cc_witness.v1"

#: Private-key material must never appear in anything this runner writes.
PRIVATE_KEY_MARKERS = ("PRIVATE KEY", "PRIVATE_KEY")


def _host_facts() -> dict:
    facts = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    try:
        import cryptography

        facts["cryptography"] = cryptography.__version__
    except ImportError:  # pragma: no cover - environment dependent
        facts["cryptography"] = None
    return facts


def _carrier_probe(*, credential_path, run_id, expected_head_sha, workflow_path,
                   candidate_sha, repository=None) -> dict:
    """Read real GitHub facts with this host's own credential, as circumstantial
    evidence that the far end of the chain is live. Never an artifact binding."""
    import lw_credential
    import lw_readback

    if credential_path is None:
        return {"performed": False, "reason": "no_credential_path_given"}
    try:
        credential = lw_credential.load(credential_path)
    except lw_credential.CredentialError as error:
        return {"performed": False, "reason": str(error),
                "credential_present": False}
    record = lw_readback.readback_role(
        repository=repository or lw_credential.REPOSITORY,
        role="c14",
        candidate_sha=candidate_sha,
        workflow_path=workflow_path,
        run_id=run_id,
        token=credential.token,
        expected_head_sha=expected_head_sha,
    )
    record["performed"] = True
    record["credential"] = credential.summary()
    record["carrier_probe_not_this_candidate"] = True
    return record


def run(*, role, package, private_key_path, issued_at=None, cc_witness=None,
        carrier_probe=None) -> tuple:
    """Return ``(witness_record, report)``. Raises only on a real refusal."""
    verification = lw_chain.verify_from_package(package)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "host_role": role,
        "task": package.get("task"),
        "execution_carrier": package.get("execution_carrier"),
        "candidate_sha": package.get("candidate", {}).get("sha"),
        "application_tree": package.get("candidate", {}).get("application_tree"),
        "private_key_path": str(private_key_path),
        "private_key_recorded": False,
        "issued_at": None,
        "verification_decision": verification.get("decision"),
        "verification_rejects": verification.get("rejects"),
        "verification_blocks": verification.get("blocks"),
        "c14_root": verification.get("c14_root"),
        "c13_root": verification.get("c13_root"),
        "artifact_metadata_verified": verification.get("artifact_metadata_verified"),
        "artifact_bytes_verified": verification.get("artifact_bytes_verified"),
        "witness_schema_version": None,
        "witness_signature_present": False,
        "witness_digest": None,
        "key_id": None,
        "witness_purpose": None,
        "public_key_pem": None,
        "carrier_probe": carrier_probe,
        "host_facts": _host_facts(),
        "authorizes_any_action": False,
    }
    if not verification.get("ok"):
        report["refused"] = "verification_not_accepted"
        return None, report

    purpose = lw_witness.CC_PURPOSE if role == "cc" else lw_witness.HK_PURPOSE
    key = lw_witness.WitnessKey.from_private_pem(private_key_path, purpose)
    instant = issued_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    if role == "cc":
        record = lw_witness.build_witness(
            witness_role="CC",
            verification=verification,
            key=key,
            first_seen=package["first_seen"],
            issued_at=instant,
            schema_version=CC_WITNESS_SCHEMA_VERSION,
        )
    else:
        if cc_witness is None:
            raise Reject("hk_requires_the_cc_witness")
        record = lw_hk.witness(
            verification=verification,
            cc_witness=cc_witness,
            key=key,
            first_seen=package["first_seen"],
            issued_at=instant,
        )

    # Verify what we are about to publish, before publishing it.
    lw_witness.verify_witness(record)
    serialised = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if any(marker in serialised for marker in PRIVATE_KEY_MARKERS):
        raise Reject("witness_record_would_contain_private_key_material")

    report.update({
        "issued_at": record["issued_at"],
        "witness_schema_version": record["schema_version"],
        "witness_signature_present": bool(record.get("signature")),
        "witness_digest": lw_witness.lite_canonical.digest(record),
        "key_id": record["key_id"],
        "witness_purpose": record["witness_purpose"],
        "public_key_pem": record["public_key_pem"],
        "artifact_binding": {
            role_name: record["artifact_metadata"][role_name]["binding"]
            for role_name in ("c14", "c13")
        },
    })
    return record, report


def _write_json(payload: dict, path) -> pathlib.Path:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("cc", "hk"), required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--out-witness", required=True)
    parser.add_argument("--out-report", required=True)
    parser.add_argument("--cc-witness", help="the CC witness (required for --role hk)")
    parser.add_argument("--issued-at")
    parser.add_argument("--credential-path",
                        help="this host's GitHub witness credential, for carrier evidence")
    parser.add_argument("--readback-run-id", type=int)
    parser.add_argument("--readback-expected-head-sha")
    parser.add_argument("--readback-workflow-path")
    parser.add_argument("--readback-candidate-sha")
    parser.add_argument("--repository")
    args = parser.parse_args(argv)

    package = lw_chain.load_package(args.package)
    cc_witness = None
    if args.cc_witness:
        cc_witness = json.loads(pathlib.Path(args.cc_witness).read_text(encoding="utf-8"))

    carrier_probe = None
    if args.readback_run_id:
        carrier_probe = _carrier_probe(
            credential_path=args.credential_path,
            run_id=args.readback_run_id,
            expected_head_sha=args.readback_expected_head_sha,
            workflow_path=args.readback_workflow_path,
            candidate_sha=args.readback_candidate_sha or package["candidate"]["sha"],
            repository=args.repository,
        )

    record, report = run(
        role=args.role,
        package=package,
        private_key_path=args.private_key,
        issued_at=args.issued_at,
        cc_witness=cc_witness,
        carrier_probe=carrier_probe,
    )

    if record is not None:
        _write_json(record, args.out_witness)
    _write_json(report, args.out_report)

    print(json.dumps({
        "host_role": args.role,
        "verification_decision": report["verification_decision"],
        "witness_written": record is not None,
        "key_id": report["key_id"],
        "witness_purpose": report["witness_purpose"],
        "artifact_binding": report.get("artifact_binding"),
        "refused": report.get("refused"),
    }, ensure_ascii=False))
    return 0 if record is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
