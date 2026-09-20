# C14 P-256 receipt contract v1

Draft control-plane contract. It authorizes **nothing**: no C14/C13 execution,
Runner registration, dispatch, deployment, Hong Kong, provider, payment,
secrets, or Production.

## Independent trust boundary

The issuer private key remains outside GitHub and this repository in the
independently controlled HSM/KMS. The verifier accepts only a P-256
(`secp256r1`) PEM public key and a pre-registered lowercase
`sha256:<SHA-256(SPKI-DER)>` fingerprint, both read from the root-owned host
trust store. Neither is accepted from a receipt, PR, workflow, task or Runner.

## Envelope

```json
{"receipt":{"schema":"go.c14.receipt.v1","receipt_id":"immutable-id","gate":"C14","candidate_sha":"lowercase 40/64 hex","application_tree":"lowercase 40/64 hex","verdict":"PASS","issuer":"independent-c14-host-identity","issued_at":"2026-09-20T12:00:00Z","evidence_manifest_sha256":"lowercase 40/64 hex"},"signature":"base64url(DER ECDSA-SHA256 signature)"}
```

Exactly those fields are permitted. The signature covers `receipt` alone,
serialized as UTF-8 JSON with lexicographically sorted keys, comma/colon
separators, no whitespace, floats, NaN or Infinity.

## Fail-closed gate

Verification succeeds only when: key parses as P-256; SPKI fingerprint exactly
matches host configuration; all envelope fields, digests and UTC timestamp are
valid; receipt age is 0–900 seconds (with at most 60 seconds future skew); and
ECDSA SHA-256 validates; and the verifier receives exact expected candidate SHA,
application tree, verdict, issuer and evidence manifest as required arguments.
Every mismatch is `VERIFY_FAIL`; a verified receipt is not authorization to
execute C14 or C13.
