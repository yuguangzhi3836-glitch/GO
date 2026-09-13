from __future__ import annotations

from datetime import datetime, timezone
import hashlib, json, uuid
from typing import Any

from sqlalchemy import select

from go_hotel.db.models import (
    AuditEventRow,
    HotelAutoPageEventRow,
    ConnectorCertificationRunRow,
    ProductionConnectorRow,
    HostedDirectHotelRow,
    HostedDirectRoomOfferRow,
    HostedDirectPaymentReadinessRow,
    OmnichannelMerchantBindingRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.hotel_page_production_acceptance import SUMMARY_EVENT
from go_hotel.services.aoluguya_supply_truth import aoluguya_supply_truth_service
from go_hotel.services.payment_sandbox_cutover import payment_sandbox_cutover_service

RESOURCE_TYPE = "R8_2_STAGING_EXECUTION_EVIDENCE"
RUN_ID = "GO_R8_2_STAGING"
AOLUGUYA_SLUG = "aoluguya-harbin"

STAGES = (
    "PRECHECK",
    "RC13_1",
    "RC13_100",
    "RC13_1000",
    "AOLUGUYA_12_TRUTH",
    "AOLUGUYA_ATOMIC_CUTOVER",
    "EXTERNAL_SUPPLIER_SANDBOX",
    "PAYMENT_SANDBOX",
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def ident(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


class StagingExecutionEvidenceOrchestrator:
    def _events(self, s):
        return s.scalars(
            select(AuditEventRow).where(
                AuditEventRow.resource_type == RESOURCE_TYPE,
                AuditEventRow.resource_id == RUN_ID,
            ).order_by(AuditEventRow.created_at.asc(), AuditEventRow.audit_id.asc())
        ).all()

    def _latest_stage_index(self, s) -> int:
        idx = -1
        for row in self._events(s):
            md = row.metadata_json or {}
            if md.get("decision") == "GO" and md.get("stage") in STAGES:
                idx = max(idx, STAGES.index(md["stage"]))
        return idx

    def _append(self, s, stage: str, actor: str, decision: str, blockers: list[str], evidence: dict[str, Any]):
        events = self._events(s)
        previous_hash = (events[-1].metadata_json or {}).get("entry_hash") if events else None
        content = {
            "stage": stage,
            "decision": decision,
            "blockers": blockers,
            "evidence": evidence,
            "previous_hash": previous_hash,
        }
        content_hash = digest(content)
        created = now()
        entry_hash = digest({"content_hash": content_hash, "created_at": created.isoformat(), "previous_hash": previous_hash})
        row = AuditEventRow(
            audit_id=ident("aud"), actor_id=actor, actor_type="ADMIN", supplier_id=None,
            roles=["GO_ADMIN"], session_id=None,
            action=f"R8_2_STAGING_STAGE_{decision}", resource_type=RESOURCE_TYPE, resource_id=RUN_ID,
            request_id=None, client_ip=None, http_method=None, path=None,
            before_state=None, after_state={"stage": stage, "decision": decision},
            decision_id=None, evidence_id=None, approval_id=None,
            metadata_json={
                "schema": "go.r8.2-staging-execution-evidence.v1",
                "stage": stage, "decision": decision, "blockers": blockers,
                "evidence": evidence, "previous_hash": previous_hash,
                "content_hash": content_hash, "entry_hash": entry_hash, "created_at_iso": created.isoformat(), "append_only": True,
                "deployed_parent": "V6.1-R8.2-rc.11+20260823T211759+CST",
                "candidate_only": True,
                "production_live": False,
            }, created_at=created,
        )
        s.add(row)
        s.flush()
        return row

    def _verify_precheck(self) -> tuple[list[str], dict[str, Any]]:
        # Static invariants that RC17 is allowed to attest locally. RDS lineage itself
        # remains a Staging runtime prerequisite and must be supplied as external evidence.
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        migrations = list((root / "alembic" / "versions").glob("*.py"))
        import ast
        revisions = {}
        def literal_assignment(tree, name):
            for node in getattr(tree, "body", []):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == name:
                            try: return ast.literal_eval(node.value)
                            except Exception: return None
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
                    try: return ast.literal_eval(node.value)
                    except Exception: return None
            return None
        for p in migrations:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            revision = literal_assignment(tree, "revision")
            down = literal_assignment(tree, "down_revision")
            if isinstance(revision, str): revisions[revision] = down
        referenced = set()
        for down in revisions.values():
            parents = () if down is None else (down if isinstance(down, tuple) else (down,))
            referenced.update(x for x in parents if isinstance(x, str))
        heads = sorted(set(revisions) - referenced)
        blockers = []
        if len(revisions) != 111: blockers.append("MIGRATION_REVISION_COUNT_111_REQUIRED")
        if heads != ["0111_test_account_expiry"]: blockers.append("MIGRATION_HEAD_0111_REQUIRED")
        return blockers, {
            "revision_count": len(revisions), "heads": heads,
            "rds_lineage_runtime_evidence_required": True,
            "alembic_stamp_forbidden": True,
        }

    def _verify_rc13(self, level: int) -> tuple[list[str], dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.scalars(select(HotelAutoPageEventRow).where(
                HotelAutoPageEventRow.event_type == SUMMARY_EVENT
            ).order_by(HotelAutoPageEventRow.created_at.desc())).all()
            row = next((r for r in rows if int((r.evidence_json or {}).get("level") or 0) == level), None)
            ev = dict(row.evidence_json or {}) if row else {}
        blockers = []
        if not row: blockers.append(f"RC13_{level}_EXECUTION_EVIDENCE_REQUIRED")
        elif ev.get("result") != "PASS": blockers.append(f"RC13_{level}_PASS_REQUIRED")
        elif not all((ev.get("checks") or {}).values()): blockers.append(f"RC13_{level}_ALL_CHECKS_PASS_REQUIRED")
        return blockers, {
            "level": level,
            "batch_id": ev.get("batch_id"),
            "result": ev.get("result"),
            "report_hash": digest(ev) if ev else None,
            "checks": ev.get("checks") or {},
            "executed_at": row.created_at.isoformat() if row else None,
        }

    def _verify_truth(self) -> tuple[list[str], dict[str, Any]]:
        try:
            result = aoluguya_supply_truth_service.evaluate()
        except Exception as exc:
            return [f"AOLUGUYA_TRUTH_EVALUATION_ERROR:{type(exc).__name__}"], {"error": str(exc)}
        checks = result.get("checks") or {}
        blockers = []
        if len(checks) != 12: blockers.append("EXACTLY_12_TRUTH_GATES_REQUIRED")
        if result.get("state") != "PASS" or not all(checks.values()): blockers.extend(result.get("blockers") or ["AOLUGUYA_12_TRUTH_GATES_PASS_REQUIRED"])
        return sorted(set(blockers)), {
            "state": result.get("state"), "checks": checks,
            "truth_gate_count": len(checks), "source_age_seconds": result.get("source_age_seconds"),
            "payment_connected": False, "production_live": False,
        }

    def _verify_cutover(self) -> tuple[list[str], dict[str, Any]]:
        try:
            status = aoluguya_supply_truth_service.status()
        except Exception as exc:
            return [f"AOLUGUYA_CUTOVER_STATUS_ERROR:{type(exc).__name__}"], {"error": str(exc)}
        hp = status.get("hosted_page") or {}
        blockers = []
        if not hp.get("official_projection"): blockers.append("AOLUGUYA_OFFICIAL_PROJECTION_REQUIRED")
        if not hp.get("no_test_truth"): blockers.append("AOLUGUYA_NO_TEST_TRUTH_REQUIRED")
        if hp.get("active_offers") != 9: blockers.append("AOLUGUYA_9_ACTIVE_OFFERS_REQUIRED")
        if hp.get("payment_available") is not False: blockers.append("PAYMENT_MUST_REMAIN_DISCONNECTED")
        return blockers, {
            "hosted_page": hp, "truth_state": status.get("state"),
            "booking_mode_required": "RESERVATION_REQUEST_ONLY",
            "atomic_cutover_verified": not blockers,
            "production_live": False,
        }

    def _verify_external_supplier(self) -> tuple[list[str], dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.execute(
                select(ConnectorCertificationRunRow, ProductionConnectorRow)
                .join(ProductionConnectorRow, ProductionConnectorRow.connector_id == ConnectorCertificationRunRow.connector_id)
                .where(
                    ProductionConnectorRow.vertical == "HOTEL",
                    ProductionConnectorRow.environment == "SANDBOX",
                    ConnectorCertificationRunRow.environment == "SANDBOX",
                    ConnectorCertificationRunRow.result == "PASS",
                )
                .order_by(ConnectorCertificationRunRow.completed_at.desc())
            ).all()
            match = next((pair for pair in rows if (pair[0].evidence_json or {}).get("external_transport_attested") is True), None)
        blockers = []
        if not match:
            blockers.append("ATTESTED_EXTERNAL_HOTEL_SUPPLIER_SANDBOX_CERTIFICATION_REQUIRED")
            return blockers, {"externally_verified": False, "production_live": False}
        run, connector = match
        checks = run.checks_json or {}
        if not checks or not all(checks.values()): blockers.append("EXTERNAL_SUPPLIER_ALL_SCENARIOS_PASS_REQUIRED")
        return blockers, {
            "connector_id": connector.connector_id, "supplier": connector.supplier_legal_name,
            "certification_run_id": run.certification_run_id, "suite_version": run.suite_version,
            "evidence_hash": run.evidence_hash, "checks": checks,
            "externally_verified": not blockers, "production_live": False,
        }

    def _verify_payment(self) -> tuple[list[str], dict[str, Any]]:
        try:
            st = payment_sandbox_cutover_service.status("ALIPAY")
            ledger = payment_sandbox_cutover_service.evidence_ledger("ALIPAY")
        except Exception as exc:
            return [f"PAYMENT_SANDBOX_STATUS_ERROR:{type(exc).__name__}"], {"error": str(exc)}
        blockers = []
        if not st.get("certification_valid"): blockers.append("VALID_PAYMENT_SANDBOX_CERTIFICATION_REQUIRED")
        if st.get("merchant_state") != "ACTIVE_CERTIFIED": blockers.append("PAYMENT_MERCHANT_ACTIVE_CERTIFIED_REQUIRED")
        if not ledger.get("chain_valid"): blockers.append("PAYMENT_CERTIFICATION_EVIDENCE_CHAIN_VALID_REQUIRED")
        if st.get("payment_live") is not False: blockers.append("PAYMENT_LIVE_MUST_REMAIN_FALSE")
        if st.get("production_cutover_available") is not False: blockers.append("PRODUCTION_CUTOVER_MUST_REMAIN_UNAVAILABLE")
        return blockers, {
            "merchant_state": st.get("merchant_state"), "certification_valid": st.get("certification_valid"),
            "certification_expires_at": st.get("certification_expires_at"),
            "ledger_chain_valid": ledger.get("chain_valid"), "ledger_entry_count": ledger.get("entry_count"),
            "payment_live": False, "production_cutover_available": False,
            "state": "PAYMENT_SANDBOX_CERTIFIED_NOT_LIVE" if not blockers else "NOT_CERTIFIED",
        }

    def verify_stage(self, stage: str) -> tuple[list[str], dict[str, Any]]:
        if stage == "PRECHECK": return self._verify_precheck()
        if stage.startswith("RC13_"): return self._verify_rc13(int(stage.split("_")[1]))
        if stage == "AOLUGUYA_12_TRUTH": return self._verify_truth()
        if stage == "AOLUGUYA_ATOMIC_CUTOVER": return self._verify_cutover()
        if stage == "EXTERNAL_SUPPLIER_SANDBOX": return self._verify_external_supplier()
        if stage == "PAYMENT_SANDBOX": return self._verify_payment()
        raise ValueError("UNKNOWN_STAGING_EXECUTION_STAGE")

    def advance(self, stage: str, actor: str, evidence_reference: str, *, rds_lineage_attested: bool = False) -> dict[str, Any]:
        if stage not in STAGES: raise ValueError("UNKNOWN_STAGING_EXECUTION_STAGE")
        if not str(evidence_reference or "").strip(): raise ValueError("EVIDENCE_REFERENCE_REQUIRED")
        with SessionLocal() as s:
            current = self._latest_stage_index(s)
            target = STAGES.index(stage)
            if target <= current:
                raise ValueError("STAGE_ALREADY_SEALED_APPEND_ONLY")
            if target != current + 1:
                raise ValueError(f"STAGE_SEQUENCE_LOCKED_NEXT_REQUIRED:{STAGES[current+1]}")
        blockers, evidence = self.verify_stage(stage)
        if stage == "PRECHECK" and not rds_lineage_attested:
            blockers.append("RDS_LINEAGE_RUNTIME_ATTESTATION_REQUIRED")
        evidence = dict(evidence)
        evidence["evidence_reference"] = evidence_reference
        evidence["rds_lineage_attested"] = bool(rds_lineage_attested) if stage == "PRECHECK" else None
        decision = "GO" if not blockers else "NO_GO"
        with SessionLocal() as s:
            row = self._append(s, stage, actor, decision, sorted(set(blockers)), evidence)
            s.commit()
            result = dict(row.metadata_json or {})
            result["audit_id"] = row.audit_id
        if blockers:
            raise ValueError("STAGING_EXECUTION_NO_GO:" + ",".join(sorted(set(blockers))))
        return result

    def status(self) -> dict[str, Any]:
        with SessionLocal() as s:
            events = self._events(s)
            latest = self._latest_stage_index(s)
            items = []
            previous = None
            chain_valid = True
            for row in events:
                md = dict(row.metadata_json or {})
                expected_content = {
                    "stage": md.get("stage"), "decision": md.get("decision"),
                    "blockers": md.get("blockers") or [], "evidence": md.get("evidence") or {},
                    "previous_hash": md.get("previous_hash"),
                }
                valid = md.get("previous_hash") == previous and md.get("content_hash") == digest(expected_content)
                valid = valid and md.get("entry_hash") == digest({"content_hash": md.get("content_hash"), "created_at": md.get("created_at_iso"), "previous_hash": md.get("previous_hash")})
                chain_valid = chain_valid and valid
                previous = md.get("entry_hash")
                items.append({"audit_id": row.audit_id, "created_at": row.created_at.isoformat(), **md, "entry_valid": valid})
            next_stage = STAGES[latest + 1] if latest + 1 < len(STAGES) else None
            return {
                "run_id": RUN_ID, "schema": "go.r8.2-staging-execution-evidence.v1",
                "sealed_go_stage_count": latest + 1, "next_stage": next_stage,
                "complete": latest == len(STAGES) - 1,
                "final_state": "STAGING_EVIDENCE_CHAIN_COMPLETE_NOT_LIVE" if latest == len(STAGES)-1 else "IN_PROGRESS",
                "chain_valid": chain_valid, "events": items,
                "deployed_parent": "V6.1-R8.2-rc.11+20260823T211759+CST",
                "candidate_not_deployed": True, "production_live": False,
            }


staging_execution_evidence_orchestrator = StagingExecutionEvidenceOrchestrator()
