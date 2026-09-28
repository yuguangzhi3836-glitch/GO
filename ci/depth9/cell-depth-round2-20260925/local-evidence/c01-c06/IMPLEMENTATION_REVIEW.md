# C05 candidate implementation review

Baseline: PR246 at 7a290b2. Frozen implementation paths and SHA-256 values: FROZEN_FILES.json (31 paths). This is a development candidate, not deployment authority or an assertion that every C01–C06 module is complete.

## Accepted-policy chain

Search resolves an explicitly configured isolated source, binds its content to offer, itinerary, price and currency, and exposes the complete versioned terms. Web and native consumers require a separate affirmative acceptance of that current hash. The booking transaction verifies it and records immutable booking consent. Refund quotes and execution consume that snapshot, including its stated time basis, rather than later catalog policy. Changed terms or cancellation cutoff require a fresh refund confirmation.

No real tariff has been approved or invented. Without a source, search says unavailable and a new booking is rejected atomically. Legacy bookings missing accepted policy remain visible with a HOLD cancellation projection; new cancellation and payment attempts are refused. Already completed positive refunds retain their historical result and are never dispatched again by replay.

The only included source is a clearly marked, opt-in isolated synthetic fixture for engineering use. It is allowed only in local/test/demo environments. Tests explicitly install it and carry the searched acceptance hash; there is no global autouse consent. The acceptance runtime explicitly installs the engineering fixture while the browser still performs the consent dialog.

## Zero-refund cancellation

A valid full-fee cancellation completes as native CANCELLED and refund-row NO_REFUND_DUE, with refund_performed=false and no zero-valued money movement. Its payment truth remains captured/PAID, and Trips and later generic reprojection must not describe a completed refund. Replay returns the same factual result. C11 additionally aligns payment ingress and terminal supplier protection.

## Client compatibility and intentional gates

RIDE callers now need a currently accepted cancellation_policy_hash; old silent-consent booking calls deliberately fail closed. Affected engineering fixtures, API lifecycle helpers, agent test reservations and browser journeys were migrated explicitly. Native consent is bound to the selected offer and itinerary; a change clears it. Missing-policy pending orders cannot resume payment. Web datetime-local input is converted by the browser to an explicit ISO instant, while API callers supplying naive times are rejected. Cutoff conditions are displayed in days, hours or minutes when exact, falling back to seconds.

## Validation

- Expanded existing RIDE references: 217 passed, no skips, c05-all-ride-final.xml.
- Full frontend contract suite: 323 passed, no skips, c05-all-frontend-final.log.
- Final human-readable cutoff display adjustment: 41 passed, c05-final-display-contracts.log.
- Independent C13: 19 policy cases plus the original full-fee reproducer and cross-end no-refund truth probe, 21 passed; core hashes stable before/after. The independent probe checks API, DB, money absence, Trips, later reprojection, snapshot labels and replay. C13 separately reports C11 ingress/terminal 3 passed.
- C14 independently matched all 31 manifest hashes and stored its limited rules opinion at ../c14/C05_FINAL_BINDING.json. This is not approval of real commercial fees or deployment.

Earlier failed regression artifacts are retained. They exposed legacy fixtures without explicit source/acceptance, an evidence-list expectation missing the new consent event, and the genuine zero-money cancellation defect. Assertions were preserved while fixtures and implementation were corrected.

The native source contract tests ran; a complete native project typecheck was not run locally because native dependencies are absent. Root's unified CI must execute that gate. No physical-device, live-provider, real-money, deployment or remote mutation was performed by this subagent.

## Module evaluation

DEPTH_ASSESSMENT.md records the requested C01–C06 five-dimension integer evidence ratings against the baseline, with concrete paths and remaining internal gaps. Those numbers are not completion percentages and do not deduct for excluded external integrations. C04 remains owned and developed by its designated team.
