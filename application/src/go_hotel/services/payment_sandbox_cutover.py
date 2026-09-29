from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import select, or_, cast, Text, update, false, text

from go_hotel.connectors.payment_sandbox import payment_sandbox_executor
from go_hotel.db.models import (
    ApprovalRequestRow,
    AuditEventRow,
    HostedDirectHotelRow,
    HostedDirectPaymentReadinessRow,
    IncidentControlRow,
    OmnichannelMerchantBindingRow as Merchant,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.omnichannel_payment import ident, out

AOLUGUYA_SLUG = "aoluguya-harbin"
CERTIFIED_STATE = "ACTIVE_CERTIFIED"
UNCERTIFIED_STATE = "REFERENCE_BOUND_NOT_CERTIFIED"
CERT_VALIDITY_DAYS = 30
CUTOVER_APPROVAL_TTL_MINUTES = 30
RESOURCE_TYPE = "PAYMENT_SANDBOX_CERTIFICATION"
EXECUTOR_KILL_SCOPE_PREFIX = "PAYMENT_SANDBOX_EXECUTOR:"


def now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()



def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _vault_ref(value: str | None) -> bool:
    return bool(
        value
        and str(value).startswith(
            ("kms://", "vault://", "cert://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://")
        )
    )


class PaymentSandboxCutoverService:
    def _hotel(self, s):
        return s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))

    def _merchant(self, s, hotel_id: str, channel: str, lock: bool = False):
        q = select(Merchant).where(
            Merchant.owner_type == "HOSTED_HOTEL",
            Merchant.owner_id == hotel_id,
            Merchant.channel == channel,
        )
        if lock:
            q = q.with_for_update()
        return s.scalar(q)

    def _events(self, s, channel: str):
        candidates = s.scalars(
            select(AuditEventRow)
            .where(
                or_(AuditEventRow.resource_type == RESOURCE_TYPE,
                    cast(AuditEventRow.roles, Text).contains('"PAYMENT_SANDBOX_CONTROL"')),
            )
            .order_by(AuditEventRow.created_at.asc(), AuditEventRow.audit_id.asc())
        ).all()
        # Membership cannot rely solely on fields that are themselves being
        # verified. Recover linked predecessors/successors even if their resource
        # identity was altered; validation will then reject the damaged record.
        by_hash = {}
        by_previous = {}
        for event in candidates:
            meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
            for index, key in ((by_hash, "entry_hash"), (by_previous, "previous_hash")):
                value = meta.get(key)
                if isinstance(value, str):
                    index.setdefault(value, []).append(event)
        selected = {}
        pending = []
        for event in candidates:
            meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
            state = event.after_state if isinstance(event.after_state, dict) else {}
            bound_hash = _digest({
                "channel": channel, "action": event.action, "actor": event.actor_id,
                "payload": state.get("immutable_payload"),
                "evidence_reference": meta.get("evidence_reference"),
                "approval_id": event.approval_id, "previous_hash": meta.get("previous_hash"),
            })
            if event.resource_id == channel or meta.get("entry_hash") == bound_hash:
                pending.append(event)
        while pending:
            event = pending.pop()
            if event.audit_id in selected:
                continue
            selected[event.audit_id] = event
            meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
            previous, entry = meta.get("previous_hash"), meta.get("entry_hash")
            if isinstance(previous, str):
                pending.extend(by_hash.get(previous, []))
            if isinstance(entry, str):
                pending.extend(by_previous.get(entry, []))
        events = [event for event in candidates if event.audit_id in selected]
        # Timestamp ties (including a frozen business clock) must not reorder
        # a valid chain by random audit IDs. Follow the persisted hash links.
        successors = {}
        for event in events:
            meta = event.metadata_json
            if not isinstance(meta, dict):
                return events
            previous = meta.get("previous_hash")
            if previous is not None and not isinstance(previous, str):
                return events
            if previous in successors:
                return events  # A fork is rejected by content validation below.
            successors[previous] = event
        ordered = []
        previous = None
        seen = set()
        while previous in successors:
            event = successors[previous]
            if event.audit_id in seen:
                return events
            seen.add(event.audit_id)
            ordered.append(event)
            previous = event.metadata_json.get("entry_hash")
            if not isinstance(previous, str):
                return events
        return ordered if len(ordered) == len(events) else events

    def _chain_valid(self, events, channel: str) -> bool:
        previous_hash = None
        seen_hashes = set()
        for event in events:
            meta = event.metadata_json
            state = event.after_state
            if not isinstance(meta, dict) or not isinstance(state, dict):
                return False
            payload = state.get("immutable_payload")
            if not isinstance(payload, dict):
                return False
            normalized = {
                "channel": channel, "action": event.action,
                "actor": event.actor_id, "payload": payload,
                "evidence_reference": meta.get("evidence_reference"),
                "approval_id": event.approval_id, "previous_hash": previous_hash,
            }
            expected = _digest(normalized)
            if (event.resource_type != RESOURCE_TYPE or event.resource_id != channel
                    or meta.get("append_only") is not True
                    or meta.get("previous_hash") != previous_hash
                    or meta.get("content_hash") != _digest(payload)
                    or meta.get("entry_hash") != expected or expected in seen_hashes):
                return False
            seen_hashes.add(expected)
            previous_hash = expected
        return True

    def _append_event(
        self,
        s,
        *,
        channel: str,
        action: str,
        actor: str,
        payload: dict[str, Any],
        evidence_reference: str | None = None,
        approval_id: str | None = None,
    ) -> AuditEventRow:
        # Serialize every writer before reading the chain tip. PostgreSQL uses
        # a transaction-scoped channel lock; SQLite takes its database write
        # lock via a zero-row update. Neither creates a business/audit fact.
        dialect = s.get_bind().dialect.name
        if dialect == "postgresql":
            lock_key = int.from_bytes(hashlib.sha256(
                (RESOURCE_TYPE + ":" + channel).encode()).digest()[:8], "big", signed=True)
            s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        elif dialect == "sqlite":
            s.execute(update(AuditEventRow).where(false()).values(action=AuditEventRow.action)
                      .execution_options(synchronize_session=False, autoflush=False))
        else:
            raise ValueError("PAYMENT_SANDBOX_AUDIT_DATABASE_UNSUPPORTED")
        events = self._events(s, channel)
        if not self._chain_valid(events, channel):
            raise ValueError("PAYMENT_SANDBOX_EVIDENCE_CHAIN_INVALID")
        previous_hash = events[-1].metadata_json.get("entry_hash") if events else None
        normalized = {
            "channel": channel,
            "action": action,
            "actor": actor,
            "payload": payload,
            "evidence_reference": evidence_reference,
            "approval_id": approval_id,
            "previous_hash": previous_hash,
        }
        entry_hash = _digest(normalized)

        if evidence_reference:
            content_hash = _digest(payload)
            for event in events:
                meta = event.metadata_json or {}
                if meta.get("evidence_reference") == evidence_reference:
                    if (meta.get("content_hash") != content_hash
                            or event.action != action or event.actor_id != actor
                            or event.approval_id != approval_id):
                        raise ValueError("PAYMENT_SANDBOX_EVIDENCE_REFERENCE_CONFLICT")
                    return event
        else:
            content_hash = _digest(payload)

        event = AuditEventRow(
            audit_id=ident("pae"),
            actor_id=actor,
            actor_type="ADMIN",
            supplier_id=None,
            roles=["PAYMENT_SANDBOX_CONTROL"],
            session_id=None,
            action=action,
            resource_type=RESOURCE_TYPE,
            resource_id=channel,
            request_id=None,
            client_ip=None,
            http_method=None,
            path=None,
            before_state=None,
            after_state={"immutable_payload": payload},
            decision_id=None,
            evidence_id=None,
            approval_id=approval_id,
            metadata_json={
                "append_only": True,
                "evidence_reference": evidence_reference,
                "content_hash": content_hash,
                "previous_hash": previous_hash,
                "entry_hash": entry_hash,
            },
            created_at=now(),
        )
        s.add(event)
        s.flush()
        return event

    def record_certification_grant(
        self,
        s,
        *,
        channel: str,
        actor: str,
        evidence_reference: str,
        external_evidence_reference: str,
        scenario_results: dict[str, str],
    ) -> AuditEventRow:
        issued_at = now()
        expires_at = issued_at + timedelta(days=CERT_VALIDITY_DAYS)
        return self._append_event(
            s,
            channel=channel,
            action="PAYMENT_SANDBOX_CERTIFICATION_GRANTED",
            actor=actor,
            evidence_reference=evidence_reference,
            payload={
                "issued_at": issued_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "external_evidence_reference": external_evidence_reference,
                "scenario_results": scenario_results,
                "payment_live": False,
                "real_money_moved": False,
            },
        )

    def _kill_switch_active(self, s, channel: str) -> bool:
        row = s.scalar(
            select(IncidentControlRow).where(
                IncidentControlRow.scope == EXECUTOR_KILL_SCOPE_PREFIX + channel
            )
        )
        return bool(row and row.status == "ACTIVE" and (row.expires_at is None or _utc(row.expires_at) > now()))

    def _latest_control_state(self, s, channel: str) -> dict[str, Any]:
        events = self._events(s, channel)
        chain_valid = self._chain_valid(events, channel)
        grant = None
        invalidator = None
        for event in events if chain_valid else []:
            if event.action == "PAYMENT_SANDBOX_CERTIFICATION_GRANTED":
                grant = event
                invalidator = None
            elif event.action in {
                "PAYMENT_SANDBOX_CERTIFICATION_REVOKED",
                "PAYMENT_SANDBOX_CERTIFICATION_EXPIRED",
                "PAYMENT_SANDBOX_CREDENTIAL_ROTATED",
            } and grant:
                invalidator = event
        expires_at = None
        if grant:
            raw = (grant.after_state or {}).get("immutable_payload", {}).get("expires_at")
            try:
                expires_at = datetime.fromisoformat(raw)
                if expires_at.tzinfo is None:
                    expires_at = None
            except (ValueError, TypeError):
                expires_at = None
        expired = bool(expires_at and expires_at <= now())
        valid = bool(chain_valid and grant and expires_at and not invalidator and not expired)
        return {
            "grant": grant,
            "invalidator": invalidator,
            "expires_at": expires_at,
            "expired": expired,
            "valid": valid,
            "events": events,
            "chain_valid": chain_valid,
        }

    def status(self, channel: str = "ALIPAY") -> dict[str, Any]:
        channel = str(channel or "").upper()
        with SessionLocal() as s:
            hotel = self._hotel(s)
            merchant = self._merchant(s, hotel.hosted_hotel_id, channel) if hotel else None
            readiness = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id) if hotel else None
            ctl = self._latest_control_state(s, channel)
            kill = self._kill_switch_active(s, channel)
            cert_valid = bool(
                ctl["valid"]
                and merchant
                and merchant.state == CERTIFIED_STATE
                and readiness
                and readiness.application_state == "SANDBOX_CERTIFIED_NOT_LIVE"
            )
            return {
                "channel": channel,
                "state": "PAYMENT_SANDBOX_CERTIFIED_NOT_LIVE" if cert_valid else "PAYMENT_SANDBOX_NOT_CERTIFIED_OR_SUSPENDED",
                "certification_valid": cert_valid,
                "certification_expires_at": ctl["expires_at"].isoformat() if ctl["expires_at"] else None,
                "certification_invalidated_by": ctl["invalidator"].action if ctl["invalidator"] else ("EXPIRY" if ctl["expired"] else None),
                "merchant_state": merchant.state if merchant else None,
                "readiness_state": readiness.application_state if readiness else None,
                "executor_configured": payment_sandbox_executor.configured,
                "executor_kill_switch_active": kill,
                "sandbox_execution_allowed": cert_valid and payment_sandbox_executor.configured and not kill,
                "payment_live": False,
                "production_cutover_available": False,
                "real_money_moved": False,
                "evidence_chain_length": len(ctl["events"]),
                "evidence_chain_valid": ctl["chain_valid"],
                "latest_entry_hash": (ctl["events"][-1].metadata_json.get("entry_hash")
                    if ctl["events"] and isinstance(ctl["events"][-1].metadata_json, dict) else None),
            }

    def assert_sandbox_execution_allowed(self, channel: str) -> None:
        state = self.status(channel)
        if not state["certification_valid"]:
            raise ValueError("VALID_PAYMENT_SANDBOX_CERTIFICATION_REQUIRED")
        if state["executor_kill_switch_active"]:
            raise ValueError("PAYMENT_SANDBOX_EXECUTOR_KILL_SWITCH_ACTIVE")
        if not state["executor_configured"]:
            raise ValueError("EXTERNAL_PAYMENT_SANDBOX_EXECUTOR_NOT_CONFIGURED")

    def revoke_certification(self, channel: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        channel = str(channel or "").upper()
        reason = str(body.get("reason") or "").strip()
        evidence_reference = str(body.get("evidence_reference") or "").strip()
        if not reason or not evidence_reference.startswith(("evidence://", "cert://", "psp-sandbox://")):
            raise ValueError("REVOCATION_REASON_AND_EVIDENCE_REQUIRED")
        with SessionLocal() as s:
            hotel = self._hotel(s)
            merchant = self._merchant(s, hotel.hosted_hotel_id, channel, lock=True) if hotel else None
            if not merchant:
                raise ValueError("PAYMENT_SANDBOX_MERCHANT_BINDING_REQUIRED")
            merchant.state = UNCERTIFIED_STATE
            merchant.updated_at = now()
            readiness = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id)
            if readiness:
                readiness.application_state = "SANDBOX_CERTIFICATION_REVOKED"
                readiness.blockers_json = ["PAYMENT_SANDBOX_RECERTIFICATION_REQUIRED"]
                readiness.updated_at = now()
            event = self._append_event(
                s,
                channel=channel,
                action="PAYMENT_SANDBOX_CERTIFICATION_REVOKED",
                actor=actor,
                evidence_reference=evidence_reference,
                payload={"reason": reason, "payment_live": False},
            )
            s.commit()
            return {"state": "PAYMENT_SANDBOX_CERTIFICATION_REVOKED", "merchant_state": merchant.state, "audit_id": event.audit_id, "payment_live": False}

    def expire_if_due(self, channel: str, actor: str = "SYSTEM") -> dict[str, Any]:
        channel = str(channel or "").upper()
        with SessionLocal() as s:
            ctl = self._latest_control_state(s, channel)
            if not ctl["grant"] or not ctl["expired"] or ctl["invalidator"]:
                return {"expired": False, "payment_live": False}
            hotel = self._hotel(s)
            merchant = self._merchant(s, hotel.hosted_hotel_id, channel, lock=True) if hotel else None
            if merchant:
                merchant.state = UNCERTIFIED_STATE
                merchant.updated_at = now()
            readiness = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id) if hotel else None
            if readiness:
                readiness.application_state = "SANDBOX_CERTIFICATION_EXPIRED"
                readiness.blockers_json = ["PAYMENT_SANDBOX_RECERTIFICATION_REQUIRED"]
                readiness.updated_at = now()
            event = self._append_event(
                s,
                channel=channel,
                action="PAYMENT_SANDBOX_CERTIFICATION_EXPIRED",
                actor=actor,
                payload={"expired_at": ctl["expires_at"].isoformat(), "payment_live": False},
            )
            s.commit()
            return {"expired": True, "merchant_state": merchant.state if merchant else None, "audit_id": event.audit_id, "payment_live": False}

    def rotate_credentials(self, channel: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        channel = str(channel or "").upper()
        credential_reference = str(body.get("credential_reference") or "").strip()
        webhook_key_reference = str(body.get("webhook_key_reference") or "").strip()
        evidence_reference = str(body.get("evidence_reference") or "").strip()
        if not _vault_ref(credential_reference) or not _vault_ref(webhook_key_reference):
            raise ValueError("ROTATED_CREDENTIAL_AND_WEBHOOK_VAULT_REFERENCES_REQUIRED")
        if not evidence_reference.startswith(("evidence://", "cert://")):
            raise ValueError("CREDENTIAL_ROTATION_EVIDENCE_REQUIRED")
        with SessionLocal() as s:
            hotel = self._hotel(s)
            merchant = self._merchant(s, hotel.hosted_hotel_id, channel, lock=True) if hotel else None
            if not merchant:
                raise ValueError("PAYMENT_SANDBOX_MERCHANT_BINDING_REQUIRED")
            old_refs = {
                "credential_reference_hash": _digest(merchant.credential_reference),
                "webhook_key_reference_hash": _digest(merchant.webhook_key_reference),
            }
            merchant.credential_reference = credential_reference
            merchant.webhook_key_reference = webhook_key_reference
            merchant.state = UNCERTIFIED_STATE
            merchant.updated_at = now()
            readiness = s.get(HostedDirectPaymentReadinessRow, hotel.hosted_hotel_id)
            if readiness:
                readiness.application_state = "CREDENTIAL_ROTATED_REQUIRES_RECERTIFICATION"
                readiness.blockers_json = ["PAYMENT_SANDBOX_RECERTIFICATION_REQUIRED"]
                readiness.updated_at = now()
            event = self._append_event(
                s,
                channel=channel,
                action="PAYMENT_SANDBOX_CREDENTIAL_ROTATED",
                actor=actor,
                evidence_reference=evidence_reference,
                payload={
                    **old_refs,
                    "new_credential_reference_hash": _digest(credential_reference),
                    "new_webhook_key_reference_hash": _digest(webhook_key_reference),
                    "plaintext_secret_persisted": False,
                    "payment_live": False,
                },
            )
            s.commit()
            return {"state": "CREDENTIAL_ROTATED_REQUIRES_RECERTIFICATION", "merchant_state": merchant.state, "audit_id": event.audit_id, "payment_live": False}

    def set_executor_kill_switch(self, channel: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        channel = str(channel or "").upper()
        active = bool(body.get("active", True))
        reason = str(body.get("reason") or "").strip()
        if active and not reason:
            raise ValueError("KILL_SWITCH_REASON_REQUIRED")
        with SessionLocal() as s:
            scope = EXECUTOR_KILL_SCOPE_PREFIX + channel
            row = s.scalar(select(IncidentControlRow).where(IncidentControlRow.scope == scope))
            if not row:
                row = IncidentControlRow(control_id=ident("ic"), scope=scope, status="INACTIVE", updated_at=now())
                s.add(row)
            row.status = "ACTIVE" if active else "INACTIVE"
            row.reason = reason if active else None
            row.activated_by = actor if active else None
            row.activated_at = now() if active else None
            row.expires_at = None
            row.updated_at = now()
            event = self._append_event(
                s,
                channel=channel,
                action="PAYMENT_SANDBOX_EXECUTOR_KILL_SWITCH_" + ("ACTIVATED" if active else "CLEARED"),
                actor=actor,
                payload={"reason": reason, "active": active, "payment_live": False},
            )
            s.commit()
            return {"channel": channel, "kill_switch_active": active, "audit_id": event.audit_id, "payment_live": False}

    def request_cutover(self, channel: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        channel = str(channel or "").upper()
        justification = str(body.get("justification") or "").strip()
        evidence_reference = str(body.get("evidence_reference") or "").strip()
        if not justification or not evidence_reference.startswith(("evidence://", "cert://")):
            raise ValueError("CUTOVER_JUSTIFICATION_AND_EVIDENCE_REQUIRED")
        self.assert_sandbox_execution_allowed(channel)
        with SessionLocal() as s:
            approval = ApprovalRequestRow(
                approval_id=ident("apr"),
                operation_type="PAYMENT_PRODUCTION_CUTOVER",
                subject_type="PAYMENT_SANDBOX_MERCHANT",
                subject_id=channel,
                requested_by=actor,
                approved_by=None,
                status="PENDING",
                request_payload={
                    "justification": justification,
                    "evidence_reference": evidence_reference,
                    "requested_target": "PRODUCTION_PAYMENT_ENABLEMENT",
                    "execution_in_this_release": False,
                },
                approval_note=None,
                created_at=now(),
                approved_at=None,
                consumed_at=None,
                expires_at=now() + timedelta(minutes=CUTOVER_APPROVAL_TTL_MINUTES),
            )
            s.add(approval)
            event = self._append_event(
                s,
                channel=channel,
                action="PAYMENT_PRODUCTION_CUTOVER_REQUESTED",
                actor=actor,
                evidence_reference=evidence_reference,
                approval_id=approval.approval_id,
                payload={"justification": justification, "execution_in_this_release": False, "payment_live": False},
            )
            s.commit()
            return {"approval": out(approval), "audit_id": event.audit_id, "state": "CUTOVER_APPROVAL_PENDING_NOT_LIVE", "payment_live": False}

    def approve_cutover(self, approval_id: str, body: dict[str, Any], actor: str) -> dict[str, Any]:
        note = str(body.get("approval_note") or "").strip()
        if not note:
            raise ValueError("CUTOVER_APPROVAL_NOTE_REQUIRED")
        with SessionLocal() as s:
            approval = s.get(ApprovalRequestRow, approval_id)
            if not approval or approval.operation_type != "PAYMENT_PRODUCTION_CUTOVER":
                raise ValueError("PAYMENT_CUTOVER_APPROVAL_NOT_FOUND")
            if approval.status != "PENDING":
                raise ValueError("PAYMENT_CUTOVER_APPROVAL_NOT_PENDING")
            if approval.requested_by == actor:
                raise ValueError("PAYMENT_CUTOVER_MAKER_CHECKER_REQUIRED")
            if _utc(approval.expires_at) <= now():
                approval.status = "EXPIRED"
                s.commit()
                raise ValueError("PAYMENT_CUTOVER_APPROVAL_EXPIRED")
            channel = approval.subject_id
        self.assert_sandbox_execution_allowed(channel)
        with SessionLocal() as s:
            approval = s.get(ApprovalRequestRow, approval_id)
            if approval.status != "PENDING":
                raise ValueError("PAYMENT_CUTOVER_APPROVAL_NOT_PENDING")
            approval.approved_by = actor
            approval.approval_note = note
            approval.approved_at = now()
            approval.status = "APPROVED_NOT_EXECUTED"
            event = self._append_event(
                s,
                channel=channel,
                action="PAYMENT_PRODUCTION_CUTOVER_APPROVED_NOT_EXECUTED",
                actor=actor,
                approval_id=approval.approval_id,
                payload={
                    "maker": approval.requested_by,
                    "checker": actor,
                    "approval_note": note,
                    "production_cutover_available": False,
                    "payment_live": False,
                },
            )
            s.commit()
            return {
                "approval": out(approval),
                "audit_id": event.audit_id,
                "state": "PAYMENT_CUTOVER_APPROVED_NOT_EXECUTED",
                "production_cutover_available": False,
                "payment_live": False,
                "real_money_moved": False,
            }

    def evidence_ledger(self, channel: str = "ALIPAY") -> dict[str, Any]:
        channel = str(channel or "").upper()
        with SessionLocal() as s:
            events = self._events(s, channel)
            chain_ok = self._chain_valid(events, channel)
            rendered = []
            for event in events:
                meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
                rendered.append({
                    "audit_id": event.audit_id,
                    "action": event.action,
                    "actor_id": event.actor_id,
                    "created_at": event.created_at.isoformat(),
                    "evidence_reference": meta.get("evidence_reference"),
                    "content_hash": meta.get("content_hash"),
                    "previous_hash": meta.get("previous_hash"),
                    "entry_hash": meta.get("entry_hash"),
                    "append_only": meta.get("append_only") is True,
                })
            return {
                "channel": channel,
                "append_only": True,
                "chain_valid": chain_ok,
                "entry_count": len(rendered),
                "entries": rendered,
                "payment_live": False,
            }


payment_sandbox_cutover_service = PaymentSandboxCutoverService()
