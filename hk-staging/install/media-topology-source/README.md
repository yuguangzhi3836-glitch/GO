# Local source-install preparation

UNSEALED. No remote operation was performed. The installer rejects PENDING_FRESH_MANIFEST before any install lifecycle begins. The preflight is independently reviewable and takes only a pinned host role, never arbitrary paths.

Inputs needed before sealing: final source bytes, current INSTALL_TARGETS.json, newly captured fixed-file/ancestor observations on both hosts, and independent review. Nine existing target hashes must match declared before hashes; the one new media_topology_runtime.py target must be absent. If it exists, reconcile rather than silently overwrite. Metadata comes from observations, never from a guessed uid/mode.

Construct the manifest from these exact ten targets and remaining fixed files as unchanged guards; derive guard ancestor pins from actual observations. Preserve source bytes and loader pins from the final reviewed candidate. New helper installs root:root0644 via the inherited new-file branch. Keep old source permissions and ownership. Seal the canonical manifest digest into a new final installer; retain this PENDING template. Re-run fault and new-file rollback tests and complete independent review before any execution.

The installer is source-only: no Compose/mount/cache provisioning, contract admission, task dispatch, signature/authority change, or application recreation. Separate reviewed runtime transition preparation is owned by the fix agent/root. The original installer lifecycle is retained, including backup fsync, best-effort complete rollback, and timers held when reconciliation is required. Hostname validation is added to main.

PREPARATION.json records the current INSTALL_TARGETS digest and template hashes; detect any later source freeze change before sealing. LOCAL_TEST.log records thirteen passing inherited lifecycle/hash-only tests, not a final installation approval.
