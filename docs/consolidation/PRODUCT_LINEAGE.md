# GO product lineage consolidation

## Scope and fixed facts

This document is a source-history reconstruction only. It does not authorize merge, deployment, migration, HK runtime mutation, or Production action.

- Repository: `yuguangzhi3836-glitch/GO`
- Default branch: `main`
- Task-start `main` SHA: `1d8bebac37fcc6f0360b17891aa49eb6e70b5f96`
- Highest PR number at task start: `#40`
- There is **no PR #1**. Repository number `#1` is an open Issue. The earliest pull request is PR `#2`.
- Boss/product author identity: `yuguangzhi3836-glitch`.
- `chenzhenxi1-sudo` PRs #5, #9, #38, #39 and #40 are operations/documentation/archive history and are not product-feature lineage.

## Lineage conclusion

The historical product source is not a single normal Git branch. Multiple generations were stored as archives plus deltas/overlays, then independently restored and tested. PR number order therefore cannot be used as ancestry.

The strongest validated software lineage reaching the selected source is:

```text
HK archived runtime source (2026-09-11 observation; 577 files)
        |  content overlap with older application baseline; not a Git commit
        |  PARTIAL_ANCESTRY only (not strict whole-tree ancestry)
        v
pre-DEPTH09 application baseline
        |
        +-- DEPTH09 source tree
        |      1c92d5d79c48a58a5194a57fbd61e395156e5b710bfe2e27e171a9b3d50c43bd
        v
PR #2 / DEPTH10 and later DEPTH archive chain
        v
DEPTH28 -> DEPTH29 -> DEPTH30 -> DEPTH31
        v
DEPTH32 FAILED (#10) -> DEPTH32R2 corrected (#11)
        v
DEPTH33 (#12)
        v
DEPTH34 FAILED (#13) -> DEPTH34R2 corrected (#14)
        v
DEPTH35 FAILED (#15) -> DEPTH35R2 corrected (#16)
        v
DEPTH36 initial FAILED (#17)
        -> scoped auth repair (#18)
        -> DEPTH36R2 still FAILED (#19)
        -> DEPTH36R3 corrected (#20; 1673 pass, 0 fail; PG-only skips retained)
        v
DEPTH37 native/provider work
        -> original native build/startup FAILED (#22/#23)
        -> DEPTH37R2 corrected (#24)
        v
P0 Universal Agent Gateway (#27; acceptance corrected by #29)
        v
P0.2 Transaction Lifecycle (#31)
        v
P0.3 Native Lifecycle Closure (#32)
        | semantic head e0742e2168b9a0fc0c1d6391f767c3219efb5e97
        v
DEPTH40 sealed P0.3 parent (#33)
        | build head c909af370d55ce7644140a191425a8a66dacec9a
        | 1271 files
        | source tree SHA256 64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667
        v
independent zero-restore acceptance (#34) PASS
        v
runtime/package/PG reviews (#35/#36/#37), source unchanged
        v
THIS CONSOLIDATION: application/
        | exact 1271-file materialization
        | same source tree SHA256 64f5d78a...
```

## Why DEPTH40 is the selected software source

`CP11_DEPTH40_P03_PARENT_20260911` is the latest source package that simultaneously satisfies the evidence needed for a canonical source baseline:

1. It binds the P0.3 semantic head `e0742e2168b9a0fc0c1d6391f767c3219efb5e97` to the preceding validated P0.2 lineage.
2. Its package identifies exactly 1271 source files and a deterministic SHA-256 tree digest.
3. Build run `34557878180` succeeded.
4. Artifact `10183252130` has ZIP SHA-256 `d0aa4b89ed0655271cf5ef7a12cce354dc8d84704cf57071f581f129458cbaf7`.
5. The embedded full source archive has SHA-256 `2909651f9b644ed56fd6ab833480c9da32b4c5b900df2e5afb192dba49ac2b00`.
6. Independent zero-restore run `34558059579` succeeded and revalidated package metadata, restore, compile, frozen dependency integrity and P0.2/P0.3 regressions (17/17).
7. Later PRs #35-#37 add packaging/runtime/upgrade evidence without changing this 1271-file source identity.
8. Physical iPhone execution remains an external-resource HOLD. That is not evidence that the software source failed.

## Canonicalization performed here

The historical package was used **once** to produce `application/`. During the GitHub-only materialization workflow:

- Artifact ZIP SHA-256 was checked before extraction.
- Package candidate identity, P0.3 commit, archive SHA-256, source-tree SHA-256 and file count were checked.
- `restore_parent.py` materialized the package into a new directory.
- all 1271 file paths and per-file SHA-256 values were checked against `SOURCE_FINGERPRINT.json`;
- the source was secret-scanned;
- all 1271 files, including the four candidate `.pytest_cache` files that are part of the sealed fingerprint, were force-added to Git so the canonical source remains byte-identical to the validated package.

After the resulting commit, a checkout of this branch contains the complete application source directly under `application/`. Historical artifacts, old PR branches, DEPTH restore scripts and overlay ordering are no longer required to obtain the application source.

## Selected identities

- `LATEST_VALIDATED_PRODUCT_CANDIDATE=CP11_DEPTH40_P03_PARENT_20260911`
- `LATEST_VALIDATED_PRODUCT_SHA=e0742e2168b9a0fc0c1d6391f767c3219efb5e97`
- `SEALED_PARENT_BUILD_HEAD=c909af370d55ce7644140a191425a8a66dacec9a`
- `CANONICAL_APPLICATION_ROOT=application/`
- `CANONICAL_APPLICATION_FILE_COUNT=1271`
- `CANONICAL_APPLICATION_TREE_SHA256=64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667`

## Authority boundary

This consolidation establishes source provenance only. It does not claim that the current live HK source equals the final candidate, does not claim a different-image HK deploy has been proven, and does not close deployment-stage, supplier, browser or physical-device gates.