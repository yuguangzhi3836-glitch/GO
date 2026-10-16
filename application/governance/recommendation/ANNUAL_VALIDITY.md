# Annual recommendation validity — candidate for Issue 507

User decision, 2026-10-06: a recommendation lasts one natural year; start
reassessment 30 days before expiry. Expiry without a passed reassessment does not
renew the recommendation.

## C09 module contract

- The existing `JudgmentService.reevaluate` acceptance transaction records the
  start of a newly accepted, distinct recommendation assessment. Dates are UTC;
  February 29 becomes February 28 at the same UTC time in the following year.
- `recommendation_authority` is service-owned sealed feature metadata. Callers
  cannot provide it. Annual expiry and review dates are validated on reads.
- The assessment content digest identifies the same underlying assessment even
  after intervening judgments. Replays retain its original start; a caller's
  transport revision does not extend it. New substantive reassessment evidence
  must be supplied through the existing assessment producer/acceptance boundary.
- Legacy or malformed records without annual provenance remain historical and
  read as pending reassessment. A row's `valid_from` alone does not prove approval.
- All four reads (`public_summary_or_default`, `public_view`, `get_latest`,
  `get_judgment`) compute effective validity; expired and superseded decisions
  cannot be returned as a current strong recommendation.
- The existing `process_pending` worker entry scans active recommendations in
  keyset pages. `limit` caps page size and ordinary hook processing, not the total
  annual scan, so older hotels are not permanently starved. A scan is O(active
  recommendations); capacity/latency at national scale is not established here.
- One durable `RECOMMENDATION_ANNUAL_REVIEW` hook represents each assessment
  cycle. Hotel transaction locking serializes scan/writer races. Repeated scans,
  service restart, or pre-commit rollback do not create another cycle request.
- Annual hooks remain `REQUESTED` for assessment. The generic worker cannot
  automatically reuse old evidence to approve them. A new passed/failed assessment
  completes the request with its result binding; failed reassessment does not
  create a new recommendation term. Completed-hook replay verifies that binding.

## Integration boundary — not a claim of authoritative production approval

This patch reuses the existing recommendation assessment input and judgment
acceptance point; it does not manufacture a reviewer, signing identity or an
upstream review result. Repository inspection found the input on
`application/src/go_hotel/api/routes/judgment.py::reevaluate` (`extra_features`),
with recommendation decisions evaluated by `JudgmentService._recommend`.
The route itself declares no authentication dependency. The authoritative
production assessment producer and its ingress authorization are NOT established
by this module's tests. Before production adoption the owner of that API/security
boundary must establish the authorized producer, reviewer/result identity and
refusal of unauthenticated/unapproved assessments. Those files are outside the
three C09-owned paths authorized in Issue 507; they are not changed here.

`application/src/go_hotel/workers/judgment_worker.py` already invokes
`process_pending(100)`. This candidate proves durable request generation, not that
an assessor consumes the request or that the live worker has this candidate.
Real annual reassessment completion requires the existing assessor to consume
these requests and submit the resulting distinct assessment. Live wiring and
completion are UNPROVEN; no deployment or scheduler change is included.

## Recovery and validation provenance

The original Builder run 37413646905 / attempt 1 / job 112107450893 accepted
Issue 507, reported 39 tests passed, then hit its context-rebuild circuit breaker.
No second Builder was dispatched. Its agent artifact 11390801529 has archive
SHA256 `1c205af91948a36fb8d038f720197e5acdf91ee325479213a6160e605b435af2`.
The service diff and pre-cleanup test readback were recovered as inert text.
This candidate is a new source identity, not the missing local commit 88c0adfd.

Two additional acceptance cases fail against the recovered service: A→B→A
replay incorrectly renews A; a page-size-one scan misses older hotels. Both are
fixed here. Additional tests cover UTC/30-day boundaries, legacy/malformed
metadata, concurrent scans, restart/rollback, same-cycle deduplication, failure
without renewal, old-judgment reads and completed-hook replay. Tests use isolated
SQLite unless explicitly stated otherwise; PostgreSQL concurrency/performance
and live operations are not claimed.

Change classes: PRODUCT_FEATURE, PRODUCT_FIX, CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.
CONTROL_PLANE applies to recommendation-authority metadata, historical assessment
replay, durable review-request identities and completed-hook authority bindings.
No shared model/migration, workflow, Runtime infrastructure, role, topology or IAM
permission change. Recommendation authority and replay semantics DO change as
described above; this scope statement does not exclude CONTROL_PLANE review.
This candidate remains Draft, unmerged and undeployed. Formal C14→C13 must bind
its exact new SHA. The original Builder's 39 passes are not transferred.
