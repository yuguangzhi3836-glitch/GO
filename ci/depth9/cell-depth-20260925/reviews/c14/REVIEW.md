# C14 independent rules review — PR #246

Status: FINDINGS AND ACCEPTANCE CRITERIA; NOT FORMAL C14 PASS.

Candidate: `6acf9fdcde4b208b12a8c9d57ef74497e745faae`  
Application tree: `9cc68fa3a805f9f0df09b937a7c2df618cf6795f` (parent-provided binding).  
Compared main: `aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0`.

Read-only review. No product implementation, PR changes, deployment, Hong Kong or Eason access, real supplier/PSP invocation, or funds movement. #247 LiteV2 organizational implementation remains with the existing Eason line; no parallel C13/C14 system is proposed.

## Independently verified source binding

Each of the five files was fetched at exact PR #246 SHA and its blob compared to the earlier main read. All five are identical.

| File | Blob SHA |
| --- | --- |
| application/src/go_hotel/autonomy/definitions.py | 4bc7bdd8158d7fe2618f41066464766bb4e1eaef |
| application/src/go_hotel/autonomy/action_control.py | 0679c035718801c387e6c424426ce3501d4382c6 |
| application/src/go_hotel/autonomy/release.py | 1d5bb7efd29697c554b878a2777b6e5661b83a5e |
| application/src/go_hotel/autonomy/operations.py | fafc2e9391fa280ce42715f2468c27291c336b46 |
| application/src/go_hotel/autonomy/durable.py | f133f861ebd933c851a16083ae8c47ee88866e67 |

## Findings and acceptance criteria

### C14-OPS-01

Source: `application/src/go_hotel/autonomy/operations.py` — observation_handlers/application_executor.

All 14 default operational handlers only observe aggregate state; not development execution or business remediation.

Acceptance: Keep observation status separate from owned business actions and closure evidence.

### C14-GOV-02

Source: `application/src/go_hotel/autonomy/definitions.py` — C12 capabilities.

Explicit operational scope mapping absent for new preflight/capacity/recovery responsibilities.

Acceptance: Responsibility implementation belongs to existing #247/Eason line; do not add parallel review system.

### C14-REL-03

Source: `application/src/go_hotel/autonomy/release.py` — ReleaseEvidence/authorize_promotion.

Qualification helper accepts any distinct registered releaser cell, bool flags, nonempty candidate ID, empty evidence list. Not proof of actual deployment bypass.

Acceptance: Must never substitute for human Command Center deployment authorization; C14 cannot grant deployment.

### C14-POL-04

Source: `application/src/go_hotel/autonomy/action_control.py` — LegalPolicyRule/AILegalPolicyRegistry.review.

Rule object has no approval provenance/version/effective interval/revocation lifecycle; review has no time parameter.

Acceptance: Unapproved real policy stays HOLD; no invented law or claimed legal completeness. Version/provenance/validity must be enforceable for real operational rules.

### C14-IND-05

Source: `application/src/go_hotel/autonomy/durable.py` — _authorize lines 323-334.

C14_REVIEW is a deterministic gate event attributed to submitter; it is not independent AI reviewer opinion.

Acceptance: Automated check and independent C14 opinion must not be conflated; implementation on existing owner-aligned review line.

The older main organizational context uses the Eason/workstation routing and a September 14 checkpoint. It is historical context relative to the owner's September 25 organizational decision. The parent reports #247 LiteV2 already aligns with that decision; this review does not duplicate or modify its implementation.

## C04 damage/deposit-dispute minimum boundaries

These are requested system behavior and engineering acceptance criteria, not assertions about any particular jurisdiction's law. They do not invent a supplier contract, dispute deadline, default liability, deductible, or consumer-consent rule.

1. Supplier can propose a damage claim with evidence, not unilaterally authorize deduction.
2. Evidence binds order, vehicle, pickup/return condition, amount/currency, contract-policy version and provenance; reject missing or mismatched evidence.
3. Customer challenge creates/maintains dispute hold; silence, timeout or supplier assertion alone is not acceptance.
4. Decision authority is separately authorized and scoped; supplier or claim creator cannot self-adjudicate; cross-tenant actors denied.
5. C04 records reasoned case decision and authorized amount only; C11 owns money instructions, execution facts, ledger and refund.
6. Payment facts must bind case, decision revision, order, operation key, amount/currency; no amount derived solely from callback assertions.
7. Duplicate same command returns prior result; conflicting payload, stale revision, replay and out-of-order completion rejected without double debit/refund.
8. Unknown external outcome remains unknown and reconciled; never speculative resend.
9. Appeal or reversal creates linked compensating decision; cannot erase old evidence or rewrite booked money truth.
10. Before real supplier/PSP integration, tests use synthetic contracts and isolated state; policy absence is explicit external HOLD.

Minimum rejection cases: supplier self-approval; customer cross-order/cross-tenant access; unbound evidence; unauthorized adjudicator; stale policy/decision revision; negative/excessive amount; wrong currency; duplicate/conflicting operation key; disputed case deduction; decision reversal racing payment; replayed callback; interrupted dispatch followed by uncertain result; appeal after booked payment requiring C11 compensation rather than rewriting history.

C04 owns the dispute's business facts. C11 owns money execution and accounting. C14 reviews rule/authority boundaries. C13 independently verifies behavior. Missing approved external policy is an explicit HOLD for real operation and must not block safe isolated engineering work with clearly synthetic policies.

## Evidence limits

No tests were run in this read-only pass. This is not a finding that the real deployment channel can be bypassed; release.py is an application qualification helper. No runtime liveness, official dispatch, C13 PASS, legal completeness, or deployment acceptance is claimed.

Ready for fixed-increment independent boundary review after the C04 implementation candidate and tests are frozen.

