# GO 当前工程检查点：DEPTH25

当前唯一控制母版为 V7.0（2026-08-31，含宪法与法律同步修订），SHA256 为 `877aa1d093d675155d20c4b6e424b70454ee89c9969f52810abfd5086d6db66d`。当前源码迁移头为 `0132_rail_runtime_field_widths`。

本检查点继承 DEPTH23、24 全部成果。当前交付入口见 `GO_DEPTH25_START_HERE.md`；最新实测及最终门禁见 `verification/current_build/depth25/CURRENT_BUILD_STATUS.json` 和 `FINAL_RELEASE_GATE.json`。最终发布仍为 HOLD，未部署。

以下 V6.1、Sprint、旧迁移头和旧 PASS 描述作为运行时及实施历史保留，不覆盖上述当前控制版本，也不证明本次交付已全面验收。

---

# GO Hotel Platform — V6.1 Current Control Baseline

Current controlling master: **V6.1 (2026-08-22)**.

Authoritative runtime version: `src/go_hotel/core/master_baseline.py`.
Current V6.1 commercial policy: `src/go_hotel/core/v61_commercial_policy.py`.
Current control tests: `tests/test_master_v61_*.py`.
Current cumulative database head: `0110_consumer_growth_official_direct_value`.

Historical Sprint documents below are retained as implementation history and do not override V6.1. See `CURRENT_CONTROL_VERSION.md`, `VERSION_DEBT_POLICY.md`, and `archive/evidence_history/root_legacy/GO_V6_1_VERSION_DEBT_CLEANUP_2026-08-22.md`.

# GO Hotel Platform - Sprint 1F

**Real Connector Framework + Connector Certification Harness + Timeout/Circuit Breaker + Reconciliation Jobs**

Sprint 1F extends the Sprint 1E resilience baseline without changing the existing Consumer booking API or domain contract.

## New in 1F

- Provider-neutral `HotelConnector` metadata/capability contract.
- `HttpConnectorBase` for contracted real supplier integrations.
- Connector registry; GO domains no longer import a concrete supplier directly.
- Deadline, bounded transient retries and per-connector circuit breaker.
- Retry of `book` only when the connector explicitly declares supplier-side idempotency capability.
- Automated certification harness: health, canonical search, prebook, booking idempotency and normalized status.
- Persisted connector certification and health results.
- Reconciliation worker that compares GO confirmed orders against supplier status without silently rewriting the ledger.
- `RECONCILIATION_MISMATCH_DETECTED` is appended to the immutable event/outbox chain on drift.
- Alembic `0003_sprint1f` migration.
- Internal connector ops endpoints and certification CLI.

## Existing public contract remains unchanged

`POST /v1/search/hotels` -> `POST /v1/offers/{offer_id}/prebook` -> `POST /v1/orders` -> payment -> internal confirmation continues to use the same Sprint 1C-1E contract. Only internal connector/governance endpoints were added.

## Run

```bash
pip install -e '.[dev]'
pytest -q
uvicorn go_hotel.main:app --reload
```

Docker/PostgreSQL:

```bash
docker compose up --build
```

Certification:

```bash
python scripts/certify_connector.py conn_mock_hotel
```

## Real supplier boundary

This baseline intentionally does **not** fabricate proprietary Lighthouse, Shiji, SiteMinder, Agoda, or other supplier request/response schemas. A real adapter is implemented from current supplier documentation + credentials + commercial authorization, then must pass the certification harness before traffic is enabled. See `src/go_hotel/connectors/provider_template.py` and `specs/connector_certification_checklist.md`.

## Workers

- outbox-worker
- recovery-worker
- reconciliation-worker

## Previous Sprint 1E guarantees retained

Concurrency guards, durable external-operation saga recovery, transactional outbox retry/DLQ, webhook dedupe and out-of-order protection remain intact.

## Sprint 1G - First Real Supplier Adapter
First supplier boundary selected: **SiteMinder booking-channel connectivity (Channels Plus / SiteConnect family)** because SiteMinder publicly documents booking-channel capabilities for property search, availability, pricing and reservation management.

This repository intentionally does **not** invent SiteMinder private sandbox endpoints or payload fields. Configure `.env.siteminder.example` from the current contracted partner documentation, then run:

```bash
cp .env.siteminder.example .env
# fill approved sandbox values
set -a && source .env && set +a
python scripts/certify_siteminder_sandbox.py
```

Until that command produces `passed=true`, the SiteMinder adapter is **not sandbox-certified** and must not receive production traffic.

## Sprint 1H - Supplier Onboarding / Activation

Sprint 1H adds the operational path from a contracted supplier connection to controlled traffic activation:

`Onboarding -> Credential Vault -> Property Mapping -> Sandbox Certification -> Activation Request -> 5% Canary -> Gradual Rollout`

Internal endpoints are under `/internal/v1/supplier-connectors`.

Credential values are write-only through the API. Reads return metadata/fingerprint only. The built-in `LOCAL_FERNET` provider is explicitly for development/test; production must bind the vault interface to managed KMS/HSM/secret-manager infrastructure.

A connector cannot activate unless it has an active credential set, an approved property mapping, and a linked passing certification. Suspension forces traffic rollout to zero.


## Sprint 1K
Adds deterministic prebook revalidation, provider quote locks, inventory hold semantics, quote expiry enforcement and booking consistency guards. Search prices are never silently promoted into payment facts; the connector prebook response is the final transaction revalidation boundary.

## Sprint 1L — Payment safety orchestration

The booking payment flow is now **authorize → supplier book → capture**. A definitive supplier booking failure triggers **authorization void**, not refund, because capture never occurred. Ambiguous supplier outcomes are reconciled before any void/retry decision. See `specs/sprint1l_payment_orchestration.md`.

## Sprint 1L — Payment safety orchestration

The booking payment flow is now **authorize → supplier book → capture**. A definitive supplier booking failure triggers **authorization void**, not refund, because capture never occurred. Ambiguous supplier outcomes are reconciled before any void/retry decision. See `specs/sprint1l_payment_orchestration.md`.


## Sprint 1M — Hotel Fare Runtime

Executable HOTEL-002 through HOTEL-005 flows are now persisted:

- cancellation quotes with tiered fees
- supplier cancellation + refund payment rail
- change quote + higher-price supplement / lower-price no-refund
- Stay Credit conversion (365 days, PROPERTY_ONLY)
- Stay Credit redemption with difference payment
- Alembic `0010_sprint1m`

See `specs/sprint1m_fare_runtime_contract.md` and `specs/sprint1m_state_machine.md`.

## Sprint 1N — Supplier fault compensation runtime

Sprint 1N adds the executable HOTEL-006 financial remedy chain:

- supplier-initiated cancellation case + cause classification
- supplier-fault gate before double compensation or bank debit
- 1x original refund + 1x extra compensation = 2x actual paid returned to consumer
- supplier settlement and reserve offsets
- supplier-specific debit mandate gate
- Consumer Protection Fund advance when supplier liquidity is insufficient
- Supplier Negative Balance and automatic recovery from future settlements
- append-only protection-fund advance/recovery ledger
- idempotent supplier cancellation command

The bank balance in this repository is a deterministic test rail, not a production bank integration. Production direct debit remains a licensed PSP/bank adapter responsibility.

## Sprint 1O

Sprint 1O adds persistent GO Truth Quick Review and serious-risk runtime: 1–5 raw user stars, 3.0–5.0 public experience contribution, structured low-score tags, verified-stay evidence, risk candidates, supplier evidence, remediation, and Judgment reevaluation hooks. Trust never directly patches GO Score or Recommendation.

## Sprint 1P - GO Judgment Runtime

Adds a persistent GO Judgment runtime with sealed Evidence Packages, independent GO Score computation, canonical Recommendation decisions, Judgment ID replay, and a worker that consumes `JUDGMENT_REEVALUATION_REQUESTED` hooks.

Hard boundaries:
- Raw 1-5 guest stars never enter GO Score features.
- Commercial/popularity/user-fit fields are rejected from the Judgment feature plane.
- Historical judgments are superseded, never overwritten.
- Only `GO_RECOMMENDED` exposes a public GO Score.

## Sprint 1Q - Supplier Console + GO Admin Operational Backend

Sprint 1Q organizes the existing transaction, fare, refund, Stay Credit, compensation, risk, Judgment and connector facts into tenant-scoped Supplier Console APIs and global GO Admin operational APIs.

Key additions:
- Supplier identity now propagates `Traffic Router -> Offer -> Order`.
- 8 Supplier Console dashboard/list endpoints.
- 9 GO Admin dashboard/queue/list endpoints.
- Exception queues expose reconciliation, failed refunds, unresolved supplier liability, risk review, degraded connectors and outbox recovery.
- Operational indexes added in Alembic `0014_sprint1q`.
- Existing Sprint 1P API paths are preserved; dashboard endpoints are additive.

The dashboard layer is intentionally read-only for core business facts. It cannot directly change GO Score, Recommendation, Ledger state, refund state or risk decisions.

## Sprint 1S — Supplier Console + GO Admin Frontend

Operational UIs are now served by the backend when running from the repository:

- Supplier Console: `/supplier-console/`
- GO Admin: `/go-admin/`

They authenticate against Sprint 1R Identity/RBAC and consume Sprint 1Q operational APIs. Supplier tenant scope comes only from the authenticated JWT principal. High-risk Admin operations remain controlled commands with maker-checker approval; there is no UI or API path for direct mutation of Ledger, GO Score, Recommendation, Risk or Refund facts.

## Sprint 1T — Interactive Operations Workbench

Sprint 1T upgrades Sprint 1S from read-oriented dashboards into controlled operational workbenches without introducing direct database mutation paths.

### Supplier Console
- Order detail workbench with payment/refund/change/Stay Credit/event timeline replay.
- Cancellation quote + controlled cancellation execution.
- Change quote + controlled change execution.
- Risk Case detail, supplier evidence submission and remediation submission.
- Supplier liability/fault/compensation detail replay.

### GO Admin
- Judgment + sealed Evidence Package replay.
- Connector onboarding activation/suspension workbench using Maker-Checker Approval IDs.
- Settlement account + liability drill-down.
- Approval queue with create/approve workflow.
- Immutable audit trail remains view-only.

### Governance boundary
The UI still has no direct UPDATE path for Order Ledger, GO Score, Recommendation, Risk facts, or Refund facts. Operations call authenticated domain/workflow endpoints and remain protected by Sprint 1R RBAC, tenant isolation and second approval where required.

## Sprint 1V
Production observability, SLO, incident control, security monitoring, runbooks, disaster recovery baseline and release readiness gate are documented in `README_SPRINT1V.md`, `docs/`, and `ops/alert_rules.yaml`.


See `README_SPRINT1W.md` for staging/CI/CD instructions.

## Sprint 1X Consumer App

Clickable GO hotel E2E is mounted at `/go-app/`. See `README_SPRINT1X.md`.

## Sprint 1Y — Consumer GO ID / Production Session / Tokenized Wallet

Sprint 1Y removes the Consumer App's `acct_demo` and `pm_success` dependencies from the production flow. Consumers can register/login, receive a GO ID, save traveler profiles, tokenize payment methods, create orders under their authenticated identity, securely checkout, and retrieve only their own trips. The old demo query parameters remain only as local-engineering compatibility paths; the Consumer UI uses JWT-derived ownership.

Production payment note: the bundled `MOCK_PSP_TOKENIZATION` adapter proves the contract but is not a PCI production processor. Replace it with a certified PSP tokenization SDK/API while retaining the same GO payment-method reference model.

## Sprint 1Z — Native iOS/Android client
`mobile/go-app/` contains the Expo/React Native production-client baseline. Native auth uses bearer access + rotating refresh tokens stored with OS-backed SecureStore, APNs/FCM device registration, allowlisted deep links, GO Trips, Wallet, order detail and Quick Review. See `docs/SPRINT_1Z_MOBILE.md`.

## Sprint 2C — Release Certification
No new product features. `scripts/sprint2c_certification_gate.py` provides an evidence-driven gate for real PostgreSQL/Redis, PSP/connector sandbox, APNs/FCM, links, signing, TestFlight/Play Internal installation and physical-device E2E. External gates remain BLOCKED until real credentials/infrastructure produce evidence.

## Sprint 2D — real-environment bring-up
Sprint 2D adds fail-closed credential preflight, real PostgreSQL/Redis probes, association-file validation, evidence-hashed gate promotion and a store build/submit workflow. No real external provider gate is marked PASS in this repository without attached non-secret evidence. See `docs/SPRINT_2D.md`.

## Latest: Sprint 3J
Recovery Command Ledger + Supplier Evidence Chain + Operational Control Plane is documented in `README_SPRINT3J.md`. Current DB head: `0031_sprint3j`.

## Sprint 3K continuation
See `README_SPRINT3K.md` and `sprint3k_verification_report.txt` for Recovery SLA Engine, escalation policy and Human Ops workflow. Current DB head: `0032_sprint3k`.

## Sprint 3U
Runtime Telemetry Provenance + Multi-Window SLO Policy + Automated Incident Correlation is implemented. See `README_SPRINT3U.md`.


## Sprint 4G
See `README_SPRINT4G.md` for Exception Debt Burn-Down Plan, Waiver Freeze and Executive Risk Acceptance Governance.

## Sprint 4X cumulative head
Historical note: the Sprint 4X-era database head was `0071_sprint4x`; the current cumulative database head is `0110_consumer_growth_official_direct_value`. Sprint 4X adds Portfolio Champion Continuity, Multi-Objective Revalidation and Safe Champion Replacement on top of the Sprint 4W cumulative baseline. See `README_SPRINT4X.md`.

### V6.1 Hotel Media Harvester / Rights Gate

Hotel AutoPage media now uses a GO-controlled content-addressed download cache. Public hotel/room media never publishes a raw origin hotlink: assets are decoded/validated, SHA-256 cached, room-bound where applicable, and fail closed until explicit rights evidence permits publication. See `GO_V6_1_MEDIA_HARVESTER_RIGHTS_GATE_2026-08-22.md`.

### R8.2 Supplier Mobile Operations Completion (2026-08-23)
Supplier Console now has an additive mobile operations layer with fixed bottom navigation (首页 / 订单 / 房态库存 / GO Offer / 我的), a full-function mobile sheet, and card-style narrow-screen tables. Desktop navigation and existing business behavior are preserved. Run `python scripts/r82_supplier_mobile_gate.py` before release.
