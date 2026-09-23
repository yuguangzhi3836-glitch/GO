# Owner registration exception — isolated acceptance record

Change class: CONTROL_PLANE / TEST_ONLY / DOCUMENTATION. Candidate only, not installed authority.

## Fixed source and decision

- PR #238 pre-exception head: `a8a1191e8693581bdaf58557313265be75fbe4fa`
- Path: `control-plane/c14-receipt-verifier-v1/C14_REGISTRATION_TO_SIGN.v2.json`
- Blob: `74dc7c9c6cf2da66541876d3de9c9a0549702257`
- Bytes: 621; SHA-256: `07ba520cfb1d782011f6b21a7582b29fd73af68524db9d4c892370475876b6a3`
- Signed envelope: [PR #238 comment 5791654074](https://github.com/yuguangzhi3836-glitch/GO/pull/238#issuecomment-5791654074).
- Mode: `OWNER_SINGLE_PERSON_EXCEPTION`. Owner has project-level signature rights to both key versions. No independent signer-identity or strict IAM-separation claim.

## Offline checks performed in scratch (2026-09-23)

`python3 -m pytest -q c14/tests`: **20 passed**. Includes positive synthetic P-256 registration and receipt cases and negative key, fingerprint, signature, source, exception declaration, receipt field, binding and freshness cases. The fixed source bytes were separately read and checked: 621 bytes with the SHA-256 above. `python3 -m compileall -q c14` passed. All keys used by the tests were ephemeral. No KMS signing or host activation occurred.

## Required isolated host check

An independent reviewer must obtain the **actual authority version 1 public key** via trusted host-side KMS read-only process, pin its SPKI SHA-256 to `87eb0ab66bd2e1f02331b2bb402ee214194b5f186c381222f9b7edd16c29dc7f`, obtain the immutable file bytes from the fixed commit/path and signed envelope from the archived PR comment, and invoke `verify_owner_registration_exception.py` with all explicit source bindings and `--exception-mode OWNER_SINGLE_PERSON_EXCEPTION`. The program returns `REGISTRATION_VERIFIED_ONLY` on success; every other mode, wrong byte, blob, path, commit, signature, authority public key or fingerprint must fail. Store the isolated command/result, reviewer identity, KMS effective IAM and impersonation checks, and evidence hashes outside this PR as signed evidence.

The isolated host and its independent reviewer are not available in this scratch workspace. The real signed object has **not** been verified by this gate on that host. The earlier independent OpenSSL verification is recorded in the archived PR comment; it is a separate check.

## Real signed-object offline check (2026-09-23)

The Owner supplied the authority version 1 public PEM copied from a read-only Cloud Shell `get-public-key` command. Its SPKI DER SHA-256 was independently calculated here as `87eb0ab66bd2e1f02331b2bb402ee214194b5f186c381222f9b7edd16c29dc7f`. Using the fixed commit's file bytes, archived signed envelope, and this PEM, `verify_owner_registration_exception.py` returned `REGISTRATION_VERIFIED_ONLY` with fixed commit `a8a1191e…`, blob `74dc7c9c…`, and SHA-256 `07ba520c…`. Five negative checks against the real artifact rejected wrong exception mode, path, bytes, signature, and public key. The public PEM's KMS origin is based on the Owner's Cloud Shell transcript, not an independently witnessed retrieval. This check ran in local scratch, **not** on the independently controlled isolated host. It is not evidence of effective IAM or signer separation.

## Still HOLD

The registration check does not prove receipt-signing isolation, replay control, audit completeness, authority installation or C14 execution. The isolated signer/receipt/replay/permission/audit suite, independent review and installation decision remain outstanding. C14/C13 PASS, merge, deployment, HK and Production remain HOLD.
