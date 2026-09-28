# C13 second local increment review

Read-only independent code/test review. Not formal C13 acceptance or module completeness. Product source was not edited.

## C03/C05/C06 and policy

Static scope: rail stale-quote supersession under order lock; attraction pending-quote resolution binding and API propagation; engineering ride CNY guard before source selection/creation; policy environment scope bound into lifecycle digest.

Ran new 6 C03/C06 +12 C05 +34 policy cases in one isolated SQLite process with `-p no:cacheprovider`. Initial result **49 passed /3 setup errors**; `c03-c05-c06-policy-junit.xml` retains results. Three API setup errors were caused by temporarily incomplete local frontend materialization. After root restored missing directories, independently reran only these 3 API cases: **3/3 passed**, `api-setup-recheck-junit.xml`. No application or fixture weakening was made. Thus all 52 existing cases passed, but the independent additional first-change probe below found an uncovered defect. All 34 policy cases passed. Policy environment scope defaults DEV/TEST and rejects malformed scope; no blocker found in that increment.

### C13-LOCAL-003 — first attraction change still accepts an old unbound confirmation

Independent test `probe_c06_first_change.py` reproduced:

1. Book an attraction, use ordinary admin UNKNOWN → CONFIRMED reconciliation before any change quote exists.
2. Create and execute first date change.
3. Replay previous unbound confirmation evidence, old supplier reference and old voucher without quote_id.
4. Actual: first pending change is confirmed using the old evidence. Expected: refuse without mutating order/capacity/history.

The original guard only required quote_id after APPLIED/FAILED quotes already exist. That did not cover prior ordinary reconciliation. `c06-first-change-probe-junit.xml` records the failing independent probe.

Resolution: implementation now requires quote_id whenever a pending change exists; ordinary non-change UNKNOWN reconciliation remains supported. Reviewer independently executed the unchanged probe plus all seven final fencing cases: **8/8 passed**, `c06-strict-fixed-junit.xml`. C13-LOCAL-003 is closed for this local frozen increment. Existing affected fixture calls now supply their actual quote identity; no rule bypass was added.

## C04 appeal increment

Reviewed frozen `reviews/c04/MANIFEST_ROUND2.json` scope: `appeal`, `review_appeal`, routes and new tests. Independent SQLite execution **26/26 passed**, JUnit `rental-appeal-junit.xml`, with cacheprovider disabled.

Checks: appeal nulls actionable amount and sets DISPUTE_HOLD; previous amount remains historical; reviewer excludes owner/maker/all previous decision-makers; immutable decision history links supersession; old versions and conflicting replay rejected; concurrent reviewers yield one accepted result; precommit append failure rolls back; funds remain untouched. No remaining blocker found in this limited increment.

Historical idempotent responses still return original decisions, by design. The C11 handoff explicitly requires latest case version and state before any future money action. This batch does not implement or validate such execution; no deposit/PSP/tenant/provider authenticity claim is made. Route tests override principal and do not prove complete production authentication.
