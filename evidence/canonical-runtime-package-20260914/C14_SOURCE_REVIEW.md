# C14 canonical runtime packaging source review

Review date: 2026-09-14. Reviewer: independent C14 runtime-package agent.

Result: SOURCE_REVIEW_PASS_SCOPED. This is a source and packaging-safety review, not a successful Docker build, restore, Sealed Node, release, or deployment receipt. Runtime CI has not been observed by this reviewer.

## Source binding

- Fixed source commit: `c6ea4dd670db36e71f3839fb31e656a5c8806858`.
- Application Git tree: `995d0d83faf883bec980c896fe8a17b0f12360fa`.
- Application source SHA256: `1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4`; 1332 files.
- Builder extracts application and deployment definitions from the fixed Git commit; HEAD application-tree equality prevents hidden business-source changes.
- The three deployment-contract Git blob constants were independently compared with the fixed commit's recursive Git tree and match exactly: README `6ff3ba8863c40b991d748c2b6572402a776ff89d`, environment contract `e14134d44c14328533108802354e7c887818376e`, Compose `32f947b5c48344aa75e6381408fb20cef173480a`.

## Reviewed bytes

| Path | SHA256 |
| --- | --- |
| packaging/canonical-runtime/package.py | 6b1204d4317c1082cc1852c0d7d07fef116ea58b26a2b57fd40a4558baa82c94 |
| packaging/canonical-runtime/test_package.py | 09bb4cef520d8c9e197294d2a3e9e072d9983783183e554cb03bdc7ea755b0e0 |
| .github/workflows/canonical-runtime-package.yml | e4dda30cff0a37fecd8bd9b5fb4d5ad12e537d8504a5fd6a96850f1ef3048f54 |

## Findings and closure

The initial extractor accepted two archive members `a/b` and `a/./b` targeting the same destination. Independent temporary-file reproduction returned `ALIAS_DUPLICATE_ACCEPTED last`. This defect is closed in the reviewed bytes: names are canonicalized with PurePosixPath, normalized duplicates and empty/root paths are rejected, and file-as-parent collisions are rejected before extraction. Absolute paths, traversal, links, devices, and exact duplicates remain rejected.

Deployment-contract replacement is rejected using independently verified fixed Git blob hashes at both build and restore. Package, source-fingerprint, and per-file checks precede Docker load. The Docker archive records every regular member's size and SHA256 and proves the expected image config bytes exist. Restore checks the resulting tag's actual config ID against the candidate and runs the image by that ID.

Build resolves and records the actual Python base image before building without another pull. Installed dependencies and complete image inspect are recorded; dependencies remain floating at build time and are explicitly not claimed frozen. The workflow uses the PR head, read-only contents permission, no persisted checkout credentials, a separate restore job, matching named artifacts, and retained failure logs. Restore loads the original saved image rather than rebuilding it.

The smoke container uses network none, an ephemeral `/tmp/probe.db` SQLite database, and executes the original image CMD after an isolated Alembic initialization. This does not run a migration against Hong Kong or PostgreSQL. Worker module imports, source hashes, health, and OpenAPI are appropriate limited smoke assertions; they do not prove worker liveness or business journeys.

## Independent local validation

Executed `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s GO/packaging/canonical-runtime -p 'test_*.py' -v`: 6 tests passed, 0 failures, 0 errors. Cases cover ordinary extraction, malicious archive members including normalized aliases and parent collisions, substituted deployment contracts, wrong source, and package corruption rejected before Docker. No Docker command or Hong Kong action was executed in this review. No existing application CI was repeated.

## Outstanding gates

- Actual Docker build and independent offline restore: NOT_OBSERVED, awaiting CI originals and candidate/package/image binding.
- Sealed Node: HOLD. Canonical Dockerfile is a Python runtime; it does not provide the pinned Node v22.22.0/linux-x64 binary, full toolchain hash, GLIBC compatibility, and PATH-integrity evidence required by the separate toolchain contract.
- Full release and deployment: HOLD / NOT_RUN. Limited image smoke cannot satisfy all four release gates or replace signed CANARY, fresh VERIFY, an approved signed plan, and runtime receipts.
- A real registry digest must be observed; none may be invented from the config ID. The existing deployment contract's equality restriction remains a separate compatibility concern.
- CURRENT_HK_RUNTIME is not modified by packaging success. Hong Kong remains on its separately recorded DEPTH48 runtime; Production remains HOLD.

No further must-fix source finding remains within this packaging review scope. Any change to the reviewed files requires review of the delta; actual CI outcomes must be recorded separately.

## Follow-up: first CI failure and canonical cache exclusion correction

The preceding reviewed-byte table is retained as the initial review identity. The current `package.py` SHA256 is `9051ccdf05656117df1d6d950312e8d76229454facda5dc013c0927a215155c9`; test and workflow hashes remain unchanged. This delta receives SOURCE_REVIEW_PASS_SCOPED only.

Independently retrieved GitHub run `34795009463`, build job `103826275178`, and its decoded original log. Six safety tests passed; Docker exported image `sha256:f1c2446318a46552e5b39dead182548b550d85dd9ad84cbac9dbf03cef6f0bd1`. The subsequent image-content check failed with FileNotFoundError for `/app/.pytest_cache/.gitignore`. The build job concluded failure and independent restore job `103826477238` was skipped. This is an image-build success within an unsuccessful packaging job, not PACKAGE or RESTORE PASS.

The immutable Git tree independently confirms exactly four tracked cache files: `.pytest_cache/.gitignore`, `.pytest_cache/CACHEDIR.TAG`, `.pytest_cache/README.md`, and `.pytest_cache/v/cache/nodeids`. Canonical `.dockerignore` excludes `.pytest_cache`. Their absence is expected runtime packaging behavior, not missing business source.

The correction introduces a closed set of these four exact paths. Full source archive and source SHA validation remain 1332 files with the same fixed digest. Image verification checks all remaining 1328 source files and separately asserts that each of the four cache paths is absent. No wildcard exclusion, business-file exclusion, source mutation, Dockerfile change, or gate bypass is introduced. Both initial build and independent restore use this corrected check.

The README explicitly separates 1332 archived source files from 1328 image source files. Existing archive-safety tests and earlier results are inherited; this reviewer did not repeat them for the cache-check delta. A successful rerun and independent restore receipt are still required. The failed run remains historical evidence; its image ID is not automatically the next candidate's identity. Sealed Node, full release, Hong Kong deployment, and Production conclusions remain unchanged.
