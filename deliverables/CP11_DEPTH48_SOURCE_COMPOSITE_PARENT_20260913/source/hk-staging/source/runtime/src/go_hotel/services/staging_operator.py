from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from go_hotel.db.models import AuditEventRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.staging_execution_evidence_orchestrator import (
    RESOURCE_TYPE,
    RUN_ID,
    STAGES,
    digest,
    staging_execution_evidence_orchestrator,
)

ARTIFACT_SCHEMA = "go.r8.2-staging-checkpoint-seal.v1"
BUNDLE_SCHEMA = "go.r8.2-staging-evidence-bundle.v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class StagingOperatorService:
    def _go_event(self, stage: str) -> AuditEventRow | None:
        with SessionLocal() as s:
            rows = s.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.resource_type == RESOURCE_TYPE,
                    AuditEventRow.resource_id == RUN_ID,
                ).order_by(AuditEventRow.created_at.asc(), AuditEventRow.audit_id.asc())
            ).all()
            for row in rows:
                md = row.metadata_json or {}
                if md.get("stage") == stage and md.get("decision") == "GO":
                    s.expunge(row)
                    return row
        return None

    def operator_status(self) -> dict[str, Any]:
        chain = staging_execution_evidence_orchestrator.status()
        next_stage = chain.get("next_stage")
        blockers: list[str] = []
        observed: dict[str, Any] = {}
        if next_stage:
            blockers, observed = staging_execution_evidence_orchestrator.verify_stage(next_stage)
            blockers = sorted(set(blockers))
            # PRECHECK has one runtime-only requirement that cannot be inferred locally.
            if next_stage == "PRECHECK":
                blockers = sorted(set(blockers + ["RDS_LINEAGE_RUNTIME_ATTESTATION_REQUIRED"]))
        missing = [self._missing_evidence_hint(x) for x in blockers]
        return {
            "run_id": RUN_ID,
            "current_checkpoint": chain["events"][-1]["stage"] if chain.get("events") and chain["events"][-1].get("decision") == "GO" else None,
            "sealed_go_stage_count": chain.get("sealed_go_stage_count", 0),
            "next_checkpoint": next_stage,
            "checkpoint_order": list(STAGES),
            "blockers": blockers,
            "missing_evidence": missing,
            "observed_next_stage_facts": observed,
            "chain_valid": chain.get("chain_valid"),
            "complete": chain.get("complete"),
            "final_state": chain.get("final_state"),
            "deployed_parent": chain.get("deployed_parent"),
            "candidate_not_deployed": True,
            "production_live": False,
        }

    @staticmethod
    def _missing_evidence_hint(blocker: str) -> dict[str, str]:
        mapping = {
            "RDS_LINEAGE_RUNTIME_ATTESTATION_REQUIRED": "Attach actual Hong Kong RDS alembic_version evidence showing exactly one row and current head 0111_test_account_expiry.",
            "MIGRATION_REVISION_COUNT_111_REQUIRED": "Restore frozen 111-revision code lineage before Staging execution.",
            "MIGRATION_HEAD_0111_REQUIRED": "Restore code migration head to 0111_test_account_expiry; do not stamp.",
            "RC13_1_EXECUTION_EVIDENCE_REQUIRED": "Run RC13.1 progressive acceptance at exact level 1 and persist its PASS evidence.",
            "RC13_100_EXECUTION_EVIDENCE_REQUIRED": "Run RC13.1 progressive acceptance at exact level 100 and persist its PASS evidence.",
            "RC13_1000_EXECUTION_EVIDENCE_REQUIRED": "Run RC13.1 progressive acceptance at exact level 1000 and persist its PASS evidence.",
            "EXACTLY_12_TRUTH_GATES_REQUIRED": "Provide the official AOLUGUYA Supply Snapshot and pass exactly 12 truth gates.",
            "AOLUGUYA_OFFICIAL_PROJECTION_REQUIRED": "Complete the controlled official AOLUGUYA projection before sealing atomic cutover.",
            "AOLUGUYA_NO_TEST_TRUTH_REQUIRED": "Remove mixed/test truth from the projected official supply state.",
            "AOLUGUYA_9_ACTIVE_OFFERS_REQUIRED": "Verify exactly 9 active official offers after cutover.",
            "ATTESTED_EXTERNAL_HOTEL_SUPPLIER_SANDBOX_CERTIFICATION_REQUIRED": "Attach real external HOTEL Sandbox transport/certification evidence; framework-only evidence is insufficient.",
            "VALID_PAYMENT_SANDBOX_CERTIFICATION_REQUIRED": "Run real PSP Sandbox certification with valid merchant/credential/executor evidence.",
            "PAYMENT_MERCHANT_ACTIVE_CERTIFIED_REQUIRED": "Payment merchant must be ACTIVE_CERTIFIED in Sandbox only.",
            "PAYMENT_CERTIFICATION_EVIDENCE_CHAIN_VALID_REQUIRED": "Repair or re-run Payment Sandbox certification so its evidence ledger is chain-valid.",
        }
        return {"blocker": blocker, "required_evidence": mapping.get(blocker, "Resolve the blocker and attach independently verifiable execution evidence before advancing.")}

    def export_bundle(self) -> dict[str, Any]:
        chain = staging_execution_evidence_orchestrator.status()
        operator = self.operator_status()
        payload = {
            "schema": BUNDLE_SCHEMA,
            "run_id": RUN_ID,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "deployed_parent": chain.get("deployed_parent"),
            "candidate_not_deployed": True,
            "production_live": False,
            "operator_status": operator,
            "chain": chain,
        }
        payload["bundle_sha256"] = _sha256(payload)
        return payload

    def seal_checkpoint(self, stage: str) -> dict[str, Any]:
        if stage not in STAGES:
            raise ValueError("UNKNOWN_STAGING_EXECUTION_STAGE")
        chain = staging_execution_evidence_orchestrator.status()
        if not chain.get("chain_valid"):
            raise ValueError("STAGING_EVIDENCE_CHAIN_INVALID")
        row = self._go_event(stage)
        if not row:
            raise ValueError("CHECKPOINT_NOT_GO_CANNOT_SEAL")
        md = dict(row.metadata_json or {})
        artifact = {
            "schema": ARTIFACT_SCHEMA,
            "run_id": RUN_ID,
            "stage": stage,
            "decision": "GO",
            "source_audit_id": row.audit_id,
            "source_entry_hash": md.get("entry_hash"),
            "source_content_hash": md.get("content_hash"),
            "source_created_at_iso": md.get("created_at_iso"),
            "evidence_reference": (md.get("evidence") or {}).get("evidence_reference"),
            "deployed_parent": md.get("deployed_parent"),
            "candidate_not_deployed": True,
            "production_live": False,
        }
        artifact["artifact_sha256"] = _sha256(artifact)
        return artifact

    @staticmethod
    def write_json_artifact(payload: dict[str, Any], output: str | Path) -> dict[str, str]:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n"
        path.write_text(body, encoding="utf-8")
        file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        sidecar = Path(str(path) + ".sha256")
        sidecar.write_text(f"{file_sha}  {path.name}\n", encoding="utf-8")
        return {"artifact_path": str(path), "sha256_path": str(sidecar), "file_sha256": file_sha}


staging_operator_service = StagingOperatorService()
