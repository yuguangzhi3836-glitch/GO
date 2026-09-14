# C11 callback outcome classification — candidate review

Anchor: `main fef9c748adb77d37ba5d4dc4fa4662eb668303a1`.

Status: the new post-commit callback gap is **BLOCKED / reproducible**, with
2 failing sync/async cases. The existing completion-guard scope remains 16/16
passing. This document changes no runtime behavior and does not sign C14/C13.

## Observed failure

The real `SqlRepository` atomically claims the key. The callback then commits an
isolated SQL row and raises. `api/idempotency.py` catches every `Exception` and
releases the unfinished claim. A second request with the same key commits a
second row. Both modes produced `effects_committed=2`, `claim_retained=false`.
The probe uses only its own SQLite database, with no payment provider or live
business records. It proves a generic duplicate-effect path, not an observed
real-money incident.

## Proposed contract boundaries

| Proven boundary | Retry treatment | Proof required |
| --- | --- | --- |
| Validation completed before any domain or external mutation | Retain safe retry/release behavior | Explicit callback contract; exception class alone is insufficient |
| All local writes rolled back, no external side effect attempted | Safe retry permitted | Known transaction boundary and rollback outcome |
| Commit or external side effect occurred; response construction or later audit failed | Keep claim; reconcile/replay | Persisted operation/resource identity and canonical outcome |
| Commit acknowledgement or provider outcome unknown | Keep claim; reconcile | Do not re-execute until outcome is resolved |

Do not infer safe release solely from `ValueError` or HTTP 4xx. In the current
source `flight/service.py::execute_change` commits authorization-requested
state, calls `vertical_money_bridge.prepare_adjustment`, and can subsequently
raise `ValueError('FLIGHT_CHANGE_AUTHORIZATION_RELEASED_REQUOTE_REQUIRED')`.
The API wrapper translates domain `ValueError` to `HTTPException`. Both types
can therefore be seen after committed state changes.

## Concrete call-site review

| Call site | Observed boundary | Next implementation scope |
| --- | --- | --- |
| `FLIGHT_CHECKOUT` | Authorization state committed before transaction bridge, followed by a second transaction | Identify resumed operation and reconcile failures after first commit |
| `FLIGHT_EXECUTE_CHANGE` | Authorization-requested commit precedes adjustment and later validation | Explicitly classify post-commit exceptions as uncertain; preserve pre-commit validation retries |
| `FLIGHT_CREATE_ORDER` | Order creation completes before a separate vault-release evidence transaction | Late evidence failure must not turn successful creation into fresh creation |
| `RAIL_CREATE_ORDER` | Same separate order and vault-evidence transaction pattern | Same classification review with C03 |
| `RIDE_CREATE_ORDER`, `RENTAL_CREATE_ORDER` | Same separate order and vault-evidence transaction pattern | Same classification review with C04/C05 |

A source scan found 37 syntactic `run_idempotent`/`run_idempotent_async` call-site
matches under `api/routes`; this is an inventory count, not proof that all 37
have been individually reviewed.

Next assigned task: first introduce an explicit contract for **proven no-side-
effect failure versus uncertain outcome** in `FLIGHT_CHECKOUT` and
`FLIGHT_EXECUTE_CHANGE`, with C02 review of the operation boundaries. Keep
ordinary proven validation retries working, add after-commit failure and
reconciliation tests, then extend the reviewed contract to the remaining calls.
The shared wrapper remains unchanged in this round so that an unreviewed global
retry-semantic change is not silently introduced.
