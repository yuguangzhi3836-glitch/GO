# C14 public trust registration (no secrets)

This package binds the C14 signer verifier to the existing HSM P-256 key. It
does not create a Cloud Run service, make an API call, authorize a runner, or
access Hong Kong, Production, payment, OTA, provider, repository, or C13.

## Immutable scope

- Project: `go-c14-trust-prod-509114`
- KMS key: `global/go-c14-receipts/go-c14-receipt-v1`
- Algorithm: `EC_SIGN_P256_SHA256`
- Service account: `go-c14-receipt-signer@go-c14-trust-prod-509114.iam.gserviceaccount.com`
- Allowed KMS role on this key only: `roles/cloudkms.signerVerifier`

## Registration procedure

1. A key administrator copies only the **version resource name** and the PEM
   public key from the KMS console. Never export, download, paste, or store a
   private key, token, JSON service-account key, OAuth credential, or KMS
   response containing credentials.
2. Compute the SHA-256 of the public key's DER SubjectPublicKeyInfo bytes. Put
   only that 64-character lowercase digest in the registration file.
3. Complete `C14_TRUST_REGISTRATION.template.json` as a new
   `C14_TRUST_REGISTRATION.json`, changing `state` to `VERIFIED` only after two
   different people independently compare: KMS version resource, algorithm,
   SPKI fingerprint, service account, and key-scoped role.
4. Each verifier records a stable non-secret identifier, role, UTC time, and a
   concise attestation of that comparison. The two identities must differ.
5. Run `python -m unittest discover -s tests -p 'test_c14_trust_manifest.py'`.
   The validator is intentionally offline and fail-closed. Commit the verified
   registration, its SHA-256, and the test output as evidence. Do not put an
   actual registration in this Draft until both verifiers have completed step 3.

`C14_TRUST_REGISTRATION.template.json` is deliberately invalid and cannot be
treated as evidence. This prevents a fabricated key version or fingerprint
from becoming a trust anchor.
