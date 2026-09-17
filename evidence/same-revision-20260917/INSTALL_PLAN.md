# Reviewed source installation plan — not executed

Source parent: `bc71a91bff31a092aae003e061622878b8ef4bf6`.
Source changes: `../CHANGED_FILES.json`; independent review:
`../C13_REVIEW.json`. Manifest canonical SHA256:
`630778703ee73dcd2816fa41ab78cfaac9e998543cfdbc8d95a976e5a0febbf8`.

1. Publish the exact `TREE_ELEMENTS.json` bytes as an independent Draft PR and
   bind the immutable commit to the reviewed file hashes. Keep the source parent
   and installed-byte lineage explicit. PR188 diagnostic source stays separate;
   it is neither overwritten nor installed in this operation.
2. Transfer reviewed `install_source.py` and `SOURCE_PACKAGE.json` through the
   existing operator channel. Independently verify their local and remote hashes.
   The installer accepts no arbitrary target list: its ten source paths and the
   exact manifest digest are fixed. Do not reconstruct the package from a branch
   tip or edit the manifest to get around a moved-baseline refusal.
3. Run the installer in `--check` mode on `hk-staging` and `go-cc`. Check mode
   writes nothing. Current source metadata, protected authority/configuration
   hashes and active timers must match; a running service yields BUSY_NO_CHANGE.
   Wait for normal completion instead of terminating an in-flight TEST_PR.
4. Apply `hk-staging` first, then `go-cc`, with the exact reviewed package. Each
   application temporarily stops only the applicable scheduling timers, checks
   idle state again, preserves before-images and permissions, replaces fixed
   source files and verifies imports and module pins. Existing source ownership,
   permissions, signing keys, authority files, ledgers, systemd definitions,
   deployment switches, database and business containers are not modified.
5. Read the root-owned receipt and final source hashes. A failed replacement
   restores every before-image; only a fully verified installed or restored source
   state permits timer restart. Incomplete restoration leaves scheduling stopped
   and records RECONCILIATION_REQUIRED. Do not issue any Request in that state.

This step installs source only. It does not register the new candidate, alter the
active candidate or current VERIFY baseline, create a deployment plan, dispatch
a Task or deploy the business image. Reviewed candidate-fact admission remains a
separate operation, derived from the exact signed TEST_PR, artifact/source and
both image graphs. Only then use the established formal Request chain.

Validation limits: 173 core tests and 3 installer tests passed independently.
Installer tests use real temporary files and injected replacement/restoration
failures; host commands are mocked. No live install is claimed by these tests.
