# C11 isolated rental deposit closure and C05 payment source guard

Scope: pre-real-supplier/PSP engineering fixture only. The existing C11 Root → FactBinding → Intent → Movement → Ledger remains the sole money authority. No production installation, merchant credential, supplier call or real payment was used.

## Implemented

- C04 server-owned versioned obligation plus explicit consumer consent is resolved under the rental order lock. It is not itself an authorization. C11 creates a distinct RENTAL_DEPOSIT root keyed by obligation identity; rent and fare-change roots are never reused.
- Only authorized admin operations can create isolated authorization. Caller amount/payee/currency fields are not accepted. New authorization is refused once the vehicle is returned/cancelled; existing evidence may be observed.
- Independent current C04 decision/version/hash determines damage capture; unused authorization is released in the same transaction. Retries use deterministic source-bound operation keys. Open appeal prevents settlement.
- Normal no-damage return and proven original-rent cancellation use a distinct C04 closure fact. Ordinary release never manufactures a zero-value damage claim and cannot bypass any damage-case workflow. Expired source permits release of an existing proven authorization, not new authorization or capture.
- Generic Movement ingress is fenced by an internal verified-source session scope. It cannot use an admin-supplied amount/evidence string to bypass the C04 source/decision checks. No new external callback ingress exists for this business type.
- Unknown/missing authorization receipts, orphan roots, source/party mismatch, malformed money graph or inconsistent capture ledger return HOLD/reconciliation. The owner-checked money view withholds balances as null when facts are not provable; it never infers money from ACTIVATED consent.
- C05 accepted cancellation snapshot is now required by both the canonical payment source resolver and direct checkout bridge, including existing unexecuted intents. Historical orders/records are not rewritten. The supplier fulfillment terminal guard also recognizes C05 no-refund-due CANCELLED orders, rejecting late confirmation.

## Concurrency / atomicity

Lock order is rental order → deposit root / intent → money rows. All C04 resolver checks and C11 writes use one transaction. SQLite uses existing BEGIN IMMEDIATE; PostgreSQL uses row locks. The generic deposit movement guard reads only the same-session verified scope, avoiding a reverse intent→order lock.

Tested: competing authorization attempts, competing settlement/release retries, rollback after capture before release, current decision refusal after appeal, stale source/decision, corrupt root/movement/ledger, expiry and role denials. These are local SQLite results; PostgreSQL and process-kill deposit tests remain separate acceptance evidence, not implied by SQLite thread tests.

## Routes

- Owner/admin GET `/v1/mobility/rentals/orders/{order_id}/deposit-money/{obligation_id}` with expected_revision/source_hash.
- Admin POST corresponding `/internal/v1/.../authorize`, `/settle`, `/release`; strict request schemas forbid amounts and payees.
- `api/routes/rental_deposit_money.py` exports `router`; root agent integrates `main.py`.

## Verification artifacts

- `deposit.txt`, `deposit-junit.xml`: 82 passed (28 C11 + 54 C04) scoped deposit/claim/closure tests, including original rent refund and independent deposit release.
- `shared.txt`, `shared-junit.xml`: 55 passed across three C05 payment-source/terminal callback guard tests, policy acceptance, consumer payment source boundary, supplier money projection and existing six-vertical checkout.
- `SOURCE_SHA256SUMS.txt`: six frozen implementation files for independent C13/C14 review. Main/router integration belongs to root's final manifest.
- `ASSESSMENT.md`: requested C07–C11 five-axis scores with per-axis evidence and remaining gaps; scores are not percentages.

## Remaining limits

- Real contract/payee/inspection authenticity and PSP authorization/capture/void certification are HOLD. Synthetic fixture labels remain explicit.
- Post-settlement appeal creates a new liability question; this round safely refuses to apply a new award on the old settled authorization. A separately bound compensation/refund workflow is not implemented here.
- UNKNOWN remains safe HOLD; automated external reconciliation is not added and cannot be counted as full recovery.
- Full admin UI, three-end/mobile visual acceptance and deployed operations observation remain separate. Current money routes and isolated fixtures are not that evidence.
