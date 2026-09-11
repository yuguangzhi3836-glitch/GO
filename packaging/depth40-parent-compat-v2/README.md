# DEPTH40 P0.3 Compatibility V2 — consolidated parent

New parent ID: **CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912**.

This is the single self-contained successor package for the compatibility repair. It includes the complete 1271-file business source, the exact already-tested repaired offline image, executor source and manifest, review Compose, engineering tools and original compatibility evidence. No previous artifact, restore chain, overlay or network connection is needed to verify or restore the downloaded package.

The frozen `CP11_DEPTH40_P03_PARENT_20260911` is preserved. Business source is unchanged: tree SHA256 `64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667`. This new aggregate ID does not rename the business candidate inside the tested image or Compose. Runtime identity is **sha256:cba95a5ac6f061b8196f953f181952fdad94ab520a12cbeb0e7ee49d9a6de150**, from compatibility run **34642554667**, commit `d49465a56a7768bc4e657858272a597c5d1f05d6`. The image is copied byte-for-byte; it is not rebuilt or retagged.

## Package contents

| Path | Contents |
|---|---|
| `application/` | Complete canonical business source at fixed commit `b5732c02dd95092a63def7eaa0d2cf332b1e2996` |
| `runtime/` | Exact verified compatibility artifact files, including the offline image, executor, Compose review contract, raw unit log, PostgreSQL probe, source check and original SHA256SUMS |
| `engineering/` | Compatibility repair source, build/verification utilities and test code; not an installed executor |
| `provenance/` | Canonical source manifest plus independently archived raw CI logs and review from `f4f32cb9230c473471c736840da3f1d552e5ac43` |
| `PARENT_MANIFEST.json`, `PINS.json` | Aggregate identity, separate business/runtime lineage, exact component hashes, test scope and release state |
| `SHA256SUMS`, `verify_parent.py` | Complete file-set verification, image config verification and copy-only restoration |

## Offline verification and restoration

Use Python 3.11 or later and the published **inner parent ZIP SHA256** from the exact run's `PARENT_BUILD_REPORT.json`/`.sha256` file. The GitHub artifact wrapper has a different hash. Verify the external ZIP checksum before trusting tools extracted from it.

```sh
sha256sum -c CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912.zip.sha256
python3 -B verify_parent.py --zip CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912.zip --sha256 FULL_PUBLISHED_INNER_ZIP_SHA256
python3 -B verify_parent.py --zip CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912.zip --sha256 FULL_PUBLISHED_INNER_ZIP_SHA256 --restore-to /workstation/new-go-parent
```

The destination must not exist. Restoration only copies files: no Docker load/run, application execution, dependency installation, database access, migration or network connection occurs. Existing destinations, unsafe archive paths, symlinks, extra/missing files, altered source bytes and mismatched image/executor identities are rejected. Checksums establish integrity relative to the externally published ZIP hash; they are not a deployment signature.

The packaging job downloads a fixed GO artifact and checks out two exact GO commits. It verifies all component checksums, source identity, executor bytes, image archive and config ID; then validates both directory and ZIP restoration. It does not rerun previously passed application suites. The delivery artifact is retained for 90 days; preserve the downloaded parent ZIP and checksum for long-term offline retention. Packaging source and the permanent run index live in GO.

## Acceptance and remaining site work

The integrated repairs cover the reviewed Compose/command and Alembic-path mismatch, config ID vs RepoDigest handling, recorded-image rollback checks, failed-deployment recovery preparation guard and PostgreSQL critical-column type validation. See `engineering/README.md` for the exact implemented behavior and limits.

The 34 compatibility tests use a simulated Docker command runner; the PostgreSQL 18.4 type-guard probe is real and isolated. Historical 20-service-startup and 25-upgrade/recovery checks retain their original source/environment scope. They are not combined into a new end-to-end PASS.

`SITE_BINDING=UNBOUND`, `INSTALLED_IN_HK=NO`, `HK_EXECUTION=NOT_RUN`. The executor deliberately cannot execute a real action until a separately approved site package binds the exact configuration, image identities, database compatibility and recovery evidence. This aggregate does not supply live credentials, keys, signed Tasks, migration authority or automatic recovery. RepoDigest remains unassigned. A site-ready deployment package still requires those actual inputs.

THREE-END REAL UX/LOGIN → SIX-VERTICAL REAL CLOSED-LOOP E2E → SEALED NODE → FINAL RELEASE remain HOLD. Production is excluded. This parent-package upgrade does not merge PR #42/#43, install TEST_PR, replay the expired VERIFY or switch Hong Kong services.
