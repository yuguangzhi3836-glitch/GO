# PR #273 R5 evidence hygiene remediation and rescan

Review status: proposed change, not merged or deployed. Changes are TEST_ONLY,
BUILD and DOCUMENTATION. The affected R4 candidate is the intended base:
`cb96de655f0c84596e85b379c6e9bd67f92817fe` on
`fix/registration-privacy-c14-20260927`. A separate R5 branch preserves the
locked R4 identity. This is not a new canonical-main or runtime baseline.

## Finding and disposition

The GitGuardian email dated 2026-10-01 13:27 UTC links to line 5 of
`docs/acceptance/rental-attractions/20260927/operations-next/independent/attraction-operations-before.log`
at R4. Its XML sibling contains the same five distinct session fragments. These
two files were introduced by `d666da292d1b11a255eeb40dcfd4d4e97d1302c0` and
still had ten occurrences each in R4. R4's existing manifest covered only
`first-fix.log/xml`, originally introduced by
`4c10cced49fd4eff3dd66638ce1c1861bb077ac5` (one and two occurrences).

The values came from actual isolated application test login sessions, not
hand-written dummy credentials. The stored values are truncated diagnostic
representations containing an internal ellipsis and cannot pass the repository's
JWT parsing path as stored. Across the four original files there are 23
occurrences representing six distinct truncated fragments. This does not prove
that every original complete session value was never usable; it establishes
that these committed fragments are not usable credentials. No credential was
replayed against any service.

R5 replaces the 20 remaining occurrences in the independent log/XML with the
same redaction marker used by R4. `R5_EVIDENCE_REDACTION.json` binds original
and sanitized SHA-256 values. Original test failures, test names and JUnit
counts are retained. First-fix files and the R4 manifest retain their existing
content. Old commits, PR refs and old artifacts have not been rewritten or deleted.

Per the user's instruction, no credential rotation or revocation is performed.
For these fragments alone, historical rewriting has limited security benefit:
it changes review/evidence identities without revoking any complete credential that
might have existed elsewhere. If a subsequent broader scan finds a complete
credential, assess its issuer, audience, expiry and actual exposure separately,
then obtain approval for issuer-side invalidation and any coordinated history
cleanup. Do not submit a found credential to an unrelated validation endpoint.

## Prevention implemented

* Pytest report hooks redact failure/collection/skip text, captured output and
  sensitive report properties before terminal and JUnit rendering.
* A bounded stream filter protects the affected workflow's console/tee output;
  `pipefail` preserves the original test or browser failure.
* Upload preparation sanitizes to a separate directory, scans it, and hashes
  the sanitized bytes. Both upload steps require successful preparation.
  A preparation error leaves no publishable directory and has no raw fallback.
* A prerequisite CI job runs the guard regression tests and checks the tracked
  rental/attraction evidence before the acceptance jobs start.

The source implementation is included inside `application/tests/` to support
the repository's application-only frozen source packages. This changes the
application tree even though production business code is unchanged. Previous
C13/C14 results do not transfer. C13 and the complete C14 suite were NOT_EXECUTED
as part of this scoped remediation; release and deployment remain HOLD.

## Scan results and boundaries

`R5_SCAN_REPORT.json` records tool identity, scope, artifact digests and summary;
`R5_SCAN_FINDINGS.json` contains only safe metadata (rule, path, line, commit and
classification). Neither contains a matched secret or raw scanner snippet.

| Surface | Result |
| --- | --- |
| Candidate files in the two affected acceptance directories | No Authorization/session findings after R5; 25 generic Gitleaks matches reviewed as 19 business idempotency UUIDs and 6 rental-deposit operation identifiers |
| Same directories across all fetched heads, tags and PR head/merge refs | Seven touching commits scanned; 23 known truncated-session findings retained in history, plus 25 reviewed business identifiers |
| All ten artifacts from R4 run 36305234598 and introduction run 36270344405 | ZIP digests verified; 100 files checked, including 52 PNG byte checks; no targeted credential findings; 253 generic matches reviewed as 230 source-file SHA-256 values and 23 business identifiers |
| All ten job logs for those two runs | In-memory JWT and Authorization value-pattern scan: no matches; these logs were not scanned by Gitleaks |
| Preparation against the ten downloaded historical artifact bundles | All ten passed the new publication preparation boundary without changing their test verdicts |
| Guard regression tests | 25 passed, including real pytest failure/setup/collection/skip subprocesses, JUnit, application-only conftest, pipeline exit status, multiline values and rejected uploads |

Gitleaks uses version 8.30.1, official release SHA-256 verified, default rules
plus the custom Authorization rule, with inline allow directives ignored and
an empty ignore file. Its raw exit code is 1 for each recorded scan because
it reports findings. Reviewed noncredential classifications are explicit;
there is no new blanket allowlist and no claim of a raw zero-finding scan.

Business identifier adjudication is supported by
`application/src/go_hotel/api/routes/rental_operations.py` (Idempotency-Key and
receipt key propagation) and
`application/src/go_hotel/services/rental_deposit_money.py` (operation identifier
construction from the obligation ID). Source hash matches are in source-file
fingerprint maps. These are not authentication credentials.

The graph snapshot has 822 refs and 2,289 reachable commits. The history scan
was path-scoped to the two affected acceptance directories; it is not a scan of
every object or archived deliverable in the repository. It does not cover other
Actions runs, deleted/unavailable refs, image OCR, GitHub caches/forks or local
clones. No GitGuardian backend rescan or incident closure was performed; an
independent scan cannot change that service's incident state. The known
historical findings should remain visible until separately adjudicated there.

## Reproduction and follow-up

```sh
python -m pytest ci/evidence_hygiene/test_guard.py -q
python application/tests/evidence_hygiene.py scan \
  docs/acceptance/rental-attractions \
  docs/acceptance/registration-privacy-20260927

# Use an empty ignore file outside the repository. Keep raw reports private.
gitleaks dir docs/acceptance \
  --config ci/evidence_hygiene/gitleaks.toml --redact=100 \
  --ignore-gitleaks-allow --gitleaks-ignore-path /tmp/empty-gitleaks-ignore \
  --max-decode-depth 2 --max-archive-depth 2 \
  --report-format json --report-path /tmp/private-candidate-scan.json

gitleaks git . \
  --config ci/evidence_hygiene/gitleaks.toml --redact=100 \
  --ignore-gitleaks-allow --gitleaks-ignore-path /tmp/empty-gitleaks-ignore \
  --max-decode-depth 2 --max-archive-depth 2 \
  --log-opts='--all --full-history -- docs/acceptance/rental-attractions docs/acceptance/registration-privacy-20260927' \
  --report-format json --report-path /tmp/private-history-scan.json
```

The recorded candidate scan used a sparse checkout containing only those two
acceptance directories. For an exact reproduction in a full checkout, stage
copies of those directories and scan that staging root; scanning all of
`docs/acceptance` is a broader task. Fetch heads, tags, PR heads and available PR
merge refs before the historical scan. Keep artifact inventory/digests and the
scanner version with each rerun. Review every new generic finding before
publishing a credential-free metadata report. A complete-credential finding
must not be dismissed simply because it came from tests.

After review, rerun the GitGuardian incident's own historical scan or attach
this scoped evidence to its triage record, distinguishing remediation in the
new tree from retained occurrences in old commits. No such external state
change is claimed here.
