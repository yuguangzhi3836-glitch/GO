# C14 P-256 receipt verifier — Draft only

This is an offline, fail-closed verifier for receipts signed by the independently
controlled HSM P-256 issuer. It accepts only the host-owned P-256 public key
and pre-registered SPKI SHA-256 fingerprint, then returns a verified receipt
summary.

It contains no private key, Runner registry, signing action, dispatch, network,
Hong Kong, provider, payment, secret, deployment, or Production capability.

See `C14_RECEIPT_CONTRACT_V1.md` and `HOST_TRUST_CONFIGURATION.md`.
