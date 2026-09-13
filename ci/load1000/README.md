# DEPTH48 cumulative 1000-user acceptance

Authorized scope: 1000 cumulative synthetic consumer accounts, distributed over
HOTEL, FLIGHT, RAIL, RIDE, RENTAL and ATTRACTION. This is not a request for 1000
simultaneously connected users. The runner uses the existing isolated HTTP
runtime and Chromium; no request targets Hong Kong or Production.

Canonical business source: main commit 286e294d92df4b7d1c0073116a8e628734abec6c,
application tree 3025b2b6b36ea9211da561a4631f304216de9d90,
1325 files, SHA256 d90a9e26c3a64b98009aaf170056f4b3acfa6acebd41baaed276b7baf17c6925.
No application files are changed. Every run verifies the full source before and
after execution; the runtime verifies each file before startup.

The existing six-module browser suite and hotel free-change scenarios run first
against a fresh disposable database. Their accounts do not count toward 1000.
The cumulative run uses a second new database, with stages of 6, 54, 240, 700
users and maximum concurrent journeys of 1, 2, 4, 8 respectively. A failed
journey stops further scheduling; in-flight journeys finish and retain output.
All users register separate accounts, enter through the consumer UI, create two
synthetic travelers, search/book/pay/refund through the UI, replay the refund,
and view the same order through consumer/supplier/admin pages and refreshed APIs.
An independent read-only SQL audit checks unique ownership, order/payment/source
bindings, capture/refund lineage and paired money entries for completed orders.

Save per-user raw results, HTTP status/latency observations, session and CI IDs,
source fingerprints and raw runtime/browser logs. Save screenshots for the first
six users, every 100th user, and failures. Do not archive credentials or database
files. All state directories are new and removed after evidence extraction.

Limits: SQLite, simulator inventory/payment/fulfillment, GitHub-hosted resource
limits, mobile web viewports only. This does not certify HK image performance,
1000-user concurrency, PostgreSQL browser E2E, official hotel content completeness,
native devices, the sealed Node gate or final release. Advanced change scenarios
are assessed by the separate preflight, not every cumulative user.
