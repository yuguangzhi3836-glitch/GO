# C14 receipt verifier — Draft only

This is an offline Ed25519 receipt verifier. It accepts a public key and its
fingerprint from a separately controlled host trust boundary, verifies a
canonical receipt, and returns only a verified receipt summary.

It contains no private key, Runner registry, signing action, dispatch, network,
Hong Kong, provider, payment, secret, deployment, or Production capability.
