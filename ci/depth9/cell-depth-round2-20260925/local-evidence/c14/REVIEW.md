# C14 Round 2 — independent rules review

Status: IN_PROGRESS, design review only pending implementation hashes. No formal C14 organizational verdict, legal certification or deployment approval. This subagent is not evidence that the formal Lite reviewer service is installed or running. PR #247 remains untouched.

## Scoring boundary

The owner's existing internal pre-supplier/pre-PSP scope and weights control: main flow 30, exception/compensation 30, cross-domain authoritative facts 20, role/end-user journeys 10, automated evidence 10. Do not replace this with an unannounced equal-weight score. A 0–4 rubric may supply evidence anchors within those weighted dimensions; the weighted total is an evidence-based maturity assessment, not a literal percentage of all possible work completed. Independent C13 owns quality scoring.

- Missing real supplier/PSP access, a formal C13 Runner, and production load execution do not reduce unrelated internal business scores; record these separately.
- A source file, assigned task, observed heartbeat or an assistant's review is not proof of persistent formal team execution.
- C13/C14 formal organizational services remain a separate design/implementation/runtime status, not inferred from this technical review.
- Evidence must name requirement scope and exact source. An unchanged accepted test may be retained, but no old global PASS transfers to changed behavior.
- UNKNOWN cannot be invented as zero capability or as PASS. Scores require a stated source/evidence basis; requirements with missing evidence remain visible.
- Suggested anchors: 0 not evidenced; 1 specified or partial source; 2 implemented with isolated developer evidence; 3 fixed-source independent boundary evidence; 4 complete agreed internal requirement matrix, integration and repeatable operational recovery evidence. Source counts and test counts alone cannot grant 4.

## C05 cancellation contract

Required single source chain: versioned search policy -> explicit consumer acceptance of its hash -> immutable booking snapshot -> cancellation quote and execution using the accepted snapshot. No authoritative approved cancellation values were found in the inspected context; existing 24h/8400/13400 and zero-fee behavior are contradictory implementation facts, not approved policy.

Real operation remains HOLD until authoritative cancellation rules are approved and bound. Isolated policy fixtures may exercise the complete mechanism but must be labelled synthetic and environment-limited. Legacy orders without accepted terms cannot silently inherit a new policy. Later supplier/policy changes must not rewrite prior consent. Timing, timezone, modification effects and existing-order applicability must be explicit in a future approved rule.

## C04/C11 deposit and damage boundary

Design received from C04: fixed server-owned synthetic source contract, consumer acceptance of source hash, obligation activation, full order-locked evidence chain, current adjudication resolver. Design received from C11: dedicated RENTAL_DEPOSIT identity/root, isolated authorization evidence, current-case/version/hash revalidation before bounded capture/release, deterministic keys and rejection of generic-entry bypass.

Required boundaries communicated to both implementers:

1. ACTIVATED means consumer accepted an obligation; it is not authorization, collection or money evidence.
2. Customer contract acceptance cannot substitute for independent disputed-case adjudication. A supplier cannot grant either customer consent or capture authority.
3. C04 records case facts; C11 alone owns deposit authorization/capture/release and accounting facts. Rental rent/change roots cannot stand in for deposit authority.
4. Resolve latest case, decision, owner, payee, currency, version and hashes under compatible order locks. Historic idempotent response is not current actionability after appeal.
5. Expired fixture policy can permit release of the remaining balance of an already existing authorization only. It cannot permit new authorization, capture, increased obligation, or resurrection of revoked source authority.
6. UNKNOWN money state must fail closed without speculative reissue; that safe refusal alone does not prove full unknown-outcome recovery completeness.
7. Fixture amount caps, 24h expiry and synthetic vehicle/payee are engineering assumptions only; real source, supplier proof and contract remain unapproved. Preserve ISOLATED_CONTRACT_FIXTURE and external_live=false throughout resolvers and responses.
8. Old cases without accepted obligation binding stay ineligible for deposit settlement. No retroactive attachment or rewriting of past money history.

Awaiting implementation file identities and source review. No product source, remote repository or formal review-system implementation was changed by this reviewer.


## Preliminary source inspection (not frozen acceptance)

Inspected the new C05 cancellation_policy/service/refunds and C04 deposit_authority/C11 rental_deposit_money while their authors were still developing. Default C05 resolver returns no policy; new booking requires the search-derived terms hash and freezes accepted terms. Refund reads the frozen policy; missing old booking policy remains HOLD. Synthetic policy loading calls environment_allowed, which only permits local/test/demo. No approved commercial tariff was invented in this inspected version.

C04 distinguishes consent activation from money authority and binds a complete synthetic source/terms hash. C11 resolves source and current decision under the order transaction, creates a separate deposit identity on the existing money graph, and takes no caller amount/payee/currency. Positive award rechecks source expiry, while zero-award release may use expired source only with an existing authorization. Generic movement entry requires a transaction-local verified scope. No real PSP adapter is introduced.

One evidence-semantics correction was sent to C05: consumer booking acceptance should not be labelled source COMMAND_CENTER, since no Command Center policy approval or dispatch is established by that event. Suggested accurate C05_BOOKING_CONSENT source.

Implementation identities, final refusal tests and C13 review remain pending. No preliminary source observation is a passing test result or higher module score.


## Frozen C04/C11 deposit increment review

Latest C04 four-file and C11 six-source manifests were independently SHA256-checked; all matched. Exact identities, plus the statically inspected consumer deposit view, are in DEPOSIT_FINAL_BINDING.json. This supersedes the initial C04_BINDING.json for this increment while preserving history.

Normal no-damage return / proven refunded cancellation now has an independent closure fact and C11 release path. Any damage case prevents using that shortcut; finalized return prevents new claims. No fictitious zero-damage case is created. Expired but unaccepted proposals may renew with a new hash and fresh consent; accepted source cannot renew. Existing authorization is required for money release, and positive capture cannot borrow the expired-source exception.

No rules blocker was found for this bounded isolated mechanism. Real contract/supplier/media/PSP authority is still unapproved. Accepted-source amendment/revocation, later booked-money appeal compensation, full recovery and cross-end evidence remain separate obligations. This record is not a formal C14 verdict or a complete internal100% claim.


## Frozen C05 mechanism review

The author's FROZEN_FILES.json contained 31 files; all 31 local hashes matched when independently checked. Exact list is retained in C05_FINAL_BINDING.json. Hash coverage is not a claim that every line/test was independently quality-validated.

Scoped source/consumer/native review found no rules blocker for the isolated mechanism: no configured source means HOLD, explicit consumer acceptance binds the quoted policy and booking snapshot, new refund uses that snapshot, and old unbound orders cannot silently adopt new fees. Booking evidence now uses C05_BOOKING_CONSENT, correcting the earlier ambiguous Command Center label.

Native requires separate policy consent tied to the actual quote hash; browser requires explicit checkbox acceptance. Zero refund due ends in CANCELLED/NO_REFUND_DUE with refund_performed=false and no money receipt, rather than falsely reporting money returned. Existing completed refund history can replay read-only; pending execution remains bound to its original policy snapshot.

The earlier internal contradiction between search's fixed late fees and unconditional zero-fee refund is addressed by a single accepted-policy mechanism. This does not approve any real commercial tariff. The supplied fixture remains opt-in, synthetic and local/test/demo-only. Real source and contract authority remain HOLD. C13 independently determines tested quality and any score change; this review does not claim native-device execution, official Lite operation, global C14 PASS or deployment approval.
