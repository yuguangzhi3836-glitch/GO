# PR archaeology ledger — GO

## Audit frame

- Repository: `yuguangzhi3836-glitch/GO`
- Default branch at task start: `main`
- Task-start `main` HEAD: `1d8bebac37fcc6f0360b17891aa49eb6e70b5f96`
- Highest PR number at task start: `#40`
- `#1` is an Issue, not a pull request. Earliest PR is `#2`.
- Product lineage author: `yuguangzhi3836-glitch`.
- Operational/archive author: `chenzhenxi1-sudo` on #5, #9, #38, #39, #40.

This ledger classifies all PRs #2 through #40. PR descriptions were not trusted as PASS by themselves: critical decisions were cross-checked against candidate identity, source fingerprints, actual workflow outcomes where material, permanent evidence, and the sealed DEPTH40 artifact. A green workflow that only collected failure evidence is explicitly classified as failure where applicable.

## Complete PR ledger

| PR | Author | State at audit | Base / fixed candidate | Product/CI facts | Classification | Lineage disposition |
|---:|---|---|---|---|---|---|
| #2 | yuguangzhi3836-glitch | open draft | `main@6f379eff...`; head `048c939d...`; starts from DEPTH09 archive | 119 commits / 78 changed files; Hyatt directory + durable lease/ACK foundation; release gates remained HOLD | PRODUCT_CHANGE | earliest PR; continues DEPTH09 product lineage |
| #3 | yuguangzhi3836-glitch | open draft | base `deliverables/cp11-depth28-v14-integration@6c85c64...`; acceptance head `30de597d...` | restores DEPTH26→27→28; 1093 fingerprints; CI 34343745354; frontend 135/135 | ACCEPTANCE_ONLY | validates DEPTH28; no product semantics added |
| #4 | yuguangzhi3836-glitch | open draft | DEPTH29 candidate `0451fb09...` | 1207 files; tree `ffcea37a...`; CI 34352506603: Python 171 + Node 158 pass | ACCEPTANCE_ONLY | validates DEPTH29 |
| #5 | chenzhenxi1-sudo | merged | main | HK deploy runbook/operation contract only | DOCUMENTATION, INFRASTRUCTURE | not product lineage; retained in main |
| #6 | yuguangzhi3836-glitch | open draft | DEPTH30 candidate `c495ca65...` | 1222 files; tree `f576c976...`; CI 34372130831: Python 172 + Node 194 pass | ACCEPTANCE_ONLY | validates corrected native payment/refund source |
| #7 | yuguangzhi3836-glitch | open draft | DEPTH30 `c495ca65...` | materialization/preparation only; no application execution or test rerun | PACKAGING_ONLY | no product change |
| #8 | yuguangzhi3836-glitch | open draft | DEPTH31 candidate `b1515916...` | 1232 files; tree `2b9095df...`; isolated change/refund/Direct validation | ACCEPTANCE_ONLY | validates DEPTH31 |
| #9 | chenzhenxi1-sudo | merged | main | documents HK Agent 60-second systemd polling | DOCUMENTATION, INFRASTRUCTURE | not product lineage |
| #10 | yuguangzhi3836-glitch | closed unmerged | DEPTH32 `51c95e62...` | CI 34427342231: 181 backend pass, **6 fail**; frontend did not run; wrong constrained table for FLIGHT | FAILED, SUPERSEDED | excluded; corrected by #11 |
| #11 | yuguangzhi3836-glitch | open draft | DEPTH32R2 `1289e9c3...` | 1236 files; tree `a309bdda...`; CI 34427905965: 187 backend + 224 frontend/native pass, no fail/error/skip | PRODUCT_FIX, ACCEPTANCE_ONLY | retained; supersedes #10 |
| #12 | yuguangzhi3836-glitch | open draft | DEPTH33 `ea2a51...` | 1239 files; tree `a67a70...`; CI 34432816747: Python 237 + frontend/native 224 pass | PRODUCT_CHANGE, ACCEPTANCE_ONLY | retained in later lineage |
| #13 | yuguangzhi3836-glitch | closed unmerged | DEPTH34 `ab9f3951...` | CI 34433623433: **5 backend fail**, 4 pass; missing `SessionLocal`; frontend did not run | FAILED, SUPERSEDED | excluded; corrected by #14 |
| #14 | yuguangzhi3836-glitch | open draft | DEPTH34R2 `2dab5377...` | 1241 files; corrected missing import; CI 34434039448 affected backend + frontend/native pass | PRODUCT_FIX, ACCEPTANCE_ONLY | retained; supersedes #13 |
| #15 | yuguangzhi3836-glitch | closed unmerged | DEPTH35 `0dd0bdca...` | 1243 files; first independent run: 36 backend pass + **2 CookieConflict fixture fail**; frontend did not run | FAILED, SUPERSEDED | excluded; corrected by #16 |
| #16 | yuguangzhi3836-glitch | open draft | DEPTH35R2 `a758f4...` | 1243 files; CI 34440381225: backend 38 + frontend/native 239 pass | PRODUCT_FIX, ACCEPTANCE_ONLY | retained; supersedes #15 |
| #17 | yuguangzhi3836-glitch | open draft | initial DEPTH36 | full suites: 1654 pass, **19 fail**, 6 skip; other packaging/loopback checks passed | FAILED | not final; repair chain continues |
| #18 | yuguangzhi3836-glitch | open draft | scoped DEPTH36 auth repair `5040b2...`; application source semantics otherwise unchanged | CI 34449749729: 40 scoped tests + packaging/http checks pass | PRODUCT_FIX, ACCEPTANCE_ONLY | intermediate; not sufficient as full final candidate |
| #19 | yuguangzhi3836-glitch | open draft | DEPTH36R2 `32712e...` | 1267 files; run 34451882079: 1668 pass, **5 fail**, 6 PG-only skip | FAILED, SUPERSEDED | excluded; corrected by #20 |
| #20 | yuguangzhi3836-glitch | open draft | DEPTH36R3 `7bd98db2...` | 1267 files; tree `c58edb0...`; CI 34453179558: **1673 pass, 0 fail/error**, 6 PG-only skip; packaging/loopback/source verify pass | PRODUCT_FIX, ACCEPTANCE_ONLY | latest corrected DEPTH36 base retained downstream |
| #21 | yuguangzhi3836-glitch | open draft | unchanged DEPTH36R3 | readiness / sealed Node/native probe; proposed outputs not product-source authority | ACCEPTANCE_ONLY, PACKAGING_ONLY | no application semantic change |
| #22 | yuguangzhi3836-glitch | open draft | original DEPTH37 native/provider candidate `cb81f9...` | native build compiled, but later device startup evidence disproved readiness | PRODUCT_CHANGE, FAILED, SUPERSEDED | excluded original native implementation |
| #23 | yuguangzhi3836-glitch | open draft | same original DEPTH37 lineage | evidence collection showed actual iOS blank startup after 60s / missing ExpoAsset; workflow success meant evidence collection, not product pass | EVIDENCE_ONLY, FAILED | preserves failure; does not validate candidate |
| #24 | yuguangzhi3836-glitch | open draft | DEPTH37R2 `da689770...`; 1276 files; tree `cf3f139...` | corrects ExpoAsset/autolinking/startup path; subsequent lineage proceeds from corrected product state | PRODUCT_FIX, ACCEPTANCE_ONLY | retained; supersedes #22/#23 failure |
| #25 | yuguangzhi3836-glitch | open draft | DEPTH37 readiness | supplier input preflight found 8 required canonical inputs empty; external calls remained 0 | ACCEPTANCE_ONLY | source not failed; external-resource readiness HOLD |
| #26 | yuguangzhi3836-glitch | open draft | DEPTH37R2 | disposable PostgreSQL acceptance for race/transaction checks | ACCEPTANCE_ONLY | validation supplement, not source candidate |
| #27 | yuguangzhi3836-glitch | open draft | P0 Universal Agent Gateway `bdb20a03...` | deterministic Agent Gateway product overlay; transaction truth across protocol surfaces | PRODUCT_CHANGE | retained; starts late P0 product line |
| #28 | yuguangzhi3836-glitch | closed unmerged | P0 base `bdb20a03...` | first acceptance tooling/path attempt did not become final accepted run | ACCEPTANCE_ONLY, FAILED, SUPERSEDED | acceptance mechanics superseded by #29; product itself not discarded |
| #29 | yuguangzhi3836-glitch | open draft | P0 `bdb20a03...` | corrected acceptance run 34546875079; 13 Agent truth + 12 native regressions = 25 pass | ACCEPTANCE_ONLY | validates P0 feature |
| #30 | yuguangzhi3836-glitch | open draft | P0.2 `b977e2d1...` | isolated acceptance around transaction lifecycle candidate | ACCEPTANCE_ONLY | validation support for #31 |
| #31 | yuguangzhi3836-glitch | open draft | P0.2 `b977e2d1d3afd35bb3d39c2e0df0dedd2e4e33d3` | lifecycle/aftersales/idempotency product changes; run 34552701811: 71/71 scoped checks pass | PRODUCT_CHANGE | retained and parent of P0.3 |
| #32 | yuguangzhi3836-glitch | open draft | P0.3 `e0742e2168b9a0fc0c1d6391f767c3219efb5e97`, based exactly on P0.2 | hotel hard-hold release, ride/rental expiry, Apple AppIntents; Xcode simulator run 34555752235 PASS; backend fresh restore 34555752258 PASS (11/11 + 6/6 sentinel); physical iPhone HOLD_EXTERNAL_DEVICE_RUNNER | PRODUCT_CHANGE, PRODUCT_FIX | **latest semantic product head retained** |
| #33 | yuguangzhi3836-glitch | open draft | DEPTH40 sealed P0.3 parent; head `c909af37...` | build 34557878180 success; artifact 10183252130; 1271 files; source tree `64f5d78a...`; independent zero-restore run 34558059579 success | PACKAGING_ONLY, ACCEPTANCE_ONLY | **selected sealed product source package** |
| #34 | yuguangzhi3836-glitch | closed unmerged | fixed DEPTH40 artifact 10183252130 | run 34558059579 success; package/checksums/zero restore/compile/frozen deps/17-of-17 P0.2+P0.3 regressions pass | ACCEPTANCE_ONLY | validates selected package; no product change |
| #35 | yuguangzhi3836-glitch | open draft | fixed DEPTH40 source unchanged | isolated image/package review | PACKAGING_ONLY, ACCEPTANCE_ONLY | runtime supplement only |
| #36 | yuguangzhi3836-glitch | open draft | fixed DEPTH40 1271-file source unchanged | CI 34565938702: PG16 migration to 0132 + Redis/eight-service checks **20/20 PASS**; offline image; HK mapping HOLD | PACKAGING_ONLY, ACCEPTANCE_ONLY | deployment-readiness evidence; source unchanged |
| #37 | yuguangzhi3836-glitch | open draft | fixed DEPTH40 source unchanged | PR body initially PENDING; actual workflow 34571894075 completed SUCCESS including PG18.4 upgrade/recovery step | ACCEPTANCE_ONLY | compatibility/recovery supplement; source unchanged |
| #38 | chenzhenxi1-sudo | merged | main | final proven HK operations documentation | DOCUMENTATION, INFRASTRUCTURE | not product lineage |
| #39 | chenzhenxi1-sudo | merged | main | archives observed GO Command Center source/config; secrets excluded | INFRASTRUCTURE, DOCUMENTATION | not product lineage; preserved in current main |
| #40 | chenzhenxi1-sudo | merged | main@11ee1568...; merge commit is task-start main `1d8bebac...` | archives observed 2026-09-11 HK runtime: 577 files, source manifest `2c2606...`, image `go-hotel:aoluguya-direct-r3-1-20260906`; no mutation/deploy/migration | INFRASTRUCTURE, DOCUMENTATION | operational baseline used for relationship comparison, not product candidate |

## Earliest product baseline

PR #2 is the earliest PR. Its base is `main@6f379eff8d63c123b2bd57d504ab6520f6ffc575` and its body explicitly starts from the DEPTH09 archive lineage. DEPTH09's own manifest identifies source tree `1c92d5d79c48a58a5194a57fbd61e395156e5b710bfe2e27e171a9b3d50c43bd`, `deployed=false`, with release gates HOLD.

Therefore the earliest PR should **not** be described as “the currently deployed HK version.” It is an archived product-development lineage that shares partial source ancestry with the later recovered HK runtime baseline.

## Latest validated product candidate

The latest semantic product head is P0.3 `e0742e2168b9a0fc0c1d6391f767c3219efb5e97`. The latest sealed, independently recoverable representation of that product is `CP11_DEPTH40_P03_PARENT_20260911`, built at `c909af370d55ce7644140a191425a8a66dacec9a` with source tree `64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667` and 1271 files.

This consolidation materializes that exact file set under `application/`; it does not merge historical PRs or mix acceptance/packaging branch code into the product root.