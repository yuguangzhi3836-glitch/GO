# C04 round3 operational interaction increment

Whole-module denominator: NORMALIZED.json (30 REQUIRED obligations across seven categories); all fresh NOT_ASSESSED, historical PASS not transferred. It includes driver eligibility, supply/vehicle/insurance, supplier operations, recovery, scheduled ownership and post-settlement corrections even when not implemented. ACCEPTANCE.json was submitted before implementation and distinguishes the first five batch priorities. Checklist scope completeness/freeze is for root/C13 review.

## Implementation

New rental_operations router provides authenticated workspace and statement-based owner response/appeal, admin open/decision/appeal-decision/final-return-review. Statements contain server-derived actor, order, case and action, with a computed digest. They are ACTOR_STATEMENT_UNVERIFIED, not photos, supplier authentication or verified condition facts. The existing domain transaction persists the statement inside the actual business event atomically. A stale/unauthorized/rejected command leaves no standalone successful statement. The public raw-evidence API continues rejecting statement injection.

Workspace derives permitted actions from current authenticated principal and current case state; command endpoints independently enforce real role/domain guards. Current actor's durable command receipts permit readback after response loss. Shared UI uses those actions, binds version/source hash, requires explicit confirmation and writes no funds. Unknown response persists exact key/path/body in actor-and-order-scoped session storage, blocks new commands, and can re-read or retry the original. Receipt presence confirms a historical command, but UI renders latest workspace state. Historical response never becomes current monetary authority. Storage failure prevents initial dispatch.

Admin request adapter passes object body to existing ApiClient; consumer wrapper JSON-serializes once. This fixes a pre-freeze double-serialization finding from root. All dynamic text is escaped. Consumer mounts in existing rental detail and refreshes deposit/money record on C04/C11 events. Main/index/shared routing integration is owned by root; no duplicate shared app modifications here.

## Evidence and limits

- 60 backend tests passed, no pytest cacheprovider: new six operational HTTP/DB tests and 54 existing damage/deposit authority tests. New tests exercise complete owner→different checker→owner appeal→third reviewer, exact retry/different-body conflict, stale/foreign-owner/spoofed actor zero writes, final inspection statement, and injected audit rollback. Money table remains unchanged by C04 actions.
- Three Node adapter checks passed (consumer serialization/header preservation/read behavior and admin object body contract).
- Browser widget interaction tests supplied in ci/journey-v2/rental-operations-widget.mjs; local Chromium attempt failed before test execution because socket() was not permitted. No bypass attempted. This is NOT a browser PASS. C12 separately owns normal real-API browser journeys and screenshots; until those complete, cross-end evidence is pending.
- No real supplier, live PSP, deployment, funds or remote write by this agent. Scope still includes unimplemented whole-module operations and C11 post-settlement compensation; this batch is not module 100%.
