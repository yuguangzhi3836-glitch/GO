# Canonical Node toolchain overlay

This separately restorable supplement binds to source commit c6ea4dd670db36e71f3839fb31e656a5c8806858 and application tree 995d0d83faf883bec980c896fe8a17b0f12360fa. The 1332-file canonical application archive is unchanged. Generated binaries and NODE_MANIFEST.json are an explicitly separate overlay, not additional canonical source files.

Build extracts the fixed source into a temporary directory and runs its unchanged r317_provision_node_toolchain.sh and r82_gate_toolchain_integrity.py. The existing NODE_SOURCE.json pins official Node v22.22.0 linux-x64 and its archive SHA256. PATH places the sealed Node first. Ubuntu 22.04 hosts the gate, whose GLIBC ceiling is 2.35. The original downloaded archive, generated manifest, complete overlay file/link inventory, source fingerprints and raw logs are retained. Relative Node symlinks are allowed only when confined to regular archive members; escaping links and symlink parents are rejected.

An independent job validates and restores the same package, verifies the original upstream archive and overlay bytes, and reruns the existing gate with the restored Node. It does not download or reprovision Node. No Docker business image is changed, no application regression is repeated, and no Hong Kong operation occurs.

Local checks: `python3 -B -m unittest discover -s packaging/canonical-node-seal -p 'test_*.py' -v`.

Actual toolchain and restore status must come from CI. Node-toolchain PASS_SCOPED alone is not full release, native/device acceptance, business journey acceptance or deployment permission. Full release and Production remain HOLD.
