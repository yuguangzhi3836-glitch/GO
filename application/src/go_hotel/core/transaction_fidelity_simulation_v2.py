from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from go_hotel.core.provider_adapter_contract_v2 import VERTICAL_PROFILES, validate_provider_adapter_contract_v2
from go_hotel.core.provider_certification_harness_v2 import provider_certification_harness_v2


@dataclass(frozen=True)
class FidelityCheckV2:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class TransactionFidelityReportV2:
    vertical: str
    provider_code: str
    passed: bool
    checks: tuple[FidelityCheckV2, ...]
    external_call_executed: bool = False
    money_movement_executed: bool = False
    production_live: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "go.transaction-fidelity-report.v2",
            "vertical": self.vertical,
            "provider_code": self.provider_code,
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
            "external_call_executed": self.external_call_executed,
            "money_movement_executed": self.money_movement_executed,
            "production_live": self.production_live,
            "simulation_state": "CONTRACT_FIDELITY_PASS_NOT_EXTERNAL_CERTIFIED" if self.passed else "CONTRACT_FIDELITY_BLOCKED",
        }


class ContractFidelitySimulationRunnerV2:
    """Pure in-process simulation driven by Provider Adapter Contract v2.

    The runner validates event/state fidelity and safety invariants using controlled
    fixtures. It deliberately performs no network I/O, reads no provider secret,
    executes no PSP action, and cannot create LIVE truth.
    """

    def run(self, contract: dict[str, Any], fixture: dict[str, Any]) -> TransactionFidelityReportV2:
        normalized = validate_provider_adapter_contract_v2(contract)
        cert = provider_certification_harness_v2.certify(normalized)
        vertical = normalized["vertical"]
        provider_code = str(normalized["provider"]["provider_code"])
        profile = VERTICAL_PROFILES[vertical]
        checks: list[FidelityCheckV2] = [
            FidelityCheckV2("provider_certification_v2", cert.passed, cert.as_dict()["certification_state"])
        ]

        events = list(fixture.get("events") or [])
        by_operation: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            by_operation.setdefault(str(event.get("operation", "")), []).append(event)

        missing_ops = [op for op in profile["operations"] if not by_operation.get(op)]
        checks.append(FidelityCheckV2("fixture_operation_coverage", not missing_ops, ",".join(missing_ops) or "complete"))

        idempotency_keys = [str(e.get("idempotency_key")) for e in events if e.get("idempotency_key")]
        duplicated_keys = {key for key in idempotency_keys if idempotency_keys.count(key) > 1}
        duplicate_conflict = False
        for key in duplicated_keys:
            fingerprints = {str(e.get("request_fingerprint")) for e in events if str(e.get("idempotency_key")) == key}
            if len(fingerprints) > 1:
                duplicate_conflict = True
                break
        checks.append(FidelityCheckV2("idempotency_replay_safe", not duplicate_conflict, "same-key/same-fingerprint only" if not duplicate_conflict else "conflicting replay"))

        deliveries = [str(e.get("delivery_id")) for e in events if e.get("delivery_id")]
        replay_detected = any(deliveries.count(d) > 1 for d in set(deliveries))
        replay_policy = str(fixture.get("webhook_replay_policy", "DEDUPE"))
        checks.append(FidelityCheckV2("webhook_replay_fidelity", (not replay_detected) or replay_policy == "DEDUPE", replay_policy))

        stale_quote = bool(fixture.get("stale_quote"))
        stale_policy = str(fixture.get("stale_quote_policy", "REPRICE_OR_FAIL_CLOSED"))
        checks.append(FidelityCheckV2("stale_quote_safety", (not stale_quote) or stale_policy in {"REPRICE_OR_FAIL_CLOSED", "FAIL_CLOSED"}, stale_policy))

        unknown_error = bool(fixture.get("unknown_supplier_error"))
        unknown_policy = normalized["error_mapping"]["unknown_error_policy"]
        checks.append(FidelityCheckV2("unknown_error_fidelity", (not unknown_error) or unknown_policy == "FAIL_CLOSED", unknown_policy))

        partial_failure = bool(fixture.get("partial_failure"))
        recovery = str(fixture.get("partial_failure_policy", "OUTBOX_RETRY_WITHOUT_TRUTH_MUTATION"))
        checks.append(FidelityCheckV2(
            "partial_failure_recovery",
            (not partial_failure) or recovery in {"OUTBOX_RETRY_WITHOUT_TRUTH_MUTATION", "FAIL_CLOSED"},
            recovery,
        ))

        provider_outage = bool(fixture.get("provider_outage"))
        outage_policy = str(fixture.get("provider_outage_policy", "FAIL_CLOSED"))
        checks.append(FidelityCheckV2("provider_outage_safety", (not provider_outage) or outage_policy == "FAIL_CLOSED", outage_policy))

        truth_owner = str(fixture.get("truth_owner", vertical))
        checks.append(FidelityCheckV2("one_domain_one_final_owner", truth_owner == vertical, truth_owner))

        synthetic_only = fixture.get("fixture_source") == "CONTROLLED_SYNTHETIC_FIXTURE"
        checks.append(FidelityCheckV2("production_reality_registry", synthetic_only and not fixture.get("external_call_executed") and not fixture.get("money_movement_executed"), "simulation-only"))

        return TransactionFidelityReportV2(
            vertical=vertical,
            provider_code=provider_code,
            passed=all(c.passed for c in checks),
            checks=tuple(checks),
        )


contract_fidelity_simulation_runner_v2 = ContractFidelitySimulationRunnerV2()
