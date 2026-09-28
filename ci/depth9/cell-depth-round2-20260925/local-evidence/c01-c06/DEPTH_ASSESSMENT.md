# C01–C06 evidence assessment, 2026-09-25

Read-only assessment baseline: PR #246 `7a290b2` (root reports five successful CI gates). New local C05 cancellation work is a successor increment and is not retrospectively counted as accepted baseline evidence. Integer scores are evidence grades, **not completeness percentages**: 0 no evidence; 1 design/local fragment; 2 partial implementation; 3 core verified; 4 complete agreed-scope closure. External supplier/PSP connection, production capacity and formal runner installation are excluded from these internal grades and do not cause deductions.

| Cell | Dimension | Grade | Source/test evidence | Internal gap preventing grade 4 |
|---|---|---:|---|---|
| C01 | Functional closure | 3 | `application/src/go_hotel/services/hotel_change_policy.py`; `application/tests/test_depth43_hotel_change_trips.py` | Hotel contract/changed dates/original funding invariant map not fully reconciled to one final integrated candidate. |
| C01 | Permissions/data integrity | 3 | `test_v70_next_c01_authorization_replay.py`, `test_c01_hosted_fare_value_integrity.py` | New fare-consent integration requires final cross-entrypoint review; media revoke/import races not fully mapped. |
| C01 | Exception recovery | 3 | `test_v70_r4_c01_unknown_episode.py`, `test_v70_next_c01_unknown_funding.py` | Complete abort/commit/recovery matrix across booking, date change and refund remains unproven. |
| C01 | Cross-end experience | 3 | `ci/journey-v2/browser.mjs`, `test_hotel_direct_review_ui.cjs` | Final successor browser evidence must cover new consent paths and failed/expired quote handling. |
| C01 | Continuing operations | 2 | `test_hotel_partner_media_publication.py`, hotel evidence chain and registration review sources | Ongoing review queues, stale media/terms monitoring and recovery-owner operating evidence are not fully closed. |
| C02 | Functional closure | 3 | `flight/changes.py`; `test_v70_round2_c02_partial_party.py`, `test_v70_next_c02_coupon_plan.py` | Final multi-segment/partial-party state coverage ledger incomplete, despite retained focused coverage. |
| C02 | Permissions/data integrity | 3 | `test_v70_r6_c02_partial_party_authority.py`, `test_v70_r3_c02_coupon_authority.py` | Need full mapped identity/fare/coupon authority matrix on integrated source. |
| C02 | Exception recovery | 3 | `application/tests/flight/test_c02_three_end_change_quote.py`; retained #240 PG process evidence | Recovery tests retained, but all frozen candidate bindings and coverage denominators not yet reconciled. |
| C02 | Cross-end experience | 3 | Flight journey in `ci/journey-v2/browser.mjs` | Full negative/partial-party post-sale browser cases not all represented by the happy-path journey. |
| C02 | Continuing operations | 2 | `services/flight_change_resolution.py`; scoped recovery evidence | Long-running exception ownership and operating diagnostics need a complete evidence map. |
| C03 | Functional closure | 3 | `rail/service.py`; `test_depth22_rail_resolution.py` | Published fare and every sequential change/refund combination not fully enumerated. |
| C03 | Permissions/data integrity | 3 | `test_c03_c06_change_quote_fencing.py`, `test_next_depth_c03_payment_inventory_races.py` | New stale-quote fencing is tested; complete permission and cross-order money conservation map remains open. |
| C03 | Exception recovery | 3 | `test_depth22_rail_resolution.py`, `services/rail_change_resolution.py` | Formal full crash-point coverage list for sequential changes and inventory release remains incomplete. |
| C03 | Cross-end experience | 2 | `test_sprint3b_rail.py`; rail browser booking path | API and basic browser coverage; ambiguous changes and recovery to admin/supplier/consumer not fully demonstrated. |
| C03 | Continuing operations | 2 | Rail resolution journal and capacity ledger tests | Pending queue ageing, reconciliation ownership and recurring operating checks not fully evidenced. |
| C04 | Functional closure | 3 | `mobility/rental/damage.py` and `test_rental_damage_disputes.py` (other owner's increment) | Deposit acceptance/hold/release integration remains the other owner's round-two scope. |
| C04 | Permissions/data integrity | 3 | `test_rental_damage_disputes.py`; rental receipt tests | Full deposit→damage→decision→money binding matrix pending, not reimplemented here. |
| C04 | Exception recovery | 3 | Rental change/reconciliation sources; dispute crash/retry tests | Competing adjudication and deposit recovery cross-product matrix requires final evidence. |
| C04 | Cross-end experience | 2 | Rental browser booking path; dispute API tests | Deposit and dispute visible consumer/admin flow not yet covered by baseline complete browser journey. |
| C04 | Continuing operations | 2 | Case events and damage evidence journal | Ageing cases, evidence requests and operational escalation full closure remains pending. |
| C05 | Functional closure | 2 | `ride/service.py`, `ride/refunds.py`; baseline search charged late fees but refunds used zero | Confirmed cancellation contract contradiction is the round-two fix; new policy source is deliberately unavailable by default. |
| C05 | Permissions/data integrity | 3 | `test_c05_engineering_currency.py`, C05 episode tests | Booking-accepted cancellation provenance was absent at baseline; must be frozen and enforced before payment/refund. |
| C05 | Exception recovery | 3 | `test_v70_r5_c05_concurrent_unknown.py`, `test_depth33_mobility_refund_consent.py` | Complete new-policy pending/refund/clock-boundary recovery integration pending successor tests. |
| C05 | Cross-end experience | 2 | `booking-travelers.js`, `app.js`, ride browser path | Baseline UI did not show/accept cancellation terms; successor UI and real browser fixture acceptance required. |
| C05 | Continuing operations | 2 | Ride UNKNOWN episode and flight-sync evidence | No approved policy source lifecycle existed; explicit HOLD and immutable historical policy inspection required. |
| C06 | Functional closure | 3 | `attractions/service.py`, `test_sprint3d_attractions.py` | Full nonrefundable/change/closure/redemption combinations not entirely reconciled. |
| C06 | Permissions/data integrity | 3 | `test_c03_c06_change_quote_fencing.py`, `test_v70_r5_c06_raw_payload_binding.py` | Strict change quote ID fixes confirmed stale-event issue; complete ordinary UNKNOWN episode and operator-role matrix needs reconciliation. |
| C06 | Exception recovery | 3 | `test_depth23_capacity.py`, quote fencing and voucher replay tests | Repeated ordinary recovery episodes and every failure-after-commit point not fully documented. |
| C06 | Cross-end experience | 2 | `test_sprint3d_attractions.py`; attraction browser booking | Admin correction, invalid validity window and stale quote refusals not all demonstrated in browser journey. |
| C06 | Continuing operations | 2 | `test_c06_internal_policy_registry.py`, `test_next_depth_c06_supplier_validity.py` | Internal policy withdrawal/update and operational queue evidence need final integrated audit; no external certification deduction. |

All paths without a prefix are under `application/src/go_hotel/` for source or `application/tests/` for tests. C04 scoring references other-owner evidence only; this agent does not modify that module. No grade 4 is assigned by inference from file existence or overall CI success. The root/C13 acceptance framework may use a separate weighted score; these five dimensions supply evidence and must not be converted into a completion percentage.
