# Feature Retention Matrix

This matrix tracks major product capabilities through failed, corrected and superseding candidates. `application/` is an exact materialization of the sealed DEPTH40 P0.3 parent; no feature was reimplemented during consolidation.

| Capability | Earliest material candidate | Known failed/superseded stage | Corrected / later stage | Last software validation used | Present in canonical source | Final status |
|---|---|---|---|---|---|---|
| National/official hotel discovery and catalog/autopage replication | DEPTH09 → PR #2 DEPTH10 | early release gates remained HOLD | carried through later DEPTH lineage | DEPTH40 exact-source acceptance #34 plus final fingerprint retention | yes | RETAINED |
| Durable lease/ACK autonomous hotel task foundation | PR #2 DEPTH10 | no specific later code failure used to exclude it; initial real-runtime gates were HOLD | inherited through restored lineage | sealed DEPTH40 fingerprint + later runtime acceptance | yes | RETAINED |
| DEPTH28 V14 integration/frontend contracts | DEPTH28 | original direct checkout could not represent full runnable tree | PR #3 corrected restoration/acceptance | CI 34343745354, 1093 fingerprints and 135 frontend tests | yes, through later restore lineage | RETAINED |
| Trip/order re-entry and cross-end fact read | DEPTH29 | none recorded as product failure | PR #4 acceptance | CI 34352506603: 171 Python + 158 Node pass | yes | RETAINED |
| Native payment/refund truthful flow | DEPTH30 | prior native UI contained fixed payment/success/refund placeholders | DEPTH30 corrected product candidate; #6 acceptance | CI 34372130831: 172 Python + 194 Node pass | yes | RETAINED |
| Change confirmation, refund binding, Direct read-only | DEPTH31 | earlier hardcoded/change placeholder behavior | DEPTH31 corrected product candidate; #8 acceptance | isolated acceptance on 1232-file source | yes | RETAINED |
| Flight refund consent / native change terms | DEPTH32 | PR #10 candidate `51c95e...`: 6 backend failures; incompatible operation-table constraint | PR #11 DEPTH32R2 `1289e9...` | CI 34427905965: 187 backend + 224 frontend/native pass | yes | RETAINED |
| Mobility refund/lifecycle progression | DEPTH33 | none in that stage | PR #12 | CI 34432816747: 237 Python + 224 frontend/native pass | yes | RETAINED |
| Preserve accepted hotel cancellation quote | DEPTH34 | PR #13 `ab9f395...`: missing `SessionLocal`, 5 backend failures | PR #14 DEPTH34R2 `2dab537...` | CI 34434039448: affected backend + frontend/native pass | yes | RETAINED |
| Logout and role-scoped session refresh | DEPTH35 | PR #15 `0dd0bd...`: 2 CookieConflict fixture failures after 36 pass | PR #16 DEPTH35R2 `a758f4...` | CI 34440381225: 38 backend + 239 frontend/native pass | yes | RETAINED |
| Full DEPTH36 auth/mobile contract and support tree | DEPTH36 | #17 full suite: 19 failures; #19 R2: 5 failures | #20 DEPTH36R3 `7bd98db...` | CI 34453179558: 1673 pass, 0 fail/error; 6 PG-only skipped | yes | RETAINED |
| PostgreSQL-only race/transaction behavior deferred in SQLite full suite | DEPTH36/37 | 6 PG-only tests skipped in #20 | later dedicated disposable-PostgreSQL acceptance (#26 and DEPTH40 runtime work) | isolated PG/race evidence plus #36 PG16 real migration/runtime | yes | RETAINED |
| Native Expo/provider startup | DEPTH37 | #22 build candidate later showed blank startup; #23 captured actual FAIL/missing ExpoAsset | #24 DEPTH37R2 corrected linking/autolinking | corrected native-build/startup acceptance chain | yes | RETAINED |
| Supplier credential/input readiness | DEPTH37 readiness | #25 found 8 canonical supplier inputs empty | no source defect inferred; inputs remain deployment/environment issue | preflight correctly blocked before external calls | code yes; live input gate no | DEFERRED_EXTERNAL_GATE |
| Universal Agent transaction gateway across REST/MCP/A2A/Apple/native core | PR #27 P0 | first acceptance tooling attempt #28 failed before target test path | #29 corrected acceptance | run 34546875079; 25 product/regression tests pass | yes | RETAINED |
| P0.2 transaction lifecycle: aftersales, idempotency, native truth | PR #31 P0.2 `b977e2...` | no later product failure | inherited by P0.3 | run 34552701811, 71/71 scoped lifecycle/regression checks | yes | RETAINED |
| Hotel hard-hold connector-native release | PR #32 P0.3 | previous hard hold remained open | P0.3 `e0742e...` | fresh-restore P0.3 tests 11/11 + P0.2 sentinel 6/6 | yes | RETAINED |
| Ride/Rental native unpaid-expiry contract | PR #32 P0.3 | previous capability incomplete | P0.3 `e0742e...` | same P0.3 fresh-restore run | yes | RETAINED |
| Apple AppIntents/Xcode software gate | PR #32 P0.3 | earlier native build/linking history had failures | P0.3 | Xcode simulator run 34555752235 PASS with warnings-as-errors | yes | RETAINED |
| Physical iPhone AppIntents/lifecycle smoke | P0.3 gate definition | not executed because required self-hosted physical-device runner is unavailable | no replacement evidence exists | explicit fail-closed workflow only | code/gate present; physical evidence absent | DEFERRED_EXTERNAL_GATE |
| Full source recoverability without historical overlay | DEPTH40 #33 | earlier acceptance iterations caught extraction/checksum/dependency assumptions | corrected sealed parent + #34 | run 34558059579 zero-restore PASS; 1271 files | yes, now directly in Git | RETAINED |
| Eight-service staging runtime packaging | DEPTH40 #36 | first isolated attempts had API timeout / PG probe race; evidence preserved | corrected CI packaging/runtime review | run 34565938702: 20/20 PASS, source unchanged | product source yes; deployment mapping external | DEFERRED_EXTERNAL_GATE |
| PostgreSQL 18 upgrade/recovery synthetic review | DEPTH40 #37 | PR text initially said PENDING, not a failure | actual workflow completed | run 34571894075 SUCCESS | source unchanged | RETAINED_AS_VALIDATION |

## Gate result

`FEATURE_RETENTION_GATE=PASS_WITH_EXTERNAL_HOLDS`

The selected 1271-file source retains the corrected software lineage through P0.3. No known failed implementation was intentionally reintroduced during consolidation. Remaining HOLDs are environmental/deployment evidence requirements (physical iPhone, supplier credentials/inputs, current HK mapping, live browser/E2E and production-stage authority), not a reason to substitute an older failed source.