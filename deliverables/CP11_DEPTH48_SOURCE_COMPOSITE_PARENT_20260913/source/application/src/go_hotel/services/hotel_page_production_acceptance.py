from __future__ import annotations

from datetime import datetime, timezone
import os
import uuid

from sqlalchemy import delete, func, select, distinct

from go_hotel.db.models import (
    HotelAutoPageEventRow,
    HotelAutoPageVersionRow,
    HotelCanonicalProfileRow,
    HotelContactPointRow,
    HotelContentSourceSnapshotRow,
    HotelRegistrationDirectRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service
from go_hotel.services.hotel_discovery_orchestrator import hotel_discovery_orchestrator_service
from go_hotel.services.media_harvester import media_harvester_service

LEVELS = (1, 100, 1000)
SUMMARY_EVENT = "RC13_BATCH_ACCEPTANCE_RESULT"
START_EVENT = "RC13_BATCH_ACCEPTANCE_STARTED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class HotelPageProductionAcceptanceService:
    """Controlled Staging acceptance harness for RC13.

    The harness deliberately uses provider payloads rather than crawling live sites.
    It validates the production pipeline without connecting real supply or payment.
    No schema changes are required: audit checkpoints are stored in the existing
    hotel_auto_page_event table.
    """

    def _require_staging(self) -> None:
        env = (os.getenv("APP_ENV") or os.getenv("GO_ENV") or "").strip().lower()
        if env != "staging":
            raise ValueError("RC13_ACCEPTANCE_STAGING_ONLY")

    def _event(self, event_type: str, evidence: dict, actor: str = "RC13_ACCEPTANCE") -> None:
        with SessionLocal() as s:
            s.add(
                HotelAutoPageEventRow(
                    hotel_auto_page_event_id=_id("hape"),
                    hotel_id=None,
                    event_type=event_type,
                    evidence_json=evidence,
                    actor=actor,
                    created_at=_now(),
                )
            )
            s.commit()

    def latest_passed_level(self) -> int:
        with SessionLocal() as s:
            rows = s.scalars(
                select(HotelAutoPageEventRow)
                .where(HotelAutoPageEventRow.event_type == SUMMARY_EVENT)
                .order_by(HotelAutoPageEventRow.created_at.desc())
            ).all()
            for row in rows:
                ev = row.evidence_json or {}
                if ev.get("result") == "PASS":
                    try:
                        return int(ev.get("level") or 0)
                    except Exception:
                        continue
        return 0

    def _assert_level_unlocked(self, level: int) -> None:
        if level not in LEVELS:
            raise ValueError("RC13_ACCEPTANCE_LEVEL_INVALID")
        if level == 1:
            return
        previous = LEVELS[LEVELS.index(level) - 1]
        if self.latest_passed_level() < previous:
            raise ValueError(f"RC13_ACCEPTANCE_LEVEL_LOCKED_PREVIOUS_{previous}_REQUIRED")

    def _orphan_rows(self, s) -> int:
        profiles = set(s.scalars(select(HotelCanonicalProfileRow.hotel_id)).all())
        snapshots = s.scalars(select(HotelContentSourceSnapshotRow.canonical_hotel_id)).all()
        versions = s.scalars(select(HotelAutoPageVersionRow.hotel_id)).all()
        contacts = s.scalars(select(HotelContactPointRow.hotel_id)).all()
        regs = s.scalars(select(HotelRegistrationDirectRow.hotel_id)).all()
        return sum(1 for x in snapshots if x and x not in profiles) + sum(1 for x in versions if x not in profiles) + sum(1 for x in contacts if x not in profiles) + sum(1 for x in regs if x not in profiles)

    def stats(self) -> dict:
        with SessionLocal() as s:
            return {
                "seed_count": int(s.scalar(select(func.count()).select_from(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type == "DISCOVERY_SEED_REGISTERED")) or 0),
                "unique_hotel_entity_count": int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow)) or 0),
                "snapshot_count": int(s.scalar(select(func.count()).select_from(HotelContentSourceSnapshotRow)) or 0),
                "generated_page_count": int(s.scalar(select(func.count()).select_from(HotelAutoPageVersionRow)) or 0),
                "published_page_count": int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.page_state == "PUBLISHED")) or 0),
                "retry_count": int(s.scalar(select(func.count()).select_from(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type == "DISCOVERY_JOB_RETRY_REQUESTED")) or 0),
                "failed_count": int(s.scalar(select(func.count()).select_from(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type == "DISCOVERY_SOURCE_FAILED")) or 0),
                "claimed_count": int(s.scalar(select(func.count()).select_from(HotelRegistrationDirectRow)) or 0),
                "go_direct_count": int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.go_direct_state.in_(["GO_DIRECT_VERIFIED", "GO_DIRECT_LIVE"]))) or 0),
                "orphan_rows": self._orphan_rows(s),
            }


    def _expected_external_ids(self, batch_id: str, level: int) -> list[str]:
        return [f"{batch_id}:{i:04d}" for i in range(1, level + 1)]

    def _batch_identity_audit(self, batch_id: str, level: int, before: dict) -> dict:
        expected = set(self._expected_external_ids(batch_id, level))
        with SessionLocal() as s:
            rows = s.execute(
                select(
                    HotelContentSourceSnapshotRow.external_hotel_id,
                    HotelContentSourceSnapshotRow.canonical_hotel_id,
                ).where(
                    HotelContentSourceSnapshotRow.source_key == "rc13_acceptance",
                    HotelContentSourceSnapshotRow.external_hotel_id.in_(expected),
                )
            ).all()
            mapping: dict[str, set[str]] = {}
            for external_id, canonical_id in rows:
                mapping.setdefault(str(external_id), set()).add(str(canonical_id))
            missing = sorted(expected - set(mapping))
            multi = {k: sorted(v) for k, v in mapping.items() if len(v) != 1}
            canonical_ids = {next(iter(v)) for v in mapping.values() if len(v) == 1}
            global_delta = int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow)) or 0) - int(before["unique_hotel_entity_count"])
        return {
            "expected_external_id_count": len(expected),
            "resolved_external_id_count": len(mapping),
            "canonical_id_count": len(canonical_ids),
            "missing_external_ids": missing,
            "multi_mapped_external_ids": multi,
            "global_entity_delta": global_delta,
            "ok": not missing and not multi and len(canonical_ids) == level and global_delta == level,
        }

    def _exercise_failure_retry_recovery(self, batch_id: str, actor: str) -> dict:
        seed = self._synthetic_seed(f"{batch_id}-retry", 1)
        seed["name"] = f"RC13 Retry Recovery {batch_id}"
        seed["external_ids"] = {"rc13_acceptance": f"{batch_id}-retry:0001"}
        seed["source_hints"][0]["external_hotel_id"] = f"{batch_id}-retry:0001"
        reg = hotel_discovery_orchestrator_service.register_seed(seed, actor)
        original = hotel_discovery_orchestrator_service._ingest_hint
        calls = {"n": 0}

        def fail_once(seed_arg, hint_arg, actor_arg):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("DISCOVERY_TRANSIENT_HTTP_503")
            return original(seed_arg, hint_arg, actor_arg)

        try:
            hotel_discovery_orchestrator_service._ingest_hint = fail_once
            first = hotel_discovery_orchestrator_service.run_job(reg["job_id"], actor, max_retries=0)
            second = hotel_discovery_orchestrator_service.retry_job(reg["job_id"], actor, max_retries=0)
        finally:
            hotel_discovery_orchestrator_service._ingest_hint = original

        return {
            "job_id": reg["job_id"],
            "hotel_id": second.get("hotel_id"),
            "first_state": first.get("state"),
            "retry_state": second.get("state"),
            "ok": first.get("state") == "FAILED" and second.get("state") == "COMPLETED" and bool(second.get("hotel_id")),
        }

    def _synthetic_seed(self, batch_id: str, idx: int) -> dict:
        external_id = f"{batch_id}:{idx:04d}"
        name = f"RC13 验收酒店 {idx:04d}"
        payload = {
            "name": name,
            "address": {"formatted": f"RC13 Acceptance Road {idx}, Staging"},
            "website": f"https://example.com/rc13/{idx}",
            "facilities": ["Wi-Fi", "Breakfast"],
            "policies": [{"type": "CHECK_IN", "value": "14:00"}, {"type": "CHECK_OUT", "value": "12:00"}],
            # Candidate URL is deliberately unharvested and RIGHTS_UNKNOWN. Public
            # page media must remain empty until Media Harvester + Rights Gate pass.
            "media_candidates": [{"source_url": f"https://example.com/rc13/{idx}.jpg", "role": "GALLERY", "rights_state": "RIGHTS_UNKNOWN"}],
            "contacts": [{"contact_type": "GENERAL", "channel": "EMAIL", "value": f"rc13-{idx}@example.com", "is_public_business_contact": True}],
        }
        return {
            "name": name,
            "address": payload["address"]["formatted"],
            "city": "Staging",
            "country": "TEST",
            "external_ids": {"rc13_acceptance": external_id},
            "source_hints": [{
                "kind": "DATA_PROVIDER",
                "source_key": "rc13_acceptance",
                "external_hotel_id": external_id,
                "rights_status": "AUTHORIZED",
                "confidence_bps": 9000,
                "payload": payload,
            }],
        }

    def _business_counts_for_hotels(self, hotel_ids: list[str]) -> dict:
        if not hotel_ids:
            return {"entities": 0, "snapshots": 0, "pages": 0, "registrations": 0}
        with SessionLocal() as s:
            return {
                "entities": int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.hotel_id.in_(hotel_ids))) or 0),
                "snapshots": int(s.scalar(select(func.count()).select_from(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.canonical_hotel_id.in_(hotel_ids))) or 0),
                "pages": int(s.scalar(select(func.count()).select_from(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id.in_(hotel_ids))) or 0),
                "registrations": int(s.scalar(select(func.count()).select_from(HotelRegistrationDirectRow).where(HotelRegistrationDirectRow.hotel_id.in_(hotel_ids))) or 0),
            }

    def _cleanup(self, hotel_ids: list[str], job_ids: list[str]) -> None:
        with SessionLocal() as s:
            if hotel_ids:
                s.execute(delete(HotelRegistrationDirectRow).where(HotelRegistrationDirectRow.hotel_id.in_(hotel_ids)))
                s.execute(delete(HotelContactPointRow).where(HotelContactPointRow.hotel_id.in_(hotel_ids)))
                s.execute(delete(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id.in_(hotel_ids)))
                s.execute(delete(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.canonical_hotel_id.in_(hotel_ids)))
                s.execute(delete(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.hotel_id.in_(hotel_ids)))
            rows = s.scalars(select(HotelAutoPageEventRow)).all()
            for row in rows:
                if row.event_type in {SUMMARY_EVENT, START_EVENT}:
                    continue
                ev = row.evidence_json or {}
                if row.hotel_id in set(hotel_ids) or ev.get("job_id") in set(job_ids):
                    s.delete(row)
            s.commit()

    def run_level(self, level: int, actor: str = "RC13_ACCEPTANCE", *, cleanup: bool = True) -> dict:
        self._require_staging()
        self._assert_level_unlocked(level)
        batch_id = f"rc13-l{level}-{uuid.uuid4().hex[:12]}"
        before = self.stats()
        self._event(START_EVENT, {"batch_id": batch_id, "level": level, "before": before}, actor)

        hotel_ids: list[str] = []
        job_ids: list[str] = []
        first_failures: list[dict] = []
        seeds = [self._synthetic_seed(batch_id, i + 1) for i in range(level)]

        for seed in seeds:
            reg = hotel_discovery_orchestrator_service.register_seed(seed, actor)
            job_ids.append(reg["job_id"])
            run = hotel_discovery_orchestrator_service.run_job(reg["job_id"], actor, max_retries=0)
            if run.get("state") != "COMPLETED" or not run.get("hotel_id"):
                first_failures.append({"job_id": reg["job_id"], "state": run.get("state"), "failures": run.get("failures")})
                continue
            hotel_ids.append(run["hotel_id"])

        hotel_ids = list(dict.fromkeys(hotel_ids))
        first_counts = self._business_counts_for_hotels(hotel_ids)

        # Idempotency replay: same seed and same source payload must not grow
        # canonical entities, immutable snapshots or page versions.
        for seed in seeds:
            reg = hotel_discovery_orchestrator_service.register_seed(seed, actor)
            job_ids.append(reg["job_id"])
            hotel_discovery_orchestrator_service.run_job(reg["job_id"], actor, max_retries=0)
        replay_counts = self._business_counts_for_hotels(hotel_ids)
        idempotent = first_counts == replay_counts

        # Entity Resolution is verified against the entire synthetic identity set and
        # the global canonical-entity delta, not only returned hotel_ids.
        identity_audit = self._batch_identity_audit(batch_id, level, before)
        unique_entities_ok = len(hotel_ids) == level and first_counts["entities"] == level and identity_audit["ok"]

        # Exercise an actual failed job -> retry requested -> successful recovery path.
        retry_recovery = self._exercise_failure_retry_recovery(batch_id, actor)
        job_ids.append(retry_recovery["job_id"])
        if retry_recovery.get("hotel_id"):
            hotel_ids.append(retry_recovery["hotel_id"])

        rights_fail_closed = True
        blocked_media_count = 0
        rights_checked_count = 0
        page_rebuild_ok = True
        claim_takeover_ok = True
        go_direct_ok = True
        primary_hotel_ids = list(dict.fromkeys(hotel_ids[:level]))
        for hid in primary_hotel_ids:
            detail = hotel_autopage_factory_service.factory_detail(hid)
            slug = (detail.get("profile") or {}).get("slug")
            if not slug:
                rights_fail_closed = False
                continue
            hotel_autopage_factory_service.set_publication(hid, "PUBLISH", actor)
            public = hotel_autopage_factory_service.public_page(slug)
            media = public.get("media") or {}
            rights_checked_count += 1
            blocked = not (media.get("hero") or media.get("gallery") or media.get("assets"))
            blocked_media_count += int(blocked)
            rights_fail_closed = rights_fail_closed and blocked

        if primary_hotel_ids:
            target = primary_hotel_ids[0]
            before_compose = self._business_counts_for_hotels([target])["pages"]
            hotel_autopage_factory_service.compose(target, actor)
            hotel_autopage_factory_service.compose(target, actor)
            after_compose = self._business_counts_for_hotels([target])["pages"]
            page_rebuild_ok = after_compose == before_compose

            profile_count_before = self._business_counts_for_hotels(hotel_ids)["entities"]
            reg = hotel_autopage_factory_service.register_for_go_direct(target, f"rc13-supplier-{batch_id}", actor, {"evidence": [{"kind": "STAGING_ACCEPTANCE"}]})
            decision = hotel_autopage_factory_service.decide_registration_direct(reg["hotel_registration_direct_id"], actor, {"decision": "APPROVE"})
            profile_count_after = self._business_counts_for_hotels(hotel_ids)["entities"]
            claim_takeover_ok = profile_count_before == profile_count_after and (decision.get("profile") or {}).get("hotel_id") == target
            go_direct_ok = (decision.get("profile") or {}).get("go_direct_state") in {"GO_DIRECT_VERIFIED", "GO_DIRECT_LIVE"}

        duplicate_count = max(0, level - len(primary_hotel_ids))
        after_run = self.stats()
        orphan_ok = after_run["orphan_rows"] == before["orphan_rows"]

        checks = {
            "batch_completed": not first_failures,
            "idempotent_replay": idempotent,
            "no_duplicate_entities": unique_entities_ok and duplicate_count == 0,
            "external_identity_exactly_one_canonical": identity_audit["ok"],
            "source_snapshot_present": first_counts["snapshots"] == level,
            "page_generated": first_counts["pages"] >= level,
            "failure_retry_recovery": retry_recovery["ok"],
            "rights_fail_closed": rights_fail_closed and rights_checked_count == level and blocked_media_count == level,
            "page_rebuild_idempotent": page_rebuild_ok,
            "claim_takeover_same_entity": claim_takeover_ok,
            "go_direct_upgrade_preserved": go_direct_ok,
            "no_new_orphans": orphan_ok,
        }
        result = "PASS" if all(checks.values()) else "FAIL"

        cleanup_result = None
        if cleanup:
            self._cleanup(hotel_ids, job_ids)
            after_cleanup = self.stats()
            cleanup_result = {
                "after_cleanup": after_cleanup,
                "baseline_restored": all(after_cleanup[k] == before[k] for k in [
                    "seed_count", "unique_hotel_entity_count", "snapshot_count", "generated_page_count",
                    "published_page_count", "retry_count", "failed_count", "claimed_count",
                    "go_direct_count", "orphan_rows",
                ]),
            }
            checks["cleanup_baseline_restored"] = cleanup_result["baseline_restored"]
            result = "PASS" if all(checks.values()) else "FAIL"

        report = {
            "batch_id": batch_id,
            "level": level,
            "result": result,
            "checks": checks,
            "before": before,
            "after_run": after_run,
            "batch_business_counts": first_counts,
            "replay_business_counts": replay_counts,
            "duplicate_count": duplicate_count,
            "identity_audit": identity_audit,
            "rights_checked_count": rights_checked_count,
            "blocked_media_count": blocked_media_count,
            "retry_recovery": retry_recovery,
            "retry_count": max(0, after_run["retry_count"] - before["retry_count"]),
            "failed_count": max(0, after_run["failed_count"] - before["failed_count"]),
            "claimed_count": 1 if hotel_ids else 0,
            "go_direct_count": 1 if go_direct_ok and hotel_ids else 0,
            "orphan_rows": after_run["orphan_rows"],
            "cleanup": cleanup_result,
            "failures": first_failures,
        }
        self._event(SUMMARY_EVENT, report, actor)
        if result != "PASS":
            raise ValueError("RC13_BATCH_ACCEPTANCE_FAILED")
        return report


hotel_page_production_acceptance_service = HotelPageProductionAcceptanceService()
