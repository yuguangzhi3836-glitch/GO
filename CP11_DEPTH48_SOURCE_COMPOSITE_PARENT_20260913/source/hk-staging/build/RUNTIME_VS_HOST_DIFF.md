# Runtime vs current host build-context drift

Inventory compared the 577 build-input paths copied from the running API image with the 577-file current host build context.

- Common paths: `577`
- Byte-identical: `576`
- Different: `1`
- Host-only paths: `0`
- Runtime-only paths among build inputs: `0`

The only differing path is:

`src/go_hotel/connectors/aoluguya_test.py`

SHA-256 in the **running image**:

`b95238be899865e971a7fd0e023eef7dfe2713e41f25dc79b1571626db96767f`

SHA-256 in the **current host release directory**:

`55199c80591a45d882c145bd987af94b6e11cab5fc331454de3115e93bb31720`

The running business image was created at `2026-09-06T12:11:13.978020567+08:00`. The host-side `aoluguya_test.py` observed during inventory had a later filesystem modification time (`2026-09-06 15:47:20 +0800`). `R31_5_FIX_BINDING_MANIFEST.json` describes a later binding fix that includes this path. The time alignment is evidence of later host-side change, but this archive does **not** claim a causal history beyond the observed files/metadata.

For current runtime truth, `source/runtime/src/go_hotel/connectors/aoluguya_test.py` is authoritative to the observed running image. The host-side variant is retained separately under `build/host-drift/` and must not be silently substituted for the live-image source.
