# Round 7 runtime and first-hotel assessment

Date: 2026-09-19. Baseline inspected: PR #225, `5a708b38de32a52f92384275ab1c30ccf79c53c1`.

## What ran

`PYTHONPATH=src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m pytest -q -s tests/test_hotel_direct_submission_real_identity.py tests/test_hotel_direct_submission_gallery_probe.py --junitxml=../evidence/depth-round7-20260919/runtime-probes.xml`

Result: 4 tests passed. See raw `runtime-probes.log` and JUnit XML. Synthetic accounts and temporary SQLite databases only; no production sessions, secrets, hotel mutations, merge or deployment.

Three tests use the real IdentityService password hashing/login, administrator MFA enrollment/TOTP, signed JWT, persisted sessions and original authorization dependencies. No principal dependency override. They verify unauthenticated rejection, supplier/admin role separation, read-only administrator rejection, wrong actor header rejection, session revocation, two-supplier property isolation, and original-image publish/retry/revoke. Accounts are generated only inside the isolated fixture. This is actual authentication-service and scoped-router integration, not the application's login UI or full authentication middleware acceptance.

## Full application and browser boundary

Fetched unmodified `application/src/go_hotel/main.py` at the exact baseline. AST inspection found 120 direct internal import statements, 115 referenced modules absent from this partial local checkout. Actual `import go_hotel.main` failed at the first missing module: `go_hotel.api.routes.autonomy_execution`. The complete missing-module inventory and main hash are recorded in `runtime-material-check.json`. This is a checkout completeness blocker, not evidence that the repository application is broken. No dummy modules or replacement main were introduced to label a partial app as complete.

Therefore full-app startup, middleware/CSRF behavior, real UI login, browser/mobile flow, and current runtime/source binding remain unverified. Browser work belongs to the parent task; this assessment did not open a browser. The exact prerequisite is a complete runnable checkout or an already approved isolated runtime bound to the candidate source, with test identities. No production or hotel identity is necessary for synthetic UI acceptance.

## 敖麓谷雅首家实证材料

The existing `aoluguya_transfer_20260919` package was inspected, not modified. Its six file hashes are recorded in the JSON evidence. It contains 19 source room records and 275 image identifiers; `image_files_saved=0`, `go_written=false`, `source_to_go_mapping_verified=false`. No hotel-provided original image binaries are present in that package. Thumbnails/identifiers do not establish original dimensions, rights, checksums or publication.

All 19 source room IDs/names are listed individually in `runtime-material-check.json`, each with null canonical room ID and PENDING mapping. Source `555252661` combines 圆梦/枕月/卧云/栖霞 in one name and spans 48–80 square metres, requiring explicit physical-room interpretation. It must not automatically become a canonical physical room or be dropped simply to force the target count. The authoritative 17-room ID inventory and a current destination readback were not obtained in this task; mappings cannot be honestly approved from names alone.

The source package includes basic address/contact material and policy/facility page snapshots, but its existing status explicitly lists incomplete room-specific facilities, facility subdetails such as hours/fees, and some highlight descriptions. Neither 100% content completeness nor current GO field equality is demonstrated. Next inputs: current canonical hotel and 17-room IDs, hotel-uploaded originals with rights declarations, and the approved isolated destination readback. Do not convert source room-count metadata into availability or source rate cancellation terms into a hotel-wide policy.

## Gallery performance observation

One actual service probe uploads 18 additional originals beside a hero and room image, reviews all 20, publishes through the existing canonical factory, reads the page three times and a single image three times, then verifies revocation denies access. Synthetic images are 1600×900 solid-colour JPEGs; their small byte sizes are not representative of real hotel photography.

| Operation | Observed elapsed time | Original file reads per request |
|---|---:|---:|
| Publish 20 assets | 460.838 ms | Not instrumented |
| Read page, 3 samples | 100.809–101.825 ms | 40 across all 20 assets |
| Read one image, 3 samples | 154.465–158.248 ms | 61 across all 20 assets |

This exposes repeated whole-gallery verification within one request. A full page followed by 20 image requests would trigger substantially more work than verifying 20 originals once; actual concurrent browser/network loading was not measured. Next optimization should remove duplicate checks within a single request and examine target-image verification while retaining current approval, ownership, inventory, expiry and revocation checks. Do not introduce stale approval caching or skip corruption checks merely to improve these timings. These observations are not a throughput, p95, 1000-user or full-gallery acceptance result.

## Database concurrency

`postgres`, `pg_ctl`, `psql` and `docker` were not available on PATH. No approved isolated PostgreSQL endpoint was supplied to this task. Sequential repeat publication is tested, but simultaneous approval/revocation/publication and PostgreSQL row-lock semantics remain unverified. SQLite `FOR UPDATE` behavior cannot establish the production guarantee, so no SQLite thread race has been relabeled as PostgreSQL concurrency acceptance.

Next database gate: two independent PostgreSQL connections synchronized around the row-lock and publication transaction boundaries; assert one canonical version for duplicate publication, no post-revocation public read, and deterministic conflict outcomes. Run only in an isolated database bound to the candidate, never against a live hotel.
