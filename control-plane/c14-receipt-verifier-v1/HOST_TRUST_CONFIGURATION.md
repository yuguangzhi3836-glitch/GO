# Host trust configuration — C14 P-256 verifier

Draft preparation only. No receipt signing, Runner registration, dispatch,
C14/C13 execution, deployment, or Production access.

Create these host-owned files outside the checkout, owned `root:go-control`
(directory `0750`, files `0640`):

- `/etc/go-command-center/trust/c14-p256-public.pem`
- `/etc/go-command-center/trust/c14-p256.env`

```sh
GO_C14_TRUSTED_P256_PUBLIC_KEY_FILE=/etc/go-command-center/trust/c14-p256-public.pem
GO_C14_TRUSTED_P256_SPKI_SHA256=sha256:REPLACE_WITH_LOWERCASE_SPKI_DER_SHA256
GO_C14_RECEIPT_MAX_AGE_SECONDS=900
GO_C14_ALLOWED_ISSUER=REPLACE_WITH_INDEPENDENT_C14_HOST_IDENTITY
# The following are injected only from the fixed, read-only task binding:
# GO_C14_EXPECTED_CANDIDATE_SHA=...
# GO_C14_EXPECTED_APPLICATION_TREE=...
# GO_C14_EXPECTED_VERDICT=PASS
# GO_C14_EXPECTED_EVIDENCE_MANIFEST_SHA256=...
```

The host administrator exports only the existing HSM P-256 public key. A second
administrator compares its KMS key-version identity and SPKI fingerprint,
then records key-version URI, issuer, fingerprint, both operator identities,
timestamp and revocation contact outside GitHub. The verifier account may read
this public material only; it must have no signing, key-admin, decryption,
GitHub-write, Runner-registration or deployment permission.

Before any activation, record a fail-closed test matrix: wrong key/fingerprint,
malformed envelope, altered candidate/tree/verdict/signature, stale/future
timestamp, wrong issuer and wrong evidence-manifest binding must all return
`VERIFY_FAIL`. The verifier invocation must pass the five matching expected
bindings (issuer, candidate SHA, application tree, verdict, evidence digest).
The one valid synthetic receipt must be signed solely by the
independent issuer and verified by a separate operator. This remains short of
C14/C13 execution.

For the single-person registration exception, pin PR #238 comment `5791654074`
and the immutable source identifiers in `REGISTRATION_AUTHORITY_CONTRACT.md`.
The host verifier must load the actual KMS authority public key from a trusted
operator-controlled path, check its SPKI fingerprint, verify the exact signed
621-byte registration and record the exception mode. The Owner is authorized
at project scope for both KMS signing keys: an isolated public-key verification
does not prove IAM separation, receipt-signer permission isolation, replay
resistance or an audit trail. None of those checks may be inferred from the
registration signature. Do not activate a signer from this documentation.
