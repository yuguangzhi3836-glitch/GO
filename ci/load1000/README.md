# DEPTH48 pagination repair regression

This branch starts from canonical main 286e294d92df4b7d1c0073116a8e628734abec6c.
The candidate application identity is fixed in ../admin-pagination/CANDIDATE.json.
Only the admin operations route and shared admin renderer differ from deployed
DEPTH48. CURRENT_HK_RUNTIME.json continues to describe the installed version.
No topology, migration, runtime dependency or Control Plane change is included.

The user requested fixing pagination and exact-order lookup before continuing
acceptance. SQL/HTTP tests seed 125 synthetic orders/refunds in EACH of six
verticals. They verify complete pages, equal-time ordering, late order lookup,
independent refund pagination, ride/rental scope, invalid bounds and admin roles.

The existing isolated browser preflight runs against this new fixed source.
Then 1000 cumulative synthetic consumers run in stages 6/54/240/700 with
concurrency 1/2/4/8. All consumers register separate accounts, enter the actual
consumer UI, search/book/pay/refund, replay refund, and view the same order in
consumer, supplier and admin surfaces. The admin uses the new exact-order UI.
Errors stop scheduling, retain in-flight attempts and preserve the failing role's
screenshot, visible text and sanitized operations response.

After the journeys, a real admin browser traverses ALL order/refund pages,
checks unique complete coverage, previous/next boundaries, oldest/latest exact
lookups, four viewport widths, no-result/reset and a synthetic 503/retry.
An independent read-only SQLite audit checks every capture/refund and money pair.

PR60 and Run34751390306 remain original failed-run history: 300 complete,
8 admin-visible-order failures, 692 unattempted. Their results are not added to
this candidate's count. Full source bytes/modes are verified on fresh CI checkout
and again after execution. The actual checked-out commit and event merge SHA are
recorded separately.

Limit: this is cumulative isolated SQLite/Chromium regression, not the user's
separate target of peak 1000 simultaneously active users on HK-STAGING.
No Hong Kong endpoint, credentials, business database or Production is used.
It does not certify HK capacity, PostgreSQL browser E2E, native devices,
official hotel content completeness, Sealed Node or final release.
