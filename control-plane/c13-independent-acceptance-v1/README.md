# C13 repair candidate — Draft only

This candidate repairs the source-binding and trust-boundary defects found in PR #229. It has no Runner installation, signing key, dispatch, deployment, Hong Kong, provider, payment, secret or Production capability.

The fixed application identity is PR #217 candidate `0c3da07bc32009dee16c69125111f8e4ea9d546b` with its actual `application/` tree `f6d329352dd8484010036448810a927d5eec4be7`.

The source checkout holds no Runner registry and no C14 receipt. `derive_task` fails closed unless a separately reviewed host trust boundary verifies both: (1) a signed C14 PASS receipt bound to candidate/tree, issuer and digest; (2) an immutable host registration of exactly one independent C13 Runner. The production host adapter is intentionally not in this PR.
