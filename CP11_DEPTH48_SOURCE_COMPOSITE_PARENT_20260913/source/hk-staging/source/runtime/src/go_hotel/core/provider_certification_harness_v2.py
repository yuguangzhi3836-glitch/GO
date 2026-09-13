from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from go_hotel.core.provider_adapter_contract_v2 import (
    VERTICAL_PROFILES,
    validate_provider_adapter_contract_v2,
)
from go_hotel.connectors.provider_adapter_contract import ProviderContractError


@dataclass(frozen=True)
class CertificationCheckV2:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ProviderCertificationReportV2:
    vertical: str
    provider_code: str
    passed: bool
    checks: tuple[CertificationCheckV2, ...]
    external_transport_verified: bool = False
    production_live: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "go.provider-certification-report.v2",
            "vertical": self.vertical,
            "provider_code": self.provider_code,
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
            "external_transport_verified": self.external_transport_verified,
            "production_live": self.production_live,
            "certification_state": (
                "CONTRACT_V2_CERTIFIED_NOT_EXTERNALLY_VERIFIED"
                if self.passed
                else "CONTRACT_V2_CERTIFICATION_BLOCKED"
            ),
        }


class ProviderCertificationHarnessV2:
    """Contract-v2-driven, vertical-neutral certification harness.

    This harness is intentionally transport-free. It certifies the readiness contract
    and controlled fixture/evidence shape only. It must not make provider calls, read
    inline secrets, or claim external certification/LIVE status.
    """

    def certify(self, contract: dict[str, Any]) -> ProviderCertificationReportV2:
        checks: list[CertificationCheckV2] = []
        try:
            normalized = validate_provider_adapter_contract_v2(contract)
            checks.append(CertificationCheckV2("contract_v2_schema", True, "validated"))
        except ProviderContractError as exc:
            vertical = str(contract.get("vertical", "UNKNOWN")).upper() if isinstance(contract, dict) else "UNKNOWN"
            provider_code = "UNKNOWN"
            if isinstance(contract, dict):
                provider_code = str((contract.get("provider") or {}).get("provider_code") or "UNKNOWN")
            return ProviderCertificationReportV2(
                vertical=vertical,
                provider_code=provider_code,
                passed=False,
                checks=(CertificationCheckV2("contract_v2_schema", False, str(exc)),),
            )

        vertical = normalized["vertical"]
        profile = VERTICAL_PROFILES[vertical]
        provider_code = str(normalized["provider"]["provider_code"])

        operations = normalized["operations"]
        missing_ops = [name for name in profile["operations"] if name not in operations]
        checks.append(CertificationCheckV2("operation_coverage", not missing_ops, ",".join(missing_ops) or "complete"))

        canonical = normalized["canonical_mapping"]
        missing_canonical = [name for name in profile["canonical"] if name not in canonical]
        checks.append(CertificationCheckV2("canonical_mapping_coverage", not missing_canonical, ",".join(missing_canonical) or "complete"))

        auth = normalized["transport"]["auth"]
        credential_reference = str(auth["credential_reference"])
        checks.append(CertificationCheckV2(
            "credential_boundary",
            credential_reference.startswith(("vault://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://", "kms://")),
            "reference-only",
        ))

        signature = normalized["webhook"]["signature"]
        replay_tolerance = int(signature["replay_tolerance_seconds"])
        checks.append(CertificationCheckV2(
            "webhook_replay_control",
            0 < replay_tolerance <= 900 and bool(signature.get("timestamp_header")) and bool(signature.get("signature_header")),
            f"tolerance={replay_tolerance}",
        ))

        errors = normalized["error_mapping"]
        checks.append(CertificationCheckV2(
            "unknown_error_fail_closed",
            errors.get("unknown_error_policy") == "FAIL_CLOSED",
            str(errors.get("unknown_error_policy")),
        ))

        limits = normalized["limits"]
        timeout_retry_ok = (
            int(limits["connect_timeout_ms"]) > 0
            and int(limits["read_timeout_ms"]) > 0
            and 1 <= int(limits["max_attempts"]) <= 5
            and int(limits["max_concurrency"]) > 0
            and int(limits["requests_per_second"]) > 0
        )
        checks.append(CertificationCheckV2("timeout_retry_bounds", timeout_retry_ok, f"max_attempts={limits['max_attempts']}"))

        attestation = normalized["attestation"]
        evidence = attestation.get("evidence_references") or []
        checks.append(CertificationCheckV2(
            "evidence_attestation",
            bool(evidence) and bool(attestation.get("contract_reference")) and bool(attestation.get("sandbox_account_reference")),
            f"evidence_count={len(evidence)}",
        ))

        readiness_only = (
            normalized.get("external_transport_verified") is False
            and normalized.get("production_live") is False
        )
        checks.append(CertificationCheckV2("reality_registry_readiness_only", readiness_only, "no external/LIVE claim"))

        return ProviderCertificationReportV2(
            vertical=vertical,
            provider_code=provider_code,
            passed=all(c.passed for c in checks),
            checks=tuple(checks),
        )


provider_certification_harness_v2 = ProviderCertificationHarnessV2()
