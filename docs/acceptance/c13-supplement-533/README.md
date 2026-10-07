# #533 authorized C13 PostgreSQL supplement — source candidate

Owner has authorized expanding the two missing paths to all 15 business cases.
This supersedes the earlier scope-pending note; it does not authorize deployment,
real payments, a repeat C14, a larger model budget or unlimited retries.

Change classes: CONTROL_PLANE, PRODUCT_FEATURE, PRODUCT_FIX, BUILD, TEST_ONLY, DOCUMENTATION.
Authority boundary: adds a fixed, Owner-authorized C13 continuation after an original
blocked C13 and admitted C14. This changes control-plane admission, not business
roles, credentials, model budget, deployment topology or production access.

## Frozen evidence

- Payment PR #531: `0b7d0403f9f171844fdcf9bf3330ff9386e82943`.
- Application tree: `0f002d4253ca71b46de2f12761b99f1e6f1ad48c`.
- Original C13: run `37484199333`, attempt 1, BLOCKED / C13-EVIDENCE-001.
- Original C14: run `37482306650`, attempt 1, PASS_SCOPED; reused unchanged.

Original C13 recorded 20 passing cases but did not establish PostgreSQL usage:
its workflow manifest hardcoded the version while candidate conftest selected
SQLite. Nine migration cases explicitly use SQLite/static checks and may be
retained as such. The other eleven business results are superseded, never
relabelled PostgreSQL. Historical `database-preflight.json` remains unchanged.

## Implemented in this draft

The ordinary review ingress supports a bounded explicit Machine inventory.
A separate fixed `PG533-15-V1` continuation is restricted to #533, #531, the frozen
SHA/tree, the original round and exact sealed C13/C14 roots. It reads the existing
review outbox without writes or creation, retains the original request/model,
and provides one durable idempotency slot with `max_attempts=1`. Repeated issue
polls or comments do not create new slots. The ordinary C14-first route is unchanged.

After source review, main integration and authorized installation, the existing
#533 body can select this one final continuation with `C13 supplement: PG533-15-V2`.
`PG533-15-V1` remains the frozen evidence-scope identity, but it is a consumed
generation: on an installed build the V1 marker is refused by name
(`C13_SUPPLEMENT_V1_CONSUMED`) rather than silently ignored, so the body must be moved
to `PG533-15-V2` by an explicit human edit before any new slot can be planned. This
document is not a live activation instruction; no marker has been applied by this change.
A marker on old installed code is insufficient. Do not create a duplicate issue.

The existing C13 workflow carries the profile in runtime_transport. A trusted
backend pytest plugin selects only the disposable c13_lite PostgreSQL service
before application configuration loads. Each selected test has actual application
engine and PostgreSQL 18.4 observations before and after execution. Collection
must be exactly 15 cases: episode 4, retention 7, funding 3, checkout 1.

The assembler verifies original seals and raw machine digests, preserves original
raw artifacts, and accepts no missing, failed or skipped cases. Its aggregate is
24 cases: nine retained SQLite migration cases plus fifteen fresh PostgreSQL
business cases. Manifest parts keep their original/new run bindings and hashes.
The existing independent C13 reviewer then evaluates and seals the aggregate;
source/unit tests cannot substitute for that review or a Runtime receipt.

## Local verification

Python 3.12.14; synthetic offline fixtures, no model or PostgreSQL execution:

| Suite | Result |
| --- | --- |
| Existing/explicit review ingress (`test_c1_review*.py`) | 63 PASS |
| Existing review transport | 65 PASS |
| Fixed supplement admission/dedup/persistence | 7 PASS |
| Prior evidence preflight | 9 PASS |
| Supplement binding, aggregation and negative evidence cases | 10 PASS |
| Workflow contract | 27 PASS; 1 SKIP (actionlint unavailable) |

No real PostgreSQL or Docker is available locally. These results verify source
boundaries and synthetic evidence handling, not the fifteen business outcomes.

## Delivery and remaining gates

| Dimension | State |
| --- | --- |
| Source admission, transport, machine profile, evidence assembly | Implemented candidate |
| Local source checks | As listed above |
| Independent review of this source repair | NOT RUN |
| #533 new task admission/claim | UNPROVEN |
| Fifteen actual PostgreSQL business tests | NOT RUN by this change |
| Fresh independent C13 acceptance of #531 | NOT RUN |
| Merge / installation / deployment | NOT DONE |

The worker dispatches workflows from main; this unmerged PR cannot activate the
new path. A connected installation device is also missing. The next gate is
review of this source candidate, followed by separately authorized integration
and installation, then one real admission/claim/run/evidence/readback cycle.
No new Builder task, paid execution, live Runtime mutation or #470 rework was
performed. #480 remains unmerged/undeployed; ABBA and high concurrency stay paused.

Evidence:
- https://github.com/yuguangzhi3836-glitch/GO/issues/533
- https://github.com/yuguangzhi3836-glitch/GO/pull/534
- https://github.com/yuguangzhi3836-glitch/GO/actions/runs/37484199333/job/112339914820
- https://github.com/yuguangzhi3836-glitch/GO/actions/runs/37482306650

## Source review entry

`application/tests/test_c13_pg533_backend_entry.py` exposes 113 existing backend
checks as two no_db C13 cases (84 Runtime + 29 Lite). This reviews the supplement
implementation; it is not PostgreSQL payment acceptance for #531. The final review
candidate is one commit against current main so first-parent review includes the
whole change. Pre-consolidation history remains on the archive branch
`archive/c13-pg533-before-review-c894647e`.

## C14 classification correction

Original source-review run 37505546083 / attempt 1 / job 112413173205 on
`b818844931cc3c03f3b2e9ae23701181d9cfe7f8` sealed FAIL, C14-CLASS-001:
CONTROL_PLANE was missing from the declared classes. It is now explicitly
listed alongside all other applicable classes. No implementation or test scope
changed for this correction. Original FAIL remains historical, never rewritten.
Seal root: `c5109f2fb42417f17f59e5c3f6bb0a8412913314ea025a895e5222e470a18f02`.
Artifact 11431758151 ZIP SHA256:
`fb58a78db8b3ec5e1b5d722ee2636540840e5a46013dddc6da99bf276486b81d`.
A new frozen-SHA independent review must close the finding before C13.


## C13 entry summary correction

Frozen 4c6e31253009b2daceca9b0528db850fde0354e5 passed scoped C14
(run 37508490629; root 7727eb37a3e04b4f0f233b28ba9caeb92abccc21a55f6cacf8d8fc0f903ead21).
C13 run 37510367341 attempt 1 machine job 112429646181 exited 1;
independent AI job 112433001930 was skipped. Both underlying unittest suites
completed successfully (84 and 29), but the entry rejected `skipped` in negative
test names, not an actual skipped case. No C13 acceptance is claimed.

The entry now requires a zero exit code, exact test-count line and terminal
`OK`. Real skips (`OK (skipped=...)`) and failures remain rejected. Three
controlled subprocess regressions share the same validator: passing test with
`skipped` in its name, actual skip, and actual failure. Local stdlib execution
passed all three; full pytest execution remains a formal CI/C13 obligation.
The changed-test inventory now has five pytest cases: two backend suite entries
(113 inner checks) and three summary regressions. This remains source acceptance,
not the fifteen PostgreSQL payment cases. New SHA requires fresh C14 then C13;
no unchanged failed run is rerun and no prior verdict transfers to the new SHA.


## C13-WORKFLOW-001 evidence correction

On 0c9c1895cb3bd7bef17f31dc3f65e7c323bb174d, C14 run37512158373
passed and C13 run37512411205 machine job112436669460 passed all five
pytest cases (zero failures/skips, exit0). Independent C13 job112442206612
sealed FAIL, root ec6b6ef7e626ef09b0ec304cf5f79758dd918f94b705c3e591685594fa0e50ed,
claiming a missing database.json would make manifest hashing raise.

The exact frozen workflow already defines sha(name) with path.is_file() and
returns None for absent files. Executing that actual manifest Python block in a
new subprocess with no database.json produced exit0 and database_sha256=null.
The original FAIL is retained; no acceptance is inferred from this counterexample.
Two permanent regressions now execute the workflow's actual embedded block,
covering ordinary absence and the exact hash of present observation bytes.
No workflow implementation or missing-observation supplement rejection is relaxed.
The existing source entry now checks 84 Runtime +31 Lite =115 inner tests,
plus the same three summary-gate regressions (five outer pytest cases total).
This changed regression evidence requires a new frozen-SHA independent review;
no unchanged failed run is rerun, and #531's actual PG acceptance remains deferred.
