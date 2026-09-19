# Round 7 runtime and first-hotel assessment

Date: 2026-09-19. Baseline inspected: PR #225, `5a708b38de32a52f92384275ab1c30ccf79c53c1`.

## What ran

`PYTHONPATH=src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m pytest -q -s tests/test_hotel_direct_submission_real_identity.py tests/test_hotel_direct_submission_gallery_probe.py --junitxml=../evidence/depth-round7-20260919/runtime-probes.xml`

Result: 4 tests passed. See raw `runtime-probes.log` and JUnit XML. Synthetic accounts and temporary SQLite databases only; no production sessions, secrets, hotel mutations, merge or deployment.

Three tests use the real IdentityService password hashing/login, administrator MFA enrollment/TOTP, signed JWT, persisted sessions and original authorization dependencies. No principal dependency override. They verify unauthenticated rejection, supplier/admin role separation, read-only administrator rejection, wrong actor header rejection, session revocation, two-supplier property isolation, and original-image publish/retry/revoke. Accounts are generated only inside the isolated fixture. This is actual authentication-service and scoped-router integration, not the application's login UI or full authentication middleware acceptance.

## Full application and browser boundary — checkout blocker resolved

Initially, unmodified `application/src/go_hotel/main.py` at the exact baseline had 115 absent direct imports. This local completeness problem was resolved in the same task: fetched missing files at the exact baseline, completing all 458 source Python files and 81 previously absent frontend text/SVG assets, preserving current product edits. `import go_hotel.main` then succeeded. No dummy modules or replacement main were introduced. Initial gaps and final resolution are recorded separately in `runtime-material-check.json`.

`tests/test_hotel_direct_submission_full_app.py` ran the real main application and lifespan, with actual audit/security/observability middleware. Two tests passed in 7.711 seconds; `full-app.log` and `full-app.xml` are the raw evidence. Every imported SessionLocal binding points to one temporary fixture SQLite database. Optional expiry workers and external model/SSO settings are disabled. Passwords and identities are generated locally; authentication dependencies are not overridden.

Verified through the actual BFF endpoints: password login, mandatory admin MFA enrollment/TOTP, session cookies, missing/wrong CSRF rejected with 403, inspected manifest/facts hashes approved with the correct cookie and CSRF, publication, idempotent retry, revocation stopping original-image reads, logout invalidating access, same-owner two-hotel switching and foreign-hotel rejection. All three HTML entry routes and their 49 directly referenced JS/CSS assets return HTTP 200.

This is full-application ASGI TestClient integration, not a real TCP/browser run. It does not execute frontend JavaScript, verify visual layout, check every dynamic module/image reference, or establish mobile-browser acceptance. Browser work belongs to the parent task; this assessment did not open a browser. PostgreSQL and current staging runtime/source binding remain unverified.

## 敖麓谷雅首家实证材料

The existing `aoluguya_transfer_20260919` package was inspected, not modified. Its six file hashes are recorded in the JSON evidence. It contains 19 source room records and 275 image identifiers; `image_files_saved=0`, `go_written=false`, `source_to_go_mapping_verified=false`. No hotel-provided original image binaries are present in that package. Thumbnails/identifiers do not establish original dimensions, rights, checksums or publication.

All 19 source room IDs/names are listed individually in `runtime-material-check.json`, each with null canonical room ID and PENDING mapping. Source `555252661` combines 圆梦/枕月/卧云/栖霞 in one name and spans 48–80 square metres, requiring explicit physical-room interpretation. It must not automatically become a canonical physical room or be dropped simply to force the target count. The authoritative 17-room ID inventory and a current destination readback were not obtained in this task; mappings cannot be honestly approved from names alone.

The source package includes basic address/contact material and policy/facility page snapshots, but its existing status explicitly lists incomplete room-specific facilities, facility subdetails such as hours/fees, and some highlight descriptions. Neither 100% content completeness nor current GO field equality is demonstrated. Next inputs: current canonical hotel and 17-room IDs, hotel-uploaded originals with rights declarations, and the approved isolated destination readback. Do not convert source room-count metadata into availability or source rate cancellation terms into a hotel-wide policy.

Historical archives were subsequently recovered and decoded; see `AOLUGUYA_ARCHIVE_RECOVERY.md/json`. They contain 229 distinct image byte objects, 69 meeting current dimensions/format requirements, but include unrelated properties, unknown/inferred rights and two room-ID conflicts. These findings do not establish current canonical bindings or authorization.

## Gallery performance observation

One actual service probe uploads 18 additional originals beside a hero and room image, reviews all 20, publishes through the existing canonical factory, reads the page, a single image and the administrator inspection three times each, then verifies revocation denies access. Synthetic images are 1600×900 solid-colour JPEGs; their small byte sizes are not representative of real hotel photography. Timings below reflect the final parent-extended probe run.

| Operation | Observed elapsed time | Original file reads per request |
|---|---:|---:|
| Publish 20 assets | 461.844 ms | Not instrumented |
| Read page, 3 samples | 101.154–108.589 ms | 40 across all 20 assets |
| Read one image, 3 samples | 152.878–161.619 ms | 61 across all 20 assets |
| Administrator inspection, 3 samples | 307.241–312.274 ms | 120 across all 20 assets |

This exposes repeated whole-gallery verification within one request. A full page followed by 20 image requests would trigger substantially more work than verifying 20 originals once; actual concurrent browser/network loading was not measured. Next optimization should remove duplicate checks within a single request and examine target-image verification while retaining current approval, ownership, inventory, expiry and revocation checks. Do not introduce stale approval caching or skip corruption checks merely to improve these timings. These observations are not a throughput, p95, 1000-user or full-gallery acceptance result.

## Database concurrency

`postgres`, `pg_ctl`, `psql` and `docker` were not available on PATH. No approved isolated PostgreSQL endpoint was supplied to this task. Sequential repeat publication is tested, but simultaneous approval/revocation/publication and PostgreSQL row-lock semantics remain unverified. SQLite `FOR UPDATE` behavior cannot establish the production guarantee, so no SQLite thread race has been relabeled as PostgreSQL concurrency acceptance.

Next database gate: two independent PostgreSQL connections synchronized around the row-lock and publication transaction boundaries; assert one canonical version for duplicate publication, no post-revocation public read, and deterministic conflict outcomes. Run only in an isolated database bound to the candidate, never against a live hotel.
