from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from go_hotel.connectors.payment_sandbox import payment_sandbox_executor
from go_hotel.db.models import (
    HostedDirectHotelRow,
    HostedDirectPaymentReadinessRow,
    OmnichannelMerchantBindingRow as Merchant,
    OmnichannelPaymentAttemptRow as Attempt,
    OmnichannelPaymentIntentRow as Intent,
    OrderSupplierFulfillmentRow as Fulfillment,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.omnichannel_payment import ident, out
from go_hotel.services.payment_sandbox_cutover import payment_sandbox_cutover_service as cutover_svc

AOLUGUYA_SLUG = "aoluguya-harbin"
READY_STATE = "READY_NOT_PSP_CONNECTED"
CERTIFIED_STATE = "ACTIVE_CERTIFIED"
CERTIFICATION_SCENARIOS = (
    "PAYMENT_LINK_CREATE",
    "SIGNED_CALLBACK_VERIFY",
    "AUTHORIZATION",
    "CAPTURE",
    "REFUND",
    "QUERY",
    "RECONCILIATION",
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _vault_ref(value: str | None) -> bool:
    return bool(value and str(value).startswith(("kms://", "vault://", "cert://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://")))


class PaymentSandboxRuntimeService:
    def configure_readiness(self, body: dict[str, Any], actor: str) -> dict[str, Any]:
        provider = str(body.get("provider") or "").upper()
        if not provider:
            raise ValueError("PSP_PROVIDER_REQUIRED")
        merchant = str(body.get("merchant_account_name") or "").strip()
        if not merchant:
            raise ValueError("MERCHANT_ACCOUNT_NAME_REQUIRED")
        app_ref = str(body.get("sandbox_app_id_reference") or "").strip() or None
        kms_ref = str(body.get("kms_reference") or "").strip() or None
        if app_ref and not app_ref.startswith(("sandbox-app://", "contract://", "psp://")):
            raise ValueError("SANDBOX_APP_REFERENCE_REQUIRED")
        if kms_ref and not _vault_ref(kms_ref):
            raise ValueError("KMS_OR_VAULT_REFERENCE_REQUIRED")
        blockers = []
        if not app_ref: blockers.append("REAL_PSP_SANDBOX_APP_REQUIRED")
        if not kms_ref: blockers.append("REAL_PSP_KMS_CREDENTIAL_REQUIRED")
        blockers.append("EXTERNAL_PAYMENT_SANDBOX_EXECUTOR_NOT_CONFIGURED")
        with SessionLocal() as s:
            hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            if not hotel:
                raise ValueError("AOLUGUYA_HOSTED_DIRECT_HOTEL_REQUIRED")
            row = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id)
            if not row:
                row = HostedDirectPaymentReadinessRow(
                    hosted_hotel_id=hotel.hosted_hotel_id, provider=provider,
                    merchant_account_name=merchant, application_state=READY_STATE,
                    sandbox_app_id_reference=app_ref, kms_reference=kms_ref,
                    blockers_json=blockers, updated_at=now(),
                )
                s.add(row)
            else:
                row.provider=provider; row.merchant_account_name=merchant; row.application_state=READY_STATE
                row.sandbox_app_id_reference=app_ref; row.kms_reference=kms_ref; row.blockers_json=blockers; row.updated_at=now()
            s.commit()
            return out(row) | {"configured_by": actor, "payment_live": False, "real_money_moved": False}

    def readiness(self) -> dict[str, Any]:
        with SessionLocal() as s:
            hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            row = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id) if hotel else None
            checks = {
                "PAYMENT_INTENT": True,
                "PAYMENT_LINK": True,
                "SIGNED_PSP_CALLBACK": True,
                "AUTHORIZATION_CAPTURE_REFUND": True,
                "LEDGER": True,
                "SETTLEMENT_HOLD": True,
                "CHECKOUT_RELEASE_GATE": True,
                "PSP_SANDBOX_APP": bool(row and row.sandbox_app_id_reference),
                "PSP_KMS_CREDENTIAL": bool(row and row.kms_reference),
                "EXTERNAL_EXECUTOR": payment_sandbox_executor.configured,
            }
            external = checks["PSP_SANDBOX_APP"] and checks["PSP_KMS_CREDENTIAL"] and checks["EXTERNAL_EXECUTOR"]
            return {
                "state": "READY_FOR_EXTERNAL_PSP_SANDBOX" if external else READY_STATE,
                "checks": checks,
                "blockers": [k for k,v in checks.items() if not v],
                "lifecycle": ["PAYMENT_INTENT","PAYMENT_LINK","PSP_CALLBACK","AUTHORIZATION","CAPTURE","REFUND","LEDGER","SETTLEMENT_HOLD","CHECKOUT_RELEASE"],
                "funds_rule": "NO_HOTEL_PAYOUT_BEFORE_FULFILLMENT_AND_CHECKOUT_GATE",
                "external_psp_connected": external,
                "payment_live": False,
                "real_money_moved": False,
            }


    def certification_preflight(self, channel: str = "ALIPAY") -> dict[str, Any]:
        channel = str(channel or "").upper()
        with SessionLocal() as s:
            hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            row = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id) if hotel else None
            merchant = s.scalar(
                select(Merchant).where(
                    Merchant.owner_type == "HOSTED_HOTEL",
                    Merchant.owner_id == (hotel.hosted_hotel_id if hotel else ""),
                    Merchant.channel == channel,
                )
            )
            checks = {
                "AOLUGUYA_HOSTED_DIRECT_HOTEL": bool(hotel),
                "PSP_SANDBOX_APP_REFERENCE": bool(row and row.sandbox_app_id_reference),
                "PSP_KMS_CREDENTIAL_REFERENCE": bool(row and row.kms_reference),
                "MERCHANT_BINDING_REFERENCE": bool(merchant),
                "MERCHANT_CREDENTIAL_REFERENCE": bool(merchant and _vault_ref(merchant.credential_reference)),
                "WEBHOOK_KEY_REFERENCE": bool(merchant and _vault_ref(merchant.webhook_key_reference)),
                "EXTERNAL_SANDBOX_EXECUTOR": payment_sandbox_executor.configured,
            }
            blockers = [name for name, ok in checks.items() if not ok]
            return {
                "channel": channel,
                "state": "READY_FOR_PAYMENT_SANDBOX_CERTIFICATION" if not blockers else "NOT_READY_FOR_PAYMENT_SANDBOX_CERTIFICATION",
                "checks": checks,
                "blockers": blockers,
                "required_scenarios": list(CERTIFICATION_SCENARIOS),
                "merchant_state": merchant.state if merchant else None,
                "payment_sandbox_certified": bool(merchant and merchant.state == CERTIFIED_STATE),
                "payment_live": False,
                "real_money_moved": False,
            }

    def certify(self, body: dict[str, Any], actor: str) -> dict[str, Any]:
        channel = str(body.get("channel") or "ALIPAY").upper()
        if not bool(body.get("source_attested")):
            raise ValueError("ATTESTED_EXTERNAL_PSP_SANDBOX_EVIDENCE_REQUIRED")
        evidence_reference = str(body.get("evidence_reference") or "").strip()
        if not evidence_reference.startswith(("psp-sandbox://", "cert://", "evidence://")):
            raise ValueError("EXTERNAL_PSP_SANDBOX_EVIDENCE_REFERENCE_REQUIRED")
        preflight = self.certification_preflight(channel)
        if preflight["blockers"]:
            raise ValueError("PAYMENT_SANDBOX_CERTIFICATION_PREFLIGHT_BLOCKED:" + ",".join(preflight["blockers"]))
        probe = payment_sandbox_executor.certification_probe(
            provider=channel,
            merchant_account_name=str(body.get("merchant_account_name") or "").strip(),
            required_scenarios=list(CERTIFICATION_SCENARIOS),
            evidence_reference=evidence_reference,
            idempotency_key=str(body.get("idempotency_key") or "").strip(),
        )
        scenario_results = probe.get("scenario_results") or {}
        missing = [x for x in CERTIFICATION_SCENARIOS if scenario_results.get(x) != "PASS"]
        if missing:
            raise ValueError("PAYMENT_SANDBOX_CERTIFICATION_SCENARIOS_FAILED:" + ",".join(missing))
        if not bool(probe.get("callback_signature_verified")):
            raise ValueError("PAYMENT_SANDBOX_SIGNED_CALLBACK_PROOF_REQUIRED")
        if not bool(probe.get("reconciliation_verified")):
            raise ValueError("PAYMENT_SANDBOX_RECONCILIATION_PROOF_REQUIRED")
        external_ref = str(probe.get("external_evidence_reference") or "").strip()
        if not external_ref.startswith(("psp-sandbox://", "cert://", "evidence://")):
            raise ValueError("PAYMENT_SANDBOX_EXECUTOR_EVIDENCE_REFERENCE_REQUIRED")
        with SessionLocal() as s:
            hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            merchant = s.scalar(
                select(Merchant).where(
                    Merchant.owner_type == "HOSTED_HOTEL",
                    Merchant.owner_id == hotel.hosted_hotel_id,
                    Merchant.channel == channel,
                ).with_for_update()
            ) if hotel else None
            if not merchant:
                raise ValueError("PAYMENT_SANDBOX_MERCHANT_BINDING_REQUIRED")
            merchant.state = CERTIFIED_STATE
            merchant.updated_at = now()
            readiness = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id)
            if readiness:
                readiness.application_state = "SANDBOX_CERTIFIED_NOT_LIVE"
                readiness.blockers_json = []
                readiness.updated_at = now()
            certification_event = cutover_svc.record_certification_grant(
                s, channel=channel, actor=actor, evidence_reference=evidence_reference,
                external_evidence_reference=external_ref, scenario_results=scenario_results,
            )
            s.commit()
            return {
                "channel": channel,
                "merchant_binding_id": merchant.merchant_binding_id,
                "merchant_state": merchant.state,
                "state": "PAYMENT_SANDBOX_CERTIFIED_NOT_LIVE",
                "scenario_results": scenario_results,
                "source_evidence_reference": evidence_reference,
                "executor_evidence_reference": external_ref,
                "callback_signature_verified": True,
                "reconciliation_verified": True,
                "certified_by": actor,
                "payment_sandbox_certified": True,
                "payment_live": False,
                "real_money_moved": False,
                "certification_audit_id": certification_event.audit_id,
                "certification_validity_days": 30,
            }

    def create_payment_link(self, intent_id: str, actor: str) -> dict[str, Any]:
        if not payment_sandbox_executor.configured:
            raise ValueError("EXTERNAL_PAYMENT_SANDBOX_EXECUTOR_NOT_CONFIGURED")
        with SessionLocal() as s:
            intent = s.scalar(select(Intent).where(Intent.payment_intent_id == intent_id).with_for_update())
            if not intent or intent.state != "READY" or not intent.selected_channel:
                raise ValueError("PAYMENT_INTENT_NOT_READY_FOR_LINK")
            cutover_svc.assert_sandbox_execution_allowed(intent.selected_channel)
            merchant = s.scalar(select(Merchant).where(Merchant.channel == intent.selected_channel, Merchant.state == "ACTIVE_CERTIFIED"))
            if not merchant:
                raise ValueError("CERTIFIED_PSP_SANDBOX_MERCHANT_REQUIRED")
            active = s.scalar(select(Attempt).where(Attempt.payment_intent_id == intent_id, Attempt.state.in_(["PROCESSING","UNKNOWN_EXTERNAL_STATE"])))
            if active:
                raise ValueError("ACTIVE_PAYMENT_ATTEMPT_BLOCKS_NEW_LINK")
            result = payment_sandbox_executor.create_payment_link(
                payment_intent_id=intent.payment_intent_id, amount_minor=intent.amount_minor,
                currency=intent.currency, channel=intent.selected_channel,
                idempotency_key=intent.idempotency_key,
            )
            attempt_no = len(s.scalars(select(Attempt).where(Attempt.payment_intent_id == intent_id)).all()) + 1
            attempt = Attempt(
                payment_attempt_id=ident("opa"), payment_intent_id=intent_id, channel=intent.selected_channel,
                attempt_no=attempt_no, external_operation_id=result.external_operation_id,
                channel_idempotency_key=f"{intent.idempotency_key}:{attempt_no}", state="PROCESSING",
                external_invoked=True, created_at=now(), updated_at=now(),
            )
            s.add(attempt); intent.state="PROCESSING"; intent.updated_at=now(); s.commit()
            return {"payment_attempt": out(attempt), "payment_url": result.payment_url, "expires_at": result.expires_at,
                    "evidence_reference": result.evidence_reference, "external_invoked": True, "actor": actor}

    def settlement_release_gate(self, intent_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        fulfillment_ref = str(body.get("hotel_fulfillment_evidence") or "").strip()
        checkout_ref = str(body.get("guest_checkout_reference") or "").strip()
        if not fulfillment_ref or not checkout_ref:
            raise ValueError("FULFILLMENT_AND_CHECKOUT_EVIDENCE_REQUIRED")
        with SessionLocal() as s:
            intent = s.get(Intent, intent_id)
            fulfillment = s.scalar(select(Fulfillment).where(Fulfillment.payment_intent_id == intent_id))
            if not intent or intent.state != "SUCCEEDED":
                raise ValueError("PAYMENT_SUCCESS_REQUIRED_BEFORE_SETTLEMENT_GATE")
            if not fulfillment:
                raise ValueError("SUPPLIER_FULFILLMENT_REQUIRED_BEFORE_SETTLEMENT_GATE")
            return {
                "payment_intent_id": intent_id,
                "state": "SETTLEMENT_RELEASE_ELIGIBLE_NOT_EXECUTED",
                "hotel_fulfillment_evidence": fulfillment_ref,
                "guest_checkout_reference": checkout_ref,
                "payout_executed": False,
                "requires_separate_payout_movement": True,
                "actor": actor,
            }


payment_sandbox_runtime_service = PaymentSandboxRuntimeService()
