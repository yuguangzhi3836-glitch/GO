# PR314 actual CI acceptance and unified business candidate integration

Status: scoped evidence acceptance PASS; integrated source candidate, not a
canonical release or live deployment. Change classes: TEST_ONLY, BUILD,
DOCUMENTATION. No topology or database migration change.

## Actual PR314 artifacts

The inspected source is `3a28b6d7215e9285b1c2b153497df9c416a638b2`, application
tree `dd542fe725922a0ce7c499401d8615b47ab1a24d`. Both runs completed successfully:

* [Rental/attraction 36945213057](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36945213057): evidence-hygiene, browser, four PostgreSQL suites.
* [Ticket 36945213058](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36945213058): browser, native source checks, four PostgreSQL suites.

All 12 jobs passed. The eight JUnit documents contain 674 tests, zero failures,
errors or skips. This is isolated developer CI, not independent C13/C14 or
physical mobile-device acceptance.

Downloaded all 11 artifacts, verified each ZIP digest against GitHub metadata,
rejected unsafe archive paths/links, and inspected all 94 files. The five
rental/attraction artifacts have verified SANITIZATION and SHA256 manifests:
every published payload digest matches, file coverage is complete, and the
manifest declares no raw publication or altered test verdict. PostgreSQL
bindings match the inspected head/application tree; source maps include the
three exact evidence-hygiene implementation/conftest files. All 12 job logs
were checked in memory for JWT and Authorization value patterns.

No credential finding was observed. Gitleaks 8.30.1, default rules plus the
repository Authorization rule, returned exit 1 with 243 generic findings:
230 source-file SHA-256 digests, 10 business idempotency UUIDs and 3 rental
deposit operation identifiers. Every finding has a safe path/line/classification
record in `PR314_GITLEAKS_REVIEW.json`. No new allowlist hides these findings.
The 36 PNGs received byte checks only, without OCR. Job logs received the
targeted in-memory pattern check, not a claimed Gitleaks scan.

`PR314_ACTUAL_CI_ACCEPTANCE.json` binds the job/step verdicts, artifact IDs and
ZIP digests, publication hash checks, source bindings, JUnit counts and scan
scope. It contains neither raw matches nor credential values.

## Additional gap found and fixed

The six ticket artifacts passed the scoped credential scan, but their workflow
still uploaded directly from raw directories. They had no SANITIZATION
manifest; its browser/native paths also lacked publication SHA256 manifests.
A clean successful run does not establish a safe failure upload boundary.

The integration therefore applies the same bounded console filter and atomic
`prepare` boundary to ticket PostgreSQL, browser and native evidence. All
three upload steps require successful preparation and use only publish
directories. A prerequisite guard test job gates all three job types. Existing
test commands, test verdicts, isolated database scope and artifact names remain
unchanged. All six actual downloaded ticket artifacts also passed a local
replay through this preparation boundary.

## Candidate lineage and retained source

The intended business base is PR313 at
`07eaef6dd06ef49ccd5b14f318df099e0e3b4f99`, which descends from PR307
`19610c2f74bd264f57ad42f29394812f8a56a4fb` and PR298
`e109af4dc4ae84f27f63d0104aa42c8d6b64b34d`. This preserves the existing non-DOT
business integration and the subsequent SI DIRECT+, GO SI search, Chinese
airport input, search notice removal and single-confirmation hotel date work.

Before integration, every path touched by PR314 had the same predecessor blob
in PR313 as in R4 (or was absent in both). All 13 PR314 result blobs are reused
exactly. Only the ticket workflow and this new acceptance record are added on
top. `INTEGRATION_BINDING.json` records application identity and exact retention
checks. Existing production application source, frontend, mobile source,
migrations, deployment definitions, Control Plane and DOT/Runtime bytes are
not replaced by old R4 files.

The inherited R5 documents remain evidence about PR314's original source and
scan. They are not silently rebound to the integrated candidate. Its changed
application tree needs fresh applicable acceptance; prior C13/C14 or image
results do not transfer. The PR records subsequent isolated CI against the
new immutable head separately.

## Remaining release boundaries

This completes the requested evidence fix's source integration. It does not
claim to close the predecessor's whole-business retention/capacity/review gaps.
PR311's separately reviewed builder/runtime-root change remains a separate
controlled-installation dependency; it is not installed or folded into this
business-source change. Canonical candidate/runtime pointers and signed
Evidence are unchanged. No main merge, deployment, real inventory/payment
access, credential revocation/rotation or history rewriting is performed.

Historical truncated fragments remain in old commits. GitGuardian backend
incident closure is not claimed. Use the report's source and scope when
recording that distinction in incident triage.

## Reproduce the local gate

```sh
python -m pytest ci/evidence_hygiene/test_guard.py -q
python application/tests/evidence_hygiene.py scan \
  docs/acceptance/rental-attractions \
  docs/acceptance/registration-privacy-20260927
python application/tests/evidence_hygiene.py prepare raw-evidence publish-evidence
```

For artifact acceptance, download the listed artifact IDs, verify their ZIP
SHA-256 values, safely extract, and verify every path in SHA256.json and every
sanitized digest in SANITIZATION.json. Check JUnit/source bindings, then scan
using the recorded Gitleaks defaults/configuration and review findings. Retain
only sanitized metadata in the repository; keep raw scanner reports private.
