"""Verify an installed witness signing key, on the host that holds it.

Run after ``install-witness-signing-key.sh``. It answers, with evidence rather than
assurance, the questions the installation authorisation asks for:

    algorithm verification          is this really Ed25519, by two toolchains?
    public key derivation           does the private half derive the public half on disk?
    key_id / fingerprint            what is this key, in the project's id convention?
    local sign -> verify positive   does a real signature verify?
    modified payload -> failure     is a tampered payload rejected?
    modified signature -> failure   is a tampered signature rejected?
    no reuse of an existing key     does it differ from every other key on this host?

The signature test uses ``WitnessKey.from_private_pem`` — the same code path the witness
will use — and is cross-checked with ``openssl``, so agreement means two independent
implementations agree rather than one implementation agreeing with itself.

The private key is loaded, used and never returned, printed, written elsewhere or
included in the report. Existing keys are compared **by public key only**: this module
never reads another key's private half.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_witness  # noqa: E402

try:  # pragma: no cover - environment dependent
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    HAVE_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTOGRAPHY = False

KEY_LAYOUT = {
    "cc": {
        "dir": "/etc/go-command-center/keys",
        "private": "c13-c14-witness-ed25519.pem",
        "public": "c13-c14-witness-ed25519.pub",
        "purpose": lw_witness.CC_PURPOSE,
    },
    "hk": {
        "dir": "/etc/go-hk-agent/keys",
        "private": "c13-c14-witness-ed25519.pem",
        "public": "c13-c14-witness-ed25519.pub",
        "purpose": lw_witness.HK_PURPOSE,
    },
}

#: A fixed payload, so a signature produced here is reproducible for a reviewer.
TEST_PAYLOAD = b"go.c13c14.witness.keycheck.v1"


def spki_der_of_public_file(path: pathlib.Path) -> bytes:
    """Read any public key file on these hosts and return its SPKI DER.

    Only public files are ever passed here. Both formats present on the hosts are
    handled: OpenSSH one-liners (``*.pub``) and SPKI PEM (``*-public.pem``).
    """
    raw = path.read_bytes().strip()
    if raw.startswith(b"ssh-"):
        key = serialization.load_ssh_public_key(raw)
    else:
        key = serialization.load_pem_public_key(raw)
    return key.public_bytes(serialization.Encoding.DER,
                            serialization.PublicFormat.SubjectPublicKeyInfo)


def fingerprint_of_spki_der(der: bytes) -> str:
    """The project's fingerprint convention, established in CCV1-113/134/135."""
    return "sha256:" + hashlib.sha256(der).hexdigest()


def existing_public_keys(key_dir: pathlib.Path, *, exclude: set) -> dict:
    """Every other *public* key in the directory. Private files are never opened."""
    found = {}
    for path in sorted(key_dir.iterdir()):
        if path.name in exclude or not path.is_file():
            continue
        if path.name.endswith(".pub") or path.name.endswith("-public.pem"):
            try:
                der = spki_der_of_public_file(path)
            except Exception as error:  # noqa: BLE001 - a malformed file is a finding
                found[path.name] = {"error": type(error).__name__}
                continue
            found[path.name] = {
                "fingerprint": fingerprint_of_spki_der(der),
                "key_id": hashlib.sha256(der).hexdigest()[:16],
            }
    return found


def _openssl(*args, stdin=None) -> tuple:
    result = subprocess.run(["openssl", *args], input=stdin, capture_output=True)
    return result.returncode, result.stdout.decode("utf-8", "replace"), \
        result.stderr.decode("utf-8", "replace")


def keycheck(host: str, *, key_dir=None, private_path=None, public_path=None,
             other_host_fingerprints=None) -> dict:
    layout = KEY_LAYOUT[host]
    key_dir = pathlib.Path(key_dir or layout["dir"])
    private_file = pathlib.Path(private_path or key_dir / layout["private"])
    public_file = pathlib.Path(public_path or key_dir / layout["public"])

    report = {
        "schema_version": "go.c13c14.witness.keycheck.v1",
        "host": host,
        "purpose": layout["purpose"],
        "private_path": str(private_file),
        "public_path": str(public_file),
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": {},
        "private_key_read_by_other_modules": False,
        "authorizes_any_action": False,
    }
    checks = report["checks"]

    # --- custody ---------------------------------------------------------------
    #
    # POSIX permission bits only exist on the host. The check is gated rather than
    # relaxed, so a unit test on a developer workstation cannot report a key as safe
    # because Windows has no group and other bits to inspect.
    posix = os.name == "posix"
    for label, path in (("private", private_file), ("public", public_file)):
        if not path.is_file():
            checks[f"{label}_exists"] = False
            report["verdict"] = "FAIL"
            return report
        stat = path.stat()
        checks[f"{label}_exists"] = True
        report[f"{label}_custody"] = {
            "mode": oct(stat.st_mode & 0o777),
            "uid": stat.st_uid,
            "gid": stat.st_gid,
            "size": stat.st_size,
        }
    report["custody_checked"] = posix
    if posix:
        private_mode = int(report["private_custody"]["mode"], 8)
        public_mode = int(report["public_custody"]["mode"], 8)
        checks["private_mode_is_0600"] = private_mode == 0o600
        checks["private_not_group_or_world_accessible"] = private_mode & 0o077 == 0
        checks["public_not_group_or_world_writable"] = public_mode & 0o022 == 0
    else:
        report["custody_check_skipped"] = (
            "not a POSIX host: permission bits are not meaningful here")

    # --- load through the witness code path (the authorised loader) -----------
    key = lw_witness.WitnessKey.from_private_pem(private_file, layout["purpose"])
    checks["witness_key_loaded"] = True
    report["purpose_from_loader"] = key.purpose
    report["key_id"] = key.key_id
    report["public_key_pem_spki"] = key.public_pem

    # --- algorithm verification, two toolchains -------------------------------
    #
    # Every openssl call below is made against *public* material only. `asn1parse` on a
    # private key prints the key bytes as a hex dump, so it is never pointed at the
    # private file: the OID is read from the SPKI that openssl derives from it.
    raw_private = serialization.load_pem_private_key(private_file.read_bytes(), password=None)
    checks["cryptography_sees_ed25519_private"] = isinstance(raw_private, Ed25519PrivateKey)
    rc, out, _ = _openssl("pkey", "-in", str(private_file), "-text_pub", "-noout")
    checks["openssl_sees_ed25519"] = rc == 0 and "ED25519" in out.upper()

    workdir = pathlib.Path(tempfile.mkdtemp())
    try:
        public_der_file = workdir / "public-spki.der"
        rc, _, _ = _openssl("pkey", "-in", str(private_file), "-pubout",
                            "-outform", "DER", "-out", str(public_der_file))
        rc2, oid_out, _ = _openssl("asn1parse", "-in", str(public_der_file),
                                   "-inform", "DER")
        # asn1parse resolves the OID to its name; the numeric form is accepted too.
        checks["openssl_oid_is_ed25519"] = (
            rc == 0 and rc2 == 0
            and ("ED25519" in oid_out.upper() or "1.3.101.112" in oid_out))

        # --- public key derivation ---------------------------------------------
        derived_der = raw_private.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        checks["openssl_derived_public_matches_cryptography"] = (
            public_der_file.read_bytes() == derived_der)
        on_disk_der = spki_der_of_public_file(public_file)
        checks["derived_public_matches_disk"] = derived_der == on_disk_der
        checks["loaded_key_matches_disk"] = (
            hashlib.sha256(derived_der).hexdigest()[:16] == key.key_id)
        report["public_key_openssh"] = public_file.read_text(encoding="utf-8").strip()
        report["fingerprint"] = fingerprint_of_spki_der(derived_der)
        report["public_key_algorithm"] = type(raw_private.public_key()).__name__
        checks["public_key_is_ed25519"] = isinstance(raw_private.public_key(),
                                                    Ed25519PublicKey)

        # --- real sign -> verify, through the witness code ---------------------
        signature = key.sign(TEST_PAYLOAD)
        checks["witness_sign_verify_positive"] = lw_witness.WitnessKey.verify(
            key.public_pem, TEST_PAYLOAD, signature)
        checks["witness_verify_rejects_modified_payload"] = not lw_witness.WitnessKey.verify(
            key.public_pem, TEST_PAYLOAD + b"x", signature)
        checks["witness_verify_rejects_modified_signature"] = not lw_witness.WitnessKey.verify(
            key.public_pem, TEST_PAYLOAD, key.sign(b"other payload"))

        # --- the same signature, checked by openssl -----------------------------
        payload_file = workdir / "payload.bin"
        payload_file.write_bytes(TEST_PAYLOAD)
        tampered_file = workdir / "tampered.bin"
        tampered_file.write_bytes(TEST_PAYLOAD + b"x")
        signature_file = workdir / "signature.bin"
        signature_file.write_bytes(base64.b64decode(signature))
        spki_pem = workdir / "public-spki.pem"
        spki_pem.write_bytes(raw_private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo))

        rc, _, _ = _openssl("pkeyutl", "-verify", "-rawin", "-pubin",
                            "-inkey", str(spki_pem), "-in", str(payload_file),
                            "-sigfile", str(signature_file))
        checks["openssl_verifies_our_signature"] = rc == 0
        rc2, _, _ = _openssl("pkeyutl", "-verify", "-rawin", "-pubin",
                             "-inkey", str(spki_pem), "-in", str(tampered_file),
                             "-sigfile", str(signature_file))
        checks["openssl_rejects_modified_payload"] = rc2 != 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # --- no reuse of any other key on this host -------------------------------
    others = existing_public_keys(
        key_dir, exclude={private_file.name, public_file.name})
    report["other_public_keys"] = others
    collisions = [name for name, info in others.items()
                  if info.get("fingerprint") == report["fingerprint"]]
    checks["no_reuse_of_an_existing_key"] = not collisions
    report["reused_from"] = collisions

    # --- and not the other host's key -----------------------------------------
    if other_host_fingerprints:
        cross = {name: fp for name, fp in other_host_fingerprints.items()
                 if fp == report["fingerprint"]}
        checks["differs_from_the_other_host"] = not cross
        report["matches_other_host_keys"] = list(cross)

    report["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("cc", "hk"), required=True)
    parser.add_argument("--key-dir", help="override the key directory (testing)")
    parser.add_argument("--private-path")
    parser.add_argument("--public-path")
    parser.add_argument("--other-host-fingerprint", action="append", default=[],
                        help="repeatable; a fingerprint from the other host's key")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    if not HAVE_CRYPTOGRAPHY:
        print(json.dumps({"error": "cryptography_unavailable"}))
        return 3

    other = {f"other-host-{index + 1}": value
             for index, value in enumerate(args.other_host_fingerprint)}
    report = keycheck(args.host, key_dir=args.key_dir, private_path=args.private_path,
                      public_path=args.public_path,
                      other_host_fingerprints=other or None)
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")

    summary = {
        "host": args.host,
        "verdict": report.get("verdict"),
        "key_id": report.get("key_id"),
        "fingerprint": report.get("fingerprint"),
        "purpose": report.get("purpose"),
        "failing_checks": [name for name, ok in report["checks"].items() if not ok],
    }
    print(json.dumps(summary))
    return 0 if report.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
