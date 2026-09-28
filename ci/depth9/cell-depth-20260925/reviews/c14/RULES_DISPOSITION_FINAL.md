# C14 limited rules disposition

**C05 real operation HOLD: displayed cancellation contract and executed refund terms disagree.**

Search offers 24-hour free cancellation / 8400 or 13400 late fee; refund quote always uses fee zero; booking freezes waiting/delay terms only. Reviewed operating-decision/state sources establish no Owner-approved cancellation rule. Neither existing source behavior may be promoted to an approved contract.

The one business rule to freeze is the **booking-accepted ride cancellation policy version**, including product/order applicability, cutoff clock/timezone and modification effects, free/charged conditions and calculation, and applicability to legacy orders. Actual values require authoritative approval; this review supplies none. Search, booking acceptance, persisted snapshot, refund quote and execution must consume the same bound version. Missing legacy consent requires explicit treatment, not retroactive rewriting.

Isolated engineering work may continue with real suppliers/funds disabled; the contract discrepancy remains unaccepted. The existing production guard only rejects prod/production, not every non-test environment; no installation or operational opening is authorized.

## Other inspected increment boundaries

- Versioned policies default to DEV/TEST, include typed environment scope in the full digest and reject cross-environment borrowing. Approval references still require trusted provenance validation before real use.
- C03 stale quote supersession and C06 exact pending-quote identity narrow acceptance without introducing fees or supplier authority.
- C05 currency restriction preserves fixed CNY prices rather than inventing exchange rates.
- C04 remains isolated adjudication; supplier evidence is unverified and funds remain for C11 review.

## Exact local bindings

| File | SHA256 |
| --- | --- |
| autonomy/action_control.py | f7e19ac1fcea318e98c0f5e288ff1231caed08b071a9350cfde6cd99ff07a44a |
| autonomy/types.py | a0aeb541030395f7191482b9df8ee85acb9764b8bb2094a47042e102d110dacc |
| autonomy/condition_evidence.py | 6ec835cd92019daf5443bb4a577b2224b12579850f53bd9e9945a6cad69b4903 |
| mobility/rental/damage.py | 03c9bfd8badff6d448fc49500d3eb44f99d45055de358cdabe12f5c0158102da |
| api/routes/rental_damage.py | 6636992f3220d1854000f6d4ca7c89ecb85f32975bb7e880d5885d7cb2a7334b |
| mobility/ride/service.py | 0eec9fdc9897e85a202638017abf4f5987834d3fd516f39b9f382ceb6000cb1b |
| mobility/ride/refunds.py | 191abb39c043d4def0fc9ef432565b92e71bd044ff35df99a686e0389ac40e36 |
| mobility/ride/flight_sync.py | 6d66fa1ae3da41d355c6feaeb62c27a253f6277c66f2edf6281f88ac40ed4808 |
| core/production_truth_gate.py | 7420017fed1c46fbde69da610cf50e4ff3ed2fe1b3f6ebfda64703d9fb6a2158 |
| rail/service.py | d1f6cf4719154db642cc2c8460d53dec99f3137c413336f7be50b592d1440078 |
| attractions/service.py | eb7c8679cc75d15bf72d57b1e6c5e9aebaea0c97792a41007d4e1d5f49ad07d7 |

Base #246: `6acf9fdcde4b208b12a8c9d57ef74497e745faae`. This is a local-byte scoped review pending frozen commit binding, not review of every modified module. No tests independently rerun, no formal C14 PASS, full legal certification or deployment approval. Prior review files remain historical records.
