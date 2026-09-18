# Durable media acceptance — 2026-09-18

Status: ISOLATED_TESTS_PASS; FINAL_INDEPENDENT_REVIEW_AND_LIVE_TOPOLOGY_E2E_PENDING.

The current business deployment remains PR198, source f827a3aefd95fd95dedb2bd2ecc93ae01111ea90, image 28c8b3b34992d9d4aefb4a58d892507ef06c063d955b2da86fe0e3560013d3fe, DB0137. At 05:20 UTC all eight roles were running with zero restarts and API healthy. The API still had no durable media mount. The selected hotel had 17 rooms, zero retained images, 69% completeness and 14 issues in the authenticated admin page. Contact fields were present.

This is a control-plane/topology candidate stacked on PR193 (302b6bd2a16dd59b4ecfd2b351eadb3ebf5d6fd1), whose source matches the installed control files. Its inherited application tree is historical and MUST NOT be deployed as a business candidate. The intended first transition retains the existing, independently identified PR198 business image. Source installation and immutable V3 candidate admission must bind that image and its existing TEST_PR/package evidence; this PR does not admit or dispatch it.

Validation: 26 topology tests, 13 source-installer/hash-only tests, 137 CC tests, 65 Bridge tests, 16 same-revision tests, 23 collector checks and 31 rollback checks pass. Sixty-three unchanged control/test dependency files match their PR193 Git blobs; added and changed files are explicitly in this delta. The three earlier independent-review blockers have regression coverage, but that earlier review remains CHANGE_REQUESTED until independently re-reviewed. Passing local tests are not a substitute for final review.

At 05:24 UTC a bounded, isolated Docker proof used the actual current and previous business images and their MediaIndex implementation. A controlled non-publishable PNG, SQLite index revision and rights metadata survived seed, container recreation and image rollback with identical SHA256 02ed3c6c462e2320014c77f32ba471e6c1db29829ed3efe0ffdf59cd17050dcb. Only fresh temporary test containers and a temporary cache were used; no existing business container was targeted. This does not prove activation of the proposed live mount.

The CI workflow separately uses the exact PR198 MediaIndex module in two disposable fixture images. It verifies the fixture hash and records its origin. Those are test images, not the actual HK business images used in the host proof.

The 05:25 UTC preflight shows all nine existing source targets at their expected before hashes and the one new helper absent. The install package is deliberately UNSEALED. Final independent review, fresh installation guards, source install, storage preparation, formal candidate admission, fresh signed CANARY/VERIFY/DEPLOY/POST_VERIFY and mounted-data persistence/rollback proof remain required. The current proven topology pointer is not changed.

Image catalog acceptance remains incomplete: hero/public-area ingestion and official mapping of all 17 room types are pending. Re-uploading the catalog before fixing the ephemeral cache would not close the loss-on-recreate defect. Prior load results remain 20/100/250 PASS, sustained 500 latency FAIL, 1000 NOT RUN. Production, real supplier use and final release remain HOLD.
