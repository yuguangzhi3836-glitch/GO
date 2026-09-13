from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import func, select

from go_hotel.connectors.hotel_supply_sandbox import hotel_supply_sandbox_executor, result_dict
from go_hotel.connectors.provider_adapter_contract import (
    ProviderContractError,
    validate_provider_adapter_contract,
)
from go_hotel.db.models import (
    ConnectorAuthorityRow,
    ConnectorCapabilityMatrixRow,
    ConnectorCertificationRunRow,
    ConnectorCredentialReferenceRow,
    ProductionConnectorRow,
)
from go_hotel.db.session import SessionLocal


REQUIRED_CAPABILITIES = {
    "search",
    "availability",
    "quote",
    "book",
    "query",
    "cancel",
    "signed_webhook",
    "idempotency",
    "query_by_idempotency",
    "error_mapping",
    "reconciliation",
}

SUPPLY_TRUTH_FIELDS = (
    "property_id",
    "room_id",
    "rate_plan_id",
    "room_name",
    "inventory",
    "price_minor",
    "currency",
    "breakfast",
    "cancellation_policy",
    "taxes_fees",
    "sell_state",
    "source_updated_at",
)

REQUIRED_SCENARIOS = (
    "CONNECTIVITY",
    "PROPERTY_MAPPING",
    "ROOM_MAPPING",
    "RATE_PLAN_MAPPING",
    "AVAILABILITY",
    "QUOTE",
    "BOOK_IDEMPOTENCY",
    "QUERY",
    "CANCEL",
    "SIGNED_WEBHOOK",
    "ERROR_MAPPING",
    "RECONCILIATION",
)

FRAMEWORK_STATE = "READY_NOT_EXTERNALLY_VERIFIED"
EXTERNAL_PASS_STATE = "EXTERNAL_SANDBOX_CERTIFIED"


def now() -> datetime:
    return datetime.now(timezone.utc)


def ident(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def out(row):
    return {
        c.name: (getattr(row, c.name).isoformat() if isinstance(getattr(row, c.name), datetime) else getattr(row, c.name))
        for c in row.__table__.columns
    }


def _validate_endpoint(endpoint: str) -> None:
    if not endpoint or not endpoint.lower().startswith("https://"):
        raise ValueError("HTTPS_SANDBOX_ENDPOINT_REQUIRED")


def _validate_secret_reference(ref: str) -> None:
    if not ref.startswith(("vault://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://", "kms://")):
        raise ValueError("EXTERNAL_VAULT_REFERENCE_REQUIRED")
    lowered = ref.lower()
    if any(x in lowered for x in ("password=", "secret=", "token=", "api_key=")):
        raise ValueError("INLINE_SECRET_FORBIDDEN")


class HotelSupplySandboxCertificationService:
    def register(self, body: dict[str, Any], actor: str) -> dict[str, Any]:
        supplier = str(body.get("supplier_legal_name") or "").strip()
        connector_key = str(body.get("connector_key") or "").strip()
        endpoint = str(body.get("sandbox_endpoint") or "").strip()
        test_hotel = str(body.get("test_hotel_reference") or "").strip()
        allowlist = str(body.get("ip_allowlist_reference") or "").strip()
        docs_ref = str(body.get("documentation_reference") or "").strip()
        auth_method = str(body.get("auth_method") or "").strip()
        if not supplier:
            raise ValueError("FORMAL_SUPPLIER_IDENTITY_REQUIRED")
        if not connector_key:
            raise ValueError("CONNECTOR_KEY_REQUIRED")
        _validate_endpoint(endpoint)
        if not test_hotel:
            raise ValueError("TEST_HOTEL_REFERENCE_REQUIRED")
        if not allowlist:
            raise ValueError("IP_ALLOWLIST_REFERENCE_REQUIRED")
        if not docs_ref:
            raise ValueError("SUPPLIER_DOCUMENTATION_REFERENCE_REQUIRED")
        if not auth_method:
            raise ValueError("AUTH_METHOD_REQUIRED")

        profile = {
            "sandbox_endpoint": endpoint,
            "test_hotel_reference": test_hotel,
            "ip_allowlist_reference": allowlist,
            "documentation_reference": docs_ref,
            "documentation_version": body.get("documentation_version"),
            "auth_method": auth_method,
            "webhook_reference": body.get("webhook_reference"),
            "rate_limit_reference": body.get("rate_limit_reference"),
            "sla_reference": body.get("sla_reference"),
            "contact_reference": body.get("contact_reference"),
            "supply_truth_fields": list(SUPPLY_TRUTH_FIELDS),
            "required_scenarios": list(REQUIRED_SCENARIOS),
        }
        caps = {k: True for k in REQUIRED_CAPABILITIES}
        caps["hotel_supply_profile"] = profile

        with SessionLocal() as s:
            existing = s.scalar(select(ProductionConnectorRow).where(ProductionConnectorRow.connector_key == connector_key))
            if existing:
                if existing.vertical != "HOTEL" or existing.supplier_legal_name != supplier:
                    raise ValueError("CONNECTOR_KEY_ALREADY_BOUND_TO_DIFFERENT_SUPPLIER")
                connector = existing
            else:
                connector = ProductionConnectorRow(
                    connector_id=ident("conn"), connector_key=connector_key,
                    display_name=body.get("display_name") or supplier,
                    vertical="HOTEL", supplier_legal_name=supplier,
                    environment="SANDBOX", lifecycle_state="ENGINEERING",
                    active_capability_version=1, created_by=actor,
                    created_at=now(), updated_at=now(),
                )
                s.add(connector)
                s.flush()
            version = (s.scalar(select(func.max(ConnectorCapabilityMatrixRow.version_no)).where(
                ConnectorCapabilityMatrixRow.connector_id == connector.connector_id
            )) or 0) + 1
            matrix = ConnectorCapabilityMatrixRow(
                capability_matrix_id=ident("ccm"), connector_id=connector.connector_id,
                version_no=version, capabilities_json=caps, content_hash=digest(caps), created_at=now(),
            )
            s.add(matrix)
            connector.active_capability_version = version
            connector.lifecycle_state = "CONNECTABLE"
            connector.updated_at = now()
            s.commit()
            return {"connector": out(connector), "profile": profile, "external_verified": False}

    def bind_authority(self, connector_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        contract = str(body.get("contract_reference") or "").strip()
        authority = str(body.get("authority_reference") or "").strip()
        if not contract or not authority:
            raise ValueError("CONTRACT_AND_DISTRIBUTION_AUTHORITY_REQUIRED")
        evidence = {
            "authority_reference": authority,
            "evidence_reference": body.get("evidence_reference"),
            "actor": actor,
        }
        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_id)
            if not connector or connector.vertical != "HOTEL" or connector.environment != "SANDBOX":
                raise ValueError("HOTEL_SANDBOX_CONNECTOR_NOT_FOUND")
            row = ConnectorAuthorityRow(
                connector_authority_id=ident("cauth"), connector_id=connector_id,
                contract_reference=contract, authority_scope_json=["HOTEL_SUPPLY_SANDBOX_CERTIFICATION"],
                evidence_json=evidence, valid_from=now(), valid_to=None, state="ACTIVE",
            )
            s.add(row)
            s.commit()
            return out(row)

    def bind_credential(self, connector_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        ref = str(body.get("secret_reference") or "").strip()
        _validate_secret_reference(ref)
        if any(k in body for k in ("secret", "password", "api_key", "private_key", "token")):
            raise ValueError("INLINE_SECRET_FORBIDDEN")
        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_id)
            if not connector or connector.vertical != "HOTEL" or connector.environment != "SANDBOX":
                raise ValueError("HOTEL_SANDBOX_CONNECTOR_NOT_FOUND")
            row = ConnectorCredentialReferenceRow(
                credential_reference_id=ident("cref"), connector_id=connector_id,
                credential_kind=body.get("credential_kind") or "HOTEL_SUPPLY_SANDBOX",
                secret_reference=ref, key_fingerprint=body.get("key_fingerprint") or digest(ref)[:32],
                expires_at=body.get("expires_at"), state="ACTIVE", updated_at=now(),
            )
            s.add(row)
            s.commit()
            return out(row)

    def set_mapping(self, connector_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        mapping = body.get("mapping") or {}
        required = ("supplier_property_id", "go_hotel_id", "rooms")
        if any(not mapping.get(k) for k in required):
            raise ValueError("PROPERTY_ROOM_MAPPING_REQUIRED")
        if not isinstance(mapping.get("rooms"), list) or not mapping["rooms"]:
            raise ValueError("ROOM_MAPPING_REQUIRED")
        for item in mapping["rooms"]:
            if not item.get("supplier_room_id") or not item.get("go_room_id"):
                raise ValueError("ROOM_MAPPING_INCOMPLETE")
            if not item.get("rate_plans"):
                raise ValueError("RATE_PLAN_MAPPING_REQUIRED")
        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_id)
            if not connector or connector.vertical != "HOTEL" or connector.environment != "SANDBOX":
                raise ValueError("HOTEL_SANDBOX_CONNECTOR_NOT_FOUND")
            latest = s.scalar(select(ConnectorCapabilityMatrixRow).where(
                ConnectorCapabilityMatrixRow.connector_id == connector_id
            ).order_by(ConnectorCapabilityMatrixRow.version_no.desc()))
            if not latest:
                raise ValueError("CAPABILITY_PROFILE_REQUIRED")
            caps = dict(latest.capabilities_json or {})
            caps["hotel_mapping"] = mapping
            version = latest.version_no + 1
            row = ConnectorCapabilityMatrixRow(
                capability_matrix_id=ident("ccm"), connector_id=connector_id,
                version_no=version, capabilities_json=caps, content_hash=digest(caps), created_at=now(),
            )
            s.add(row)
            connector.active_capability_version = version
            connector.updated_at = now()
            s.commit()
            return {"mapping": mapping, "content_hash": row.content_hash, "actor": actor}

    def set_provider_adapter_contract(self, connector_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        contract = body.get("provider_adapter_contract") or body.get("contract") or {}
        try:
            normalized = validate_provider_adapter_contract(contract)
        except ProviderContractError as exc:
            raise ValueError(str(exc)) from exc
        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_id)
            if not connector or connector.vertical != "HOTEL" or connector.environment != "SANDBOX":
                raise ValueError("HOTEL_SANDBOX_CONNECTOR_NOT_FOUND")
            if normalized["provider"]["supplier_legal_name"] != connector.supplier_legal_name:
                raise ValueError("PROVIDER_CONTRACT_SUPPLIER_MISMATCH")
            latest = s.scalar(select(ConnectorCapabilityMatrixRow).where(
                ConnectorCapabilityMatrixRow.connector_id == connector_id
            ).order_by(ConnectorCapabilityMatrixRow.version_no.desc()))
            if not latest:
                raise ValueError("CAPABILITY_PROFILE_REQUIRED")
            caps = dict(latest.capabilities_json or {})
            caps["provider_adapter_contract"] = normalized
            version = latest.version_no + 1
            row = ConnectorCapabilityMatrixRow(
                capability_matrix_id=ident("ccm"), connector_id=connector_id,
                version_no=version, capabilities_json=caps, content_hash=digest(caps), created_at=now(),
            )
            s.add(row)
            connector.active_capability_version = version
            connector.updated_at = now()
            s.commit()
            return {
                "connector_id": connector_id,
                "provider_code": normalized["provider"]["provider_code"],
                "state": "PROVIDER_CONTRACT_READY_NOT_EXTERNALLY_VERIFIED",
                "content_hash": row.content_hash,
                "external_transport_verified": False,
                "production_live": False,
                "payment_scope": "OUT_OF_SCOPE",
                "actor": actor,
            }

    def provider_adapter_readiness(self, connector_id: str) -> dict[str, Any]:
        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_id)
            if not connector or connector.vertical != "HOTEL" or connector.environment != "SANDBOX":
                raise ValueError("HOTEL_SANDBOX_CONNECTOR_NOT_FOUND")
            matrix = s.scalar(select(ConnectorCapabilityMatrixRow).where(
                ConnectorCapabilityMatrixRow.connector_id == connector_id
            ).order_by(ConnectorCapabilityMatrixRow.version_no.desc()))
            contract = (matrix.capabilities_json or {}).get("provider_adapter_contract") if matrix else None
            if not contract:
                return {
                    "connector_id": connector_id,
                    "state": "PROVIDER_CONTRACT_MISSING",
                    "provider_contract_ready": False,
                    "external_transport_verified": False,
                    "production_live": False,
                    "payment_scope": "OUT_OF_SCOPE",
                }
            try:
                normalized = validate_provider_adapter_contract(contract)
            except ProviderContractError as exc:
                return {
                    "connector_id": connector_id,
                    "state": "PROVIDER_CONTRACT_INVALID",
                    "provider_contract_ready": False,
                    "blocker": str(exc),
                    "external_transport_verified": False,
                    "production_live": False,
                    "payment_scope": "OUT_OF_SCOPE",
                }
            return {
                "connector_id": connector_id,
                "provider_code": normalized["provider"]["provider_code"],
                "supplier": connector.supplier_legal_name,
                "state": "PROVIDER_CONTRACT_READY_NOT_EXTERNALLY_VERIFIED",
                "provider_contract_ready": True,
                "operations": sorted((normalized.get("operations") or {}).keys()),
                "webhook_signature_scheme": normalized["webhook"]["signature"]["scheme"],
                "error_mapping_fail_closed": normalized["error_mapping"]["unknown_error_policy"] == "FAIL_CLOSED",
                "rate_limit": normalized["limits"],
                "attestation": {
                    "contract_reference": normalized["attestation"]["contract_reference"],
                    "evidence_references": normalized["attestation"]["evidence_references"],
                    "external_transport_verified": False,
                },
                "external_transport_verified": False,
                "production_live": False,
                "payment_scope": "OUT_OF_SCOPE",
            }

    def readiness(self, connector_id: str) -> dict[str, Any]:
        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_id)
            if not connector or connector.vertical != "HOTEL" or connector.environment != "SANDBOX":
                raise ValueError("HOTEL_SANDBOX_CONNECTOR_NOT_FOUND")
            matrix = s.scalar(select(ConnectorCapabilityMatrixRow).where(
                ConnectorCapabilityMatrixRow.connector_id == connector_id
            ).order_by(ConnectorCapabilityMatrixRow.version_no.desc()))
            authority = s.scalar(select(ConnectorAuthorityRow).where(
                ConnectorAuthorityRow.connector_id == connector_id,
                ConnectorAuthorityRow.state == "ACTIVE",
            ).order_by(ConnectorAuthorityRow.valid_from.desc()))
            credential = s.scalar(select(ConnectorCredentialReferenceRow).where(
                ConnectorCredentialReferenceRow.connector_id == connector_id,
                ConnectorCredentialReferenceRow.state == "ACTIVE",
            ).order_by(ConnectorCredentialReferenceRow.updated_at.desc()))
            caps = matrix.capabilities_json if matrix else {}
            profile = caps.get("hotel_supply_profile") or {}
            mapping = caps.get("hotel_mapping") or {}
            checks = {
                "named_supplier": bool(connector.supplier_legal_name),
                "sandbox_endpoint": str(profile.get("sandbox_endpoint") or "").startswith("https://"),
                "documentation": bool(profile.get("documentation_reference")),
                "auth_method": bool(profile.get("auth_method")),
                "ip_allowlist": bool(profile.get("ip_allowlist_reference")),
                "test_hotel": bool(profile.get("test_hotel_reference")),
                "authority": bool(authority),
                "vault_credential": bool(credential and credential.secret_reference),
                "required_capabilities": REQUIRED_CAPABILITIES <= {k for k, v in caps.items() if v is True},
                "property_mapping": bool(mapping.get("supplier_property_id") and mapping.get("go_hotel_id")),
                "room_rate_mapping": bool(mapping.get("rooms")),
            }
            blockers = [k.upper() for k, v in checks.items() if not v]
            external_runs = s.scalars(select(ConnectorCertificationRunRow).where(
                ConnectorCertificationRunRow.connector_id == connector_id,
                ConnectorCertificationRunRow.environment == "SANDBOX",
                ConnectorCertificationRunRow.result == "PASS",
            )).all()
            externally_verified = any((r.evidence_json or {}).get("external_transport_attested") for r in external_runs)
            state = EXTERNAL_PASS_STATE if externally_verified and not blockers else (FRAMEWORK_STATE if not blockers else "INPUTS_INCOMPLETE")
            return {
                "connector_id": connector_id,
                "supplier": connector.supplier_legal_name,
                "state": state,
                "checks": checks,
                "blockers": blockers,
                "external_executor_configured": bool(hotel_supply_sandbox_executor.configured),
                "externally_verified": externally_verified,
                "production_live": False,
                "payment_connected": False,
                "supply_truth_ready": state in {FRAMEWORK_STATE, EXTERNAL_PASS_STATE},
            }

    def framework_certify(self, connector_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        readiness = self.readiness(connector_id)
        checks = {x: False for x in REQUIRED_SCENARIOS}
        checks.update({
            "CONNECTIVITY": readiness["checks"]["sandbox_endpoint"],
            "PROPERTY_MAPPING": readiness["checks"]["property_mapping"],
            "ROOM_MAPPING": readiness["checks"]["room_rate_mapping"],
            "RATE_PLAN_MAPPING": readiness["checks"]["room_rate_mapping"],
            "AVAILABILITY": readiness["checks"]["required_capabilities"],
            "QUOTE": readiness["checks"]["required_capabilities"],
            "BOOK_IDEMPOTENCY": readiness["checks"]["required_capabilities"],
            "QUERY": readiness["checks"]["required_capabilities"],
            "CANCEL": readiness["checks"]["required_capabilities"],
            "SIGNED_WEBHOOK": readiness["checks"]["required_capabilities"],
            "ERROR_MAPPING": readiness["checks"]["required_capabilities"],
            "RECONCILIATION": readiness["checks"]["required_capabilities"],
        })
        evidence = [{"type": "FRAMEWORK_CONTRACT", "reference": body.get("evidence_reference") or "framework://rc14"}]
        result = "PASS" if all(checks.values()) else "FAIL"
        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_id)
            row = ConnectorCertificationRunRow(
                certification_run_id=ident("cert"), connector_id=connector_id,
                environment="SANDBOX", suite_version="RC14-HOTEL-SUPPLY-V1",
                result=result, checks_json=checks,
                evidence_json={"framework_only": True, "external_transport_attested": False, "evidence": evidence},
                evidence_hash=digest({"checks": checks, "evidence": evidence}),
                executed_by=actor, completed_at=now(),
            )
            s.add(row)
            connector.lifecycle_state = "CERTIFIABLE" if result == "PASS" else connector.lifecycle_state
            connector.updated_at = now()
            s.commit()
            return {
                "certification": out(row),
                "decision": "READY_NOT_EXTERNALLY_VERIFIED" if result == "PASS" else "FRAMEWORK_NOT_READY",
                "real_supplier_connected": False,
                "production_live": False,
            }

    def external_certify(self, connector_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        key = str(body.get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        readiness = self.readiness(connector_id)
        if readiness["state"] == "INPUTS_INCOMPLETE":
            raise ValueError("HOTEL_SUPPLY_SANDBOX_INPUTS_INCOMPLETE")
        if not hotel_supply_sandbox_executor.configured:
            raise ValueError("HOTEL_SUPPLY_SANDBOX_EXECUTOR_NOT_CONFIGURED")
        with SessionLocal() as s:
            existing = s.scalar(select(ConnectorCertificationRunRow).where(
                ConnectorCertificationRunRow.connector_id == connector_id,
                ConnectorCertificationRunRow.environment == "SANDBOX",
                ConnectorCertificationRunRow.suite_version == f"RC14-EXT-{key}",
            ))
            if existing:
                return {"certification": out(existing), "decision": EXTERNAL_PASS_STATE if existing.result == "PASS" else "BLOCKED"}
            connector = s.get(ProductionConnectorRow, connector_id)
            matrix = s.scalar(select(ConnectorCapabilityMatrixRow).where(
                ConnectorCapabilityMatrixRow.connector_id == connector_id
            ).order_by(ConnectorCapabilityMatrixRow.version_no.desc()))
            credential = s.scalar(select(ConnectorCredentialReferenceRow).where(
                ConnectorCredentialReferenceRow.connector_id == connector_id,
                ConnectorCredentialReferenceRow.state == "ACTIVE",
            ).order_by(ConnectorCredentialReferenceRow.updated_at.desc()))
            caps = matrix.capabilities_json or {}
            profile = caps.get("hotel_supply_profile") or {}
            mapping = caps.get("hotel_mapping") or {}
            results = hotel_supply_sandbox_executor.execute_suite(
                supplier_name=connector.supplier_legal_name,
                endpoint=profile["sandbox_endpoint"],
                credential_reference=credential.secret_reference,
                test_hotel_reference=profile["test_hotel_reference"],
                mapping=mapping,
                idempotency_key=key,
            )
            observed = {r.operation: bool(r.ok) for r in results}
            checks = {scenario: observed.get(scenario, False) for scenario in REQUIRED_SCENARIOS}
            pass_all = all(checks.values())
            evidence = {
                "framework_only": False,
                "external_transport_attested": True,
                "operations": [result_dict(x) for x in results],
            }
            row = ConnectorCertificationRunRow(
                certification_run_id=ident("cert"), connector_id=connector_id,
                environment="SANDBOX", suite_version=f"RC14-EXT-{key}",
                result="PASS" if pass_all else "FAIL", checks_json=checks,
                evidence_json=evidence, evidence_hash=digest(evidence),
                executed_by=actor, completed_at=now(),
            )
            s.add(row)
            connector.lifecycle_state = "CERTIFIABLE" if pass_all else connector.lifecycle_state
            connector.updated_at = now()
            s.commit()
            return {
                "certification": out(row),
                "decision": EXTERNAL_PASS_STATE if pass_all else "BLOCKED",
                "real_supplier_connected": pass_all,
                "production_live": False,
            }

    def dashboard(self) -> dict[str, Any]:
        with SessionLocal() as s:
            rows = s.scalars(select(ProductionConnectorRow).where(
                ProductionConnectorRow.vertical == "HOTEL",
                ProductionConnectorRow.environment == "SANDBOX",
            )).all()
            items = []
            for row in rows:
                try:
                    items.append(self.readiness(row.connector_id))
                except ValueError:
                    continue
            return {
                "hotel_sandbox_connectors": items,
                "external_executor_configured": bool(hotel_supply_sandbox_executor.configured),
                "default_state_without_real_credentials": "READY_NOT_EXTERNALLY_VERIFIED",
                "payment_scope": "OUT_OF_SCOPE",
                "production_live": False,
            }


hotel_supply_sandbox_certification_service = HotelSupplySandboxCertificationService()
