# CP11 DEPTH37 — Agent Transaction Gateway P0

## Objective
Make GO the protocol-neutral deterministic transaction layer that external AI systems can call without allowing any model or adapter to become an authority for inventory, payment, order, refund, supplier or identity truth.

## P0 surfaces
1. Universal Agent Gateway — one canonical transaction port.
2. MCP adapter — offer.search, reserve, commit, reserve.release, order.get.
3. A2A adapter — same five capabilities exposed through an Agent Card/skill surface.
4. Apple App Intents contract — Search, Reserve and Commit intents bound to purpose-limited authorization.
5. Agent Offer/Reserve/Commit contract — immutable offer/reservation/order identities, idempotent mutations, deterministic authority envelope.

## Constitutional invariants
- Search/query is never an inventory promise.
- Reserve is the only path that may establish inventory commitment and must delegate to the existing deterministic core.
- Payment components may not write inventory.
- Commit requires a valid reservation and payment truth; the Agent Gateway does not manufacture either fact.
- Reserve/Commit/Release are idempotent.
- Late payment success may not resurrect an expired reservation.
- External AI/model output is advisory/compute only, never transaction authority.
- Purpose-bound, minimum-necessary traveler authorization; adapters never receive the full personal travel vault by default.
- Official Direct remains first; authorized fallback is explicit, never silently relabeled as official.

## Current implementation state
- PASS: canonical Python contracts committed.
- PASS: protocol-neutral gateway committed.
- PASS: MCP adapter surface committed.
- PASS: A2A Agent Card/skill surface committed.
- PASS: Apple App Intents source contract committed.
- PASS: unit test source for common gateway invariants committed.
- HOLD: binding TransactionCore to the restored full parent runtime transaction services.
- HOLD: signed external-agent authentication/authorization provider binding.
- HOLD: Xcode/iOS native target integration and device build.
- HOLD: CI execution against restored full parent source and sealed Node/Python runtime.
- HOLD: external sandbox credentials / official provider interoperability testing.

## Release rule
This branch is DEVELOPMENT / ISOLATED ACCEPTANCE ONLY. It is not authority to merge, deploy, alter HK staging, alter RDS/Redis/Caddy, or enable real external-agent traffic.
