# Excluded and superseded candidates

Exclusion here means “not selected as the canonical application source.” Historical branches/PRs remain intact for audit.

## Genuine failed product candidates

| PR | Candidate/stage | Failure evidence | Disposition |
|---|---|---|---|
| #10 | DEPTH32 `51c95e622521ddca39625744bdde8e997db40a05` | CI 34427342231: 181 backend pass, 6 fail; FLIGHT used an incompatible rail/attraction-constrained operation table; frontend did not run | `EXCLUDED_FAILED`, superseded by #11 DEPTH32R2 |
| #13 | DEPTH34 `ab9f39518de107e05c95b800839bd5f7c229ea23` | CI 34433623433: 5 backend fail, 4 pass; missing `SessionLocal`; frontend did not run | `EXCLUDED_FAILED`, superseded by #14 DEPTH34R2 |
| #15 | DEPTH35 `0dd0bdca784ece89eb7600d38b5210ed4436c88a` | CI 34439772418: 36 backend pass, 2 fixture `CookieConflict` failures; frontend did not run | `EXCLUDED_FAILED`, superseded by #16 DEPTH35R2 |
| #17 | initial DEPTH36 acceptance | complete runs showed 1654 pass, 19 fail, 6 skip | `EXCLUDED_FAILED`, repaired through #18/#19/#20 |
| #19 | DEPTH36R2 `32712e...` | full run 34451882079: 1668 pass, 5 fail, 6 PG-only skipped | `EXCLUDED_FAILED`, superseded by #20 DEPTH36R3 |
| #22/#23 | original DEPTH37 native/provider build/startup | build could compile, but actual iOS startup evidence showed blank screen after 60s / missing ExpoAsset; green evidence workflow did not mean product PASS | `EXCLUDED_FAILED`, superseded by #24 DEPTH37R2 |

## Superseded intermediate candidates / acceptance mechanics

- #18: scoped DEPTH36 auth-test repair; application semantics were not a complete final candidate and it was superseded by the later full-suite correction #20.
- #21: readiness/packaging evidence only; no new canonical product semantics.
- #28: first Universal Agent Gateway acceptance attempt; workflow/path mechanics failed before serving as final acceptance; corrected by #29. The underlying product feature is retained through later candidates.
- #34: successful acceptance of the selected DEPTH40 source, but acceptance branch code is not product source and is therefore not copied into `application/`.
- #35, #36, #37: packaging/runtime/upgrade validation supplements. They leave the fixed 1271-file product source unchanged and are not themselves application candidates.

## Infrastructure/documentation PRs excluded from product lineage

PRs #5, #9, #38, #39 and #40 were authored by `chenzhenxi1-sudo` and change runbooks, operations documentation, Command Center archive and HK-STAGING archive. They materially affect current `main` history and were reviewed, but they are not boss product-feature lineage and are deliberately outside `application/`.

## Earlier validated but superseded product generations

DEPTH28, 29, 30, 31, corrected DEPTH32R2, DEPTH33, corrected DEPTH34R2, corrected DEPTH35R2, corrected DEPTH36R3, corrected DEPTH37R2, P0 and P0.2 are not “failed”; they are excluded only because their effective functionality is inherited by the later sealed P0.3 source. Re-selecting one of them would silently drop later validated features.

## Unknown/abandoned handling

No ambiguous parallel product lineage with evidence equal to the sealed P0.3 lineage was found. Historical experiment/preparation/packaging branches not carried into the sealed 1271-file fingerprint are treated as non-canonical rather than silently merged. No historical branch or PR was deleted or closed by this consolidation.