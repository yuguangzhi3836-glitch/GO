from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import func, select

from go_hotel.db.models import (
    ConnectorAuthorityRow,
    ConnectorCapabilityMatrixRow,
    ConnectorCertificationRunRow,
    HostedDirectHotelRow,
    HostedDirectInventoryPoolRow,
    HostedDirectRateVariantRow,
    HostedDirectRoomOfferRow,
    ProductionConnectorRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service

AOLUGUYA_SUPPLIER = "哈尔滨敖麓谷雅酒店"
AOLUGUYA_SLUG = "aoluguya-harbin"
AOLUGUYA_CONNECTOR_KEY = "hotel_official_aoluguya_harbin"
AOLUGUYA_PROVIDER_CODE = "AOLUGUYA_OFFICIAL"
AOLUGUYA_MAX_STALENESS_SECONDS = 1800
OFFICIAL_SOURCE_TYPES = {
    "HOTEL_OFFICIAL_SUPPLIER_CONSOLE",
    "HOTEL_OFFICIAL_SIGNED_FEED",
    "HOTEL_OFFICIAL_API",
}
FALLBACK_TIER_1 = ("CTRIP", "MEITUAN")
FALLBACK_NAMES = {
    "CTRIP": "携程 / Trip.com",
    "MEITUAN": "美团",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def ident(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("SOURCE_UPDATED_AT_REQUIRED")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception as exc:
            raise ValueError("VALID_SOURCE_UPDATED_AT_REQUIRED") from exc
    if dt.tzinfo is None:
        raise ValueError("SOURCE_UPDATED_AT_MUST_HAVE_TIMEZONE")
    return dt.astimezone(timezone.utc)


def _latest_matrix(s, connector_id: str):
    return s.scalar(
        select(ConnectorCapabilityMatrixRow)
        .where(ConnectorCapabilityMatrixRow.connector_id == connector_id)
        .order_by(ConnectorCapabilityMatrixRow.version_no.desc())
    )


def _new_matrix(s, connector: ProductionConnectorRow, caps: dict[str, Any]):
    latest = _latest_matrix(s, connector.connector_id)
    version = (latest.version_no if latest else 0) + 1
    row = ConnectorCapabilityMatrixRow(
        capability_matrix_id=ident("ccm"),
        connector_id=connector.connector_id,
        version_no=version,
        capabilities_json=caps,
        content_hash=digest(caps),
        created_at=now(),
    )
    s.add(row)
    connector.active_capability_version = version
    connector.updated_at = now()
    return row


def _contains_test_truth(value: Any) -> bool:
    markers = (
        "STAGING_TEST_NOT_OFFICIAL",
        "STAGING_TEST_QUOTE_NOT_OFFICIAL",
        "STAGING_TEST_INVENTORY",
        "Staging测试",
        "MOCK",
        "SIMULATED",
    )
    if isinstance(value, dict):
        return any(_contains_test_truth(k) or _contains_test_truth(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_test_truth(v) for v in value)
    if value is None:
        return False
    text = str(value)
    return any(m in text for m in markers)


def _stable_rate_key(room_key, offer_id):
    return f"{room_key}:offer:{offer_id}"


def _resolve_rate_variants(rooms, variants, existing_map):
    """Resolve every rate before writes; breakfast is never a plan identity.

    Legacy breakfast-only matching is retained only for one unbound source rate
    and one unbound hosted variant. Ambiguous mappings require explicit keys.
    """
    exact = {}
    legacy = {}
    for variant, pool, offer in variants:
        saved = existing_map.get(offer.hosted_offer_id) or {}
        if saved and saved.get("room_key") != pool.physical_room_key:
            raise ValueError("HOSTED_RATE_ROOM_IDENTITY_MISMATCH")
        key = saved.get("rate_plan_key") or _stable_rate_key(pool.physical_room_key, offer.hosted_offer_id)
        identity = (pool.physical_room_key, key)
        if identity in exact:
            raise ValueError("DUPLICATE_HOSTED_RATE_PLAN_KEY")
        exact[identity] = (variant, pool, offer)
        if not saved:
            legacy.setdefault((pool.physical_room_key, variant.breakfast_count), []).append((variant, pool, offer))
    result = {}
    used = set()
    pending = {}
    for room in rooms:
        for rate in room["rates"]:
            identity = (room["room_key"], rate["rate_plan_key"])
            if identity in result:
                raise ValueError("DUPLICATE_SOURCE_RATE_PLAN_KEY")
            matched = exact.get(identity)
            if matched:
                if matched[0].breakfast_count != rate["breakfast_count"]:
                    raise ValueError("HOSTED_RATE_BREAKFAST_MISMATCH")
                if matched[2].hosted_offer_id in used:
                    raise ValueError("DUPLICATE_HOSTED_RATE_MAPPING")
                result[identity] = matched
                used.add(matched[2].hosted_offer_id)
            else:
                pending.setdefault((room["room_key"], rate["breakfast_count"]), []).append(identity)
    for breakfast_key, identities in pending.items():
        candidates = [item for item in legacy.get(breakfast_key, []) if item[2].hosted_offer_id not in used]
        if len(identities) != 1 or len(candidates) != 1:
            raise ValueError("UNMAPPED_OR_AMBIGUOUS_HOSTED_RATE_VARIANT:" + ":".join(map(str, breakfast_key)))
        result[identities[0]] = candidates[0]
        used.add(candidates[0][2].hosted_offer_id)
    return result


class AoluguyaSupplyTruthService:
    def ensure_named_connector(self, actor: str) -> dict[str, Any]:
        with SessionLocal() as s:
            connector = s.scalar(select(ProductionConnectorRow).where(ProductionConnectorRow.connector_key == AOLUGUYA_CONNECTOR_KEY))
            if connector:
                if connector.supplier_legal_name != AOLUGUYA_SUPPLIER or connector.vertical != "HOTEL":
                    raise ValueError("AOLUGUYA_CONNECTOR_IDENTITY_MISMATCH")
            else:
                connector = ProductionConnectorRow(
                    connector_id=ident("conn"),
                    connector_key=AOLUGUYA_CONNECTOR_KEY,
                    display_name="AOLUGUYA Official Supply Truth",
                    vertical="HOTEL",
                    supplier_legal_name=AOLUGUYA_SUPPLIER,
                    environment="SANDBOX",
                    lifecycle_state="NAMED_HOTEL_PILOT",
                    active_capability_version=1,
                    created_by=actor,
                    created_at=now(),
                    updated_at=now(),
                )
                s.add(connector)
                s.flush()
                caps = {
                    "provider_code": AOLUGUYA_PROVIDER_CODE,
                    "official_direct": True,
                    "source_modes": sorted(OFFICIAL_SOURCE_TYPES),
                    "payment_scope": "OUT_OF_SCOPE",
                    "external_transport_verified": False,
                    "production_live": False,
                    "aoluguya_supply_truth_snapshot": None,
                }
                _new_matrix(s, connector, caps)
            s.commit()
            return {
                "connector_id": connector.connector_id,
                "connector_key": connector.connector_key,
                "supplier": connector.supplier_legal_name,
                "state": "NAMED_HOTEL_PILOT_READY_FOR_OFFICIAL_TRUTH",
                "external_transport_verified": False,
                "payment_connected": False,
                "production_live": False,
            }

    def ingest_official_truth(self, body: dict[str, Any], actor: str) -> dict[str, Any]:
        connector_info = self.ensure_named_connector(actor)
        source_type = str(body.get("source_type") or "").strip()
        if source_type not in OFFICIAL_SOURCE_TYPES:
            raise ValueError("HOTEL_OFFICIAL_SOURCE_TYPE_REQUIRED")
        evidence_reference = str(body.get("evidence_reference") or "").strip()
        if not evidence_reference:
            raise ValueError("HOTEL_OFFICIAL_EVIDENCE_REQUIRED")
        source_updated_at = parse_time(body.get("source_updated_at"))
        age = (now() - source_updated_at).total_seconds()
        if age < -300:
            raise ValueError("SOURCE_UPDATED_AT_IN_FUTURE")
        if age > AOLUGUYA_MAX_STALENESS_SECONDS:
            raise ValueError("STALE_SUPPLY_TRUTH_REJECTED")
        if str(body.get("supplier_legal_name") or "") != AOLUGUYA_SUPPLIER:
            raise ValueError("AOLUGUYA_SUPPLIER_IDENTITY_REQUIRED")
        if str(body.get("property_key") or "") != AOLUGUYA_SLUG:
            raise ValueError("AOLUGUYA_PROPERTY_KEY_REQUIRED")

        rooms = body.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            raise ValueError("ROOM_TRUTH_REQUIRED")
        room_keys: set[str] = set()
        rate_keys: set[str] = set()
        normalized_rooms: list[dict[str, Any]] = []
        for room in rooms:
            room_key = str(room.get("room_key") or "").strip()
            room_name = str(room.get("room_name") or "").strip()
            inventory = room.get("inventory")
            if not room_key or not room_name or room_key in room_keys:
                raise ValueError("UNIQUE_ROOM_KEY_AND_NAME_REQUIRED")
            room_keys.add(room_key)
            if not isinstance(inventory, int) or inventory < 0:
                raise ValueError("VALID_ROOM_INVENTORY_REQUIRED")
            rates = room.get("rates")
            if not isinstance(rates, list) or not rates:
                raise ValueError("RATE_PLAN_TRUTH_REQUIRED")
            normalized_rates = []
            for rate in rates:
                rate_key = str(rate.get("rate_plan_key") or "").strip()
                rate_name = str(rate.get("rate_name") or "").strip()
                price_minor = rate.get("price_minor")
                currency = str(rate.get("currency") or "").upper()
                breakfast_count = rate.get("breakfast_count")
                cancellation_policy = str(rate.get("cancellation_policy") or "").strip()
                taxes_fees = rate.get("taxes_fees")
                sell_state = str(rate.get("sell_state") or "").upper()
                if not rate_key or rate_key in rate_keys or not rate_name:
                    raise ValueError("UNIQUE_RATE_PLAN_KEY_AND_NAME_REQUIRED")
                rate_keys.add(rate_key)
                if not isinstance(price_minor, int) or price_minor <= 0:
                    raise ValueError("VALID_OFFICIAL_PRICE_REQUIRED")
                if currency != "CNY":
                    raise ValueError("AOLUGUYA_CNY_REQUIRED")
                if not isinstance(breakfast_count, int) or breakfast_count < 0:
                    raise ValueError("UNIQUE_BREAKFAST_VARIANT_REQUIRED")
                if not cancellation_policy:
                    raise ValueError("CANCELLATION_POLICY_REQUIRED")
                if not isinstance(taxes_fees, dict) or "included_in_total" not in taxes_fees:
                    raise ValueError("TAXES_FEES_TRUTH_REQUIRED")
                if sell_state not in {"OPEN", "CLOSED", "STOP_SELL"}:
                    raise ValueError("VALID_SELL_STATE_REQUIRED")
                normalized_rates.append({
                    "rate_plan_key": rate_key,
                    "rate_name": rate_name,
                    "price_minor": price_minor,
                    "currency": currency,
                    "breakfast_count": breakfast_count,
                    "breakfast": rate.get("breakfast") or {"count": breakfast_count},
                    "cancellation_policy": cancellation_policy,
                    "taxes_fees": taxes_fees,
                    "sell_state": sell_state,
                })
            normalized_rooms.append({
                "room_key": room_key,
                "room_name": room_name,
                "inventory": inventory,
                "rates": normalized_rates,
            })

        snapshot = {
            "schema": "go.aoluguya-supply-truth.v1",
            "supplier_legal_name": AOLUGUYA_SUPPLIER,
            "property_key": AOLUGUYA_SLUG,
            "source_type": source_type,
            "source_updated_at": source_updated_at.isoformat(),
            "evidence_reference": evidence_reference,
            "rooms": normalized_rooms,
            "payment_scope": "OUT_OF_SCOPE",
            "official_truth": True,
            "external_transport_verified": source_type == "HOTEL_OFFICIAL_API" and bool(body.get("external_transport_verified")),
            "ingested_by": actor,
            "ingested_at": now().isoformat(),
        }
        if snapshot["external_transport_verified"] and not body.get("external_transport_evidence_reference"):
            raise ValueError("EXTERNAL_TRANSPORT_EVIDENCE_REQUIRED")
        if _contains_test_truth(snapshot):
            raise ValueError("TEST_OR_SIMULATED_TRUTH_FORBIDDEN")
        snapshot["content_hash"] = digest(snapshot)

        with SessionLocal() as s:
            connector = s.get(ProductionConnectorRow, connector_info["connector_id"])
            latest = _latest_matrix(s, connector.connector_id)
            caps = dict(latest.capabilities_json or {})
            caps["aoluguya_supply_truth_snapshot"] = snapshot
            caps["aoluguya_supply_truth_state"] = "HOTEL_OFFICIAL_TRUTH_RECEIVED"
            caps["payment_scope"] = "OUT_OF_SCOPE"
            row = _new_matrix(s, connector, caps)
            s.commit()
            return {
                "connector_id": connector.connector_id,
                "state": "HOTEL_OFFICIAL_TRUTH_RECEIVED",
                "snapshot_hash": snapshot["content_hash"],
                "source_type": source_type,
                "source_updated_at": snapshot["source_updated_at"],
                "capability_version": row.version_no,
                "payment_connected": False,
            }

    def _load_snapshot(self, s):
        connector = s.scalar(select(ProductionConnectorRow).where(ProductionConnectorRow.connector_key == AOLUGUYA_CONNECTOR_KEY))
        if not connector:
            raise ValueError("AOLUGUYA_NAMED_CONNECTOR_REQUIRED")
        latest = _latest_matrix(s, connector.connector_id)
        snapshot = (latest.capabilities_json or {}).get("aoluguya_supply_truth_snapshot") if latest else None
        if not snapshot:
            raise ValueError("AOLUGUYA_OFFICIAL_SUPPLY_TRUTH_REQUIRED")
        return connector, latest, snapshot

    def evaluate(self) -> dict[str, Any]:
        with SessionLocal() as s:
            connector, _, snapshot = self._load_snapshot(s)
            hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            source_dt = parse_time(snapshot.get("source_updated_at"))
            age = max(0, int((now() - source_dt).total_seconds()))
            rooms = snapshot.get("rooms") or []
            rates = [rate for room in rooms for rate in room.get("rates", [])]
            checks = {
                "PROPERTY_TRUTH": snapshot.get("supplier_legal_name") == AOLUGUYA_SUPPLIER and snapshot.get("property_key") == AOLUGUYA_SLUG,
                "ROOM_TRUTH": bool(rooms) and len({x.get("room_key") for x in rooms}) == len(rooms),
                "RATE_PLAN": bool(rates) and len({x.get("rate_plan_key") for x in rates}) == len(rates),
                "AVAILABILITY": all(isinstance(x.get("inventory"), int) and x.get("inventory") >= 0 for x in rooms),
                "PRICE_CURRENCY": all(isinstance(x.get("price_minor"), int) and x.get("price_minor") > 0 and x.get("currency") == "CNY" for x in rates),
                "BREAKFAST": all(isinstance(x.get("breakfast_count"), int) and isinstance(x.get("breakfast"), dict) for x in rates),
                "CANCELLATION": all(bool(x.get("cancellation_policy")) for x in rates),
                "TAX": all(isinstance(x.get("taxes_fees"), dict) and "included_in_total" in x.get("taxes_fees", {}) for x in rates),
                "SOURCE_PROVENANCE": snapshot.get("source_type") in OFFICIAL_SOURCE_TYPES and bool(snapshot.get("evidence_reference")),
                "STALE_DATA_GUARD": age <= AOLUGUYA_MAX_STALENESS_SECONDS,
                "NO_TEST_TRUTH": not _contains_test_truth(snapshot),
                "GO_PAGE_PROJECTION_READY": bool(hotel and hotel.supplier_name == AOLUGUYA_SUPPLIER),
            }
            return {
                "connector_id": connector.connector_id,
                "state": "PASS" if all(checks.values()) else "BLOCKED",
                "checks": checks,
                "source_age_seconds": age,
                "blockers": [k for k, v in checks.items() if not v],
                "payment_connected": False,
                "production_live": False,
            }


    def official_snapshot_template(self) -> dict[str, Any]:
        """Return a directly fillable 5-room/9-rate official truth template.

        Values intentionally stay blank/default until an authorized hotel source submits them.
        """
        with SessionLocal() as db:
            hotel = db.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            if not hotel:
                raise ValueError("AOLUGUYA_HOSTED_DIRECT_HOTEL_REQUIRED")
            rows = db.execute(
                select(HostedDirectRateVariantRow, HostedDirectInventoryPoolRow)
                .join(HostedDirectInventoryPoolRow, HostedDirectInventoryPoolRow.inventory_pool_id == HostedDirectRateVariantRow.inventory_pool_id)
                .where(HostedDirectInventoryPoolRow.hosted_hotel_id == hotel.hosted_hotel_id)
                .order_by(HostedDirectInventoryPoolRow.physical_room_key, HostedDirectRateVariantRow.breakfast_count)
            ).all()
            grouped: dict[str, dict[str, Any]] = {}
            existing_map = (hotel.contact_json or {}).get("official_rate_map") or {}
            for variant, pool in rows:
                room = grouped.setdefault(pool.physical_room_key, {
                    "room_key": pool.physical_room_key, "room_name": pool.physical_room_name,
                    "inventory": None, "rates": []
                })
                room["rates"].append({
                    "rate_plan_key": (existing_map.get(variant.hosted_offer_id) or {}).get("rate_plan_key")
                        or (_stable_rate_key(pool.physical_room_key, variant.hosted_offer_id)
                            if sum(p.physical_room_key == pool.physical_room_key and v.breakfast_count == variant.breakfast_count for v, p in rows) > 1
                            else f"{pool.physical_room_key}:bf{variant.breakfast_count}"),
                    "rate_name": "", "price_minor": None, "currency": "CNY",
                    "breakfast_count": variant.breakfast_count, "breakfast": {"count": variant.breakfast_count},
                    "cancellation_policy": "", "taxes_fees": {"included_in_total": None},
                    "sell_state": "OPEN"
                })
            rooms = list(grouped.values())
            if len(rooms) != 5 or sum(len(x["rates"]) for x in rooms) != 9:
                raise ValueError("AOLUGUYA_5_ROOM_9_RATE_BASELINE_REQUIRED")
            return {
                "schema": "go.aoluguya-official-supply-intake.v1",
                "supplier_legal_name": AOLUGUYA_SUPPLIER,
                "property_key": AOLUGUYA_SLUG,
                "source_type": "HOTEL_OFFICIAL_SUPPLIER_CONSOLE",
                "source_updated_at": "", "evidence_reference": "",
                "source_actor": "", "source_signature_reference": "",
                "rooms": rooms,
                "required_room_count": 5, "required_rate_variant_count": 9,
                "payment_scope": "OUT_OF_SCOPE",
                "instructions": [
                    "Inventory/price/policy/tax must be current hotel-official facts.",
                    "source_updated_at must include timezone and be within stale guard.",
                    "Do not paste OTA historical reference price as hotel official price.",
                ],
            }

    def _cutover_backup(self, db, hotel, pools, all_offers) -> dict[str, Any]:
        return {
            "schema": "go.aoluguya-cutover-backup.v2",
            "hotel_state": hotel.state, "contact_json": dict(hotel.contact_json or {}),
            "pools": {p.inventory_pool_id: {
                "physical_room_name": p.physical_room_name, "capacity_total": p.capacity_total,
                "capacity_available": p.capacity_available
            } for p in pools.values()},
            "offers": {o.hosted_offer_id: {
                "room_name": o.room_name, "rate_name": o.rate_name, "price_minor": o.price_minor,
                "currency": o.currency, "inventory": o.inventory,
                "cancellation_policy": o.cancellation_policy, "state": o.state
            } for o in all_offers},
            "variants": {v.rate_variant_id: {"state": v.state}
                for v in db.scalars(select(HostedDirectRateVariantRow)
                    .join(HostedDirectInventoryPoolRow, HostedDirectInventoryPoolRow.inventory_pool_id == HostedDirectRateVariantRow.inventory_pool_id)
                    .where(HostedDirectInventoryPoolRow.hosted_hotel_id == hotel.hosted_hotel_id)).all()},
            "captured_at": now().isoformat(),
        }

    def rollback_cutover(self, actor: str) -> dict[str, Any]:
        with SessionLocal() as db:
            connector, latest, _ = self._load_snapshot(db)
            backup = (latest.capabilities_json or {}).get("aoluguya_cutover_backup")
            if not backup:
                raise ValueError("AOLUGUYA_CUTOVER_BACKUP_REQUIRED")
            hotel = db.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            if not hotel:
                raise ValueError("AOLUGUYA_HOSTED_DIRECT_HOTEL_REQUIRED")
            pools = db.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id == hotel.hosted_hotel_id)).all()
            offers = db.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == hotel.hosted_hotel_id)).all()
            variants = db.scalars(select(HostedDirectRateVariantRow)
                .join(HostedDirectInventoryPoolRow, HostedDirectInventoryPoolRow.inventory_pool_id == HostedDirectRateVariantRow.inventory_pool_id)
                .where(HostedDirectInventoryPoolRow.hosted_hotel_id == hotel.hosted_hotel_id)).all()
            variant_backup = backup.get("variants")
            if variant_backup is not None and set(variant_backup) != {v.rate_variant_id for v in variants}:
                raise ValueError("AOLUGUYA_ROLLBACK_VARIANT_IDENTITY_MISMATCH")
            for p in pools:
                old = backup["pools"].get(p.inventory_pool_id)
                if old:
                    p.physical_room_name = old["physical_room_name"]; p.capacity_total = old["capacity_total"]; p.capacity_available = old["capacity_available"]; p.updated_at = now()
            for o in offers:
                old = backup["offers"].get(o.hosted_offer_id)
                if old:
                    for k in ("room_name","rate_name","price_minor","currency","inventory","cancellation_policy","state"):
                        setattr(o, k, old[k])
                    o.updated_at = now()
            if variant_backup is not None:
                for variant in variants:
                    variant.state = variant_backup[variant.rate_variant_id]["state"]
            hotel.state = backup["hotel_state"]; hotel.contact_json = backup["contact_json"]; hotel.updated_at = now()
            caps = dict(latest.capabilities_json or {})
            limitations = [] if variant_backup is not None else ["LEGACY_BACKUP_VARIANT_STATE_UNAVAILABLE"]
            caps["aoluguya_cutover_rollback"] = {"rolled_back_at": now().isoformat(), "rolled_back_by": actor,
                "variant_states_restored": variant_backup is not None, "limitations": limitations}
            _new_matrix(db, connector, caps)
            db.commit()
            return {"state": "AOLUGUYA_CUTOVER_ROLLED_BACK" if not limitations else "AOLUGUYA_CUTOVER_PARTIALLY_ROLLED_BACK",
                "variant_states_restored": variant_backup is not None, "limitations": limitations,
                "payment_available": False, "booking_mode": "RESERVATION_REQUEST_ONLY"}

    def project_to_hosted_direct(self, actor: str) -> dict[str, Any]:
        assessment = self.evaluate()
        if assessment["state"] != "PASS":
            raise ValueError("AOLUGUYA_SUPPLY_TRUTH_GATE_BLOCKED:" + ",".join(assessment["blockers"]))
        with SessionLocal() as s:
            connector, latest, snapshot = self._load_snapshot(s)
            hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            if not hotel or hotel.supplier_name != AOLUGUYA_SUPPLIER:
                raise ValueError("AOLUGUYA_HOSTED_DIRECT_HOTEL_REQUIRED")
            pools = {
                p.physical_room_key: p
                for p in s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id == hotel.hosted_hotel_id)).all()
            }
            if not pools:
                raise ValueError("AOLUGUYA_HOSTED_ROOM_POOLS_REQUIRED")
            variants = s.execute(
                select(HostedDirectRateVariantRow, HostedDirectInventoryPoolRow, HostedDirectRoomOfferRow)
                .join(HostedDirectInventoryPoolRow, HostedDirectInventoryPoolRow.inventory_pool_id == HostedDirectRateVariantRow.inventory_pool_id)
                .join(HostedDirectRoomOfferRow, HostedDirectRoomOfferRow.hosted_offer_id == HostedDirectRateVariantRow.hosted_offer_id)
                .where(HostedDirectInventoryPoolRow.hosted_hotel_id == hotel.hosted_hotel_id)
            ).all()
            missing_rooms = [room["room_key"] for room in snapshot["rooms"] if room["room_key"] not in pools]
            if missing_rooms:
                raise ValueError("AOLUGUYA_CUTOVER_MAPPING_INCOMPLETE:" + ",".join(missing_rooms))
            by_key = _resolve_rate_variants(snapshot["rooms"], variants,
                (hotel.contact_json or {}).get("official_rate_map") or {})
            all_offers = s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == hotel.hosted_hotel_id)).all()
            backup = self._cutover_backup(s, hotel, pools, all_offers)
            touched: set[str] = set()
            # A partial snapshot may stop a sale, but must not erase its identity:
            # otherwise a later unknown plan could claim the old offer by breakfast.
            official_rate_map: dict[str, dict[str, Any]] = {
                offer_id: dict(binding) for offer_id, binding in
                ((hotel.contact_json or {}).get("official_rate_map") or {}).items()
            }
            for room in snapshot["rooms"]:
                pool = pools.get(room["room_key"])
                if not pool:
                    raise ValueError("UNMAPPED_HOSTED_ROOM_KEY:" + room["room_key"])
                pool.physical_room_name = room["room_name"]
                pool.capacity_total = room["inventory"]
                pool.capacity_available = min(pool.capacity_available, room["inventory"])
                if pool.capacity_available < 0:
                    pool.capacity_available = 0
                pool.updated_at = now()
                for rate in room["rates"]:
                    key = (room["room_key"], rate["rate_plan_key"])
                    tupled = by_key.get(key)
                    if not tupled:
                        raise ValueError("UNMAPPED_HOSTED_RATE_VARIANT:" + room["room_key"] + ":" + str(rate["breakfast_count"]))
                    variant, _, offer = tupled
                    offer.room_name = room["room_name"]
                    offer.rate_name = rate["rate_name"]
                    offer.price_minor = rate["price_minor"]
                    offer.currency = rate["currency"]
                    offer.inventory = room["inventory"]
                    offer.cancellation_policy = rate["cancellation_policy"]
                    offer.state = "ACTIVE" if rate["sell_state"] == "OPEN" and room["inventory"] > 0 else "INACTIVE"
                    offer.updated_at = now()
                    variant.state = offer.state
                    touched.add(offer.hosted_offer_id)
                    official_rate_map[offer.hosted_offer_id] = {
                        "room_key": room["room_key"],
                        "rate_plan_key": rate["rate_plan_key"],
                        "taxes_fees": rate["taxes_fees"],
                        "breakfast": rate["breakfast"],
                        "sell_state": rate["sell_state"],
                        "projection_state": offer.state,
                    }
            for offer in all_offers:
                if offer.hosted_offer_id not in touched:
                    offer.state = "INACTIVE"
                    offer.updated_at = now()
                    if offer.hosted_offer_id in official_rate_map:
                        official_rate_map[offer.hosted_offer_id]["projection_state"] = "INACTIVE"
                    for variant, _, variant_offer in variants:
                        if variant_offer.hosted_offer_id == offer.hosted_offer_id:
                            variant.state = "INACTIVE"
            if not any(x.state == "ACTIVE" for x in all_offers):
                raise ValueError("ACTIVE_OFFICIAL_OFFER_REQUIRED")
            contact = dict(hotel.contact_json or {})
            for key in ("environment_marker", "inventory_status", "quote_status"):
                contact.pop(key, None)
            contact.update({
                "supply_truth_status": "HOTEL_OFFICIAL",
                "supply_truth_source_type": snapshot["source_type"],
                "supply_truth_connector_id": connector.connector_id,
                "supply_truth_snapshot_hash": snapshot["content_hash"],
                "supply_truth_source_updated_at": snapshot["source_updated_at"],
                "supply_truth_projected_at": now().isoformat(),
                "supply_truth_evidence_reference": snapshot["evidence_reference"],
                "official_rate_map": official_rate_map,
                "payment_status": "NOT_CONNECTED",
                "publication_scope": "RESERVATION_REQUEST_ONLY",
            })
            if _contains_test_truth(contact):
                raise ValueError("HOSTED_PAGE_TEST_TRUTH_REMAINS")
            hotel.contact_json = contact
            hotel.state = "PUBLISHED_REQUEST_ONLY"
            hotel.updated_at = now()
            # Public page must never expose a mixed test+official truth state.
            if _contains_test_truth(hotel.contact_json) or any(_contains_test_truth(o.rate_name) for o in all_offers if o.state == "ACTIVE"):
                raise ValueError("MIXED_TEST_AND_OFFICIAL_PUBLIC_TRUTH_FORBIDDEN")
            caps = dict(latest.capabilities_json or {})
            caps["aoluguya_cutover_backup"] = backup
            caps["aoluguya_projection"] = {
                "hosted_hotel_id": hotel.hosted_hotel_id,
                "projected_offer_ids": sorted(touched),
                "snapshot_hash": snapshot["content_hash"],
                "projected_at": now().isoformat(),
                "projected_by": actor,
                "payment_connected": False,
            }
            _new_matrix(s, connector, caps)
            s.commit()
            return {
                "state": "AOLUGUYA_SUPPLY_TRUTH_PROJECTED",
                "hosted_hotel_id": hotel.hosted_hotel_id,
                "active_offers": sum(x.state == "ACTIVE" for x in all_offers),
                "inactive_offers": sum(x.state != "ACTIVE" for x in all_offers),
                "snapshot_hash": snapshot["content_hash"],
                "booking_mode": "RESERVATION_REQUEST_ONLY",
                "payment_available": False,
            }

    def status(self) -> dict[str, Any]:
        assessment = self.evaluate()
        with SessionLocal() as s:
            hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == AOLUGUYA_SLUG))
            if not hotel:
                return assessment | {"hosted_page": None}
            offers = s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == hotel.hosted_hotel_id)).all()
            contact = hotel.contact_json or {}
            official = contact.get("supply_truth_status") == "HOTEL_OFFICIAL"
            no_test = not _contains_test_truth(contact) and all(not _contains_test_truth(o.rate_name) for o in offers if o.state == "ACTIVE")
            return assessment | {
                "hosted_page": {
                    "hotel_state": hotel.state,
                    "supply_truth_status": contact.get("supply_truth_status"),
                    "active_offers": sum(x.state == "ACTIVE" for x in offers),
                    "official_projection": official,
                    "no_test_truth": no_test,
                    "payment_available": False,
                }
            }

    def fallback_governance(self) -> dict[str, Any]:
        with SessionLocal() as s:
            provider_states = {}
            connectors = s.scalars(select(ProductionConnectorRow).where(ProductionConnectorRow.vertical == "HOTEL")).all()
            for provider_code in FALLBACK_TIER_1:
                matched = []
                for connector in connectors:
                    latest = _latest_matrix(s, connector.connector_id)
                    contract = (latest.capabilities_json or {}).get("provider_adapter_contract") if latest else None
                    code = ((contract or {}).get("provider") or {}).get("provider_code")
                    if code == provider_code:
                        authority = s.scalar(select(ConnectorAuthorityRow).where(
                            ConnectorAuthorityRow.connector_id == connector.connector_id,
                            ConnectorAuthorityRow.state == "ACTIVE",
                        ).order_by(ConnectorAuthorityRow.valid_from.desc()))
                        runs = s.scalars(select(ConnectorCertificationRunRow).where(
                            ConnectorCertificationRunRow.connector_id == connector.connector_id,
                            ConnectorCertificationRunRow.environment == "SANDBOX",
                            ConnectorCertificationRunRow.result == "PASS",
                        )).all()
                        certified = any((r.evidence_json or {}).get("external_transport_attested") for r in runs)
                        matched.append({
                            "connector_id": connector.connector_id,
                            "supplier": connector.supplier_legal_name,
                            "authorized": bool(authority),
                            "externally_verified": certified,
                            "eligible": bool(authority and certified),
                        })
                provider_states[provider_code] = {
                    "display_name": FALLBACK_NAMES[provider_code],
                    "tier": 1,
                    "connectors": matched,
                    "eligible": any(x["eligible"] for x in matched),
                    "state": "ELIGIBLE_AUTHORIZED_FALLBACK" if any(x["eligible"] for x in matched) else "NOT_EXTERNALLY_VERIFIED",
                }
            return {
                "routing_policy": "DIRECT_FIRST_AUTHORIZED_MULTI_FALLBACK",
                "official_direct_priority": 0,
                "fallback_tier_1": list(FALLBACK_TIER_1),
                "providers": provider_states,
                "single_ota_core_dependency": False,
                "unverified_fallback_allowed": False,
                "payment_scope": "OUT_OF_SCOPE",
            }

    def route(self, body: dict[str, Any]) -> dict[str, Any]:
        business_id = str(body.get("business_id") or AOLUGUYA_SLUG)
        official_available = bool(body.get("official_available"))
        booking_context = str(body.get("booking_context") or "NEW_BOOKING").upper()
        candidates = body.get("fallback_candidates") or []
        if official_available:
            decision = vertical_source_runtime_service.decide("HOTEL", business_id, [{
                "source_id": AOLUGUYA_CONNECTOR_KEY,
                "source_type": "HOTEL_OFFICIAL_DIRECT",
                "authorized": True,
                "available": True,
                "evidence_reference": "hotel-official://aoluguya/supply-truth",
            }])
            return decision | {"fallback_provider": None, "fallback_used": False}

        governance = self.fallback_governance()
        eligible_by_code = {
            code: data for code, data in governance["providers"].items() if data["eligible"]
        }
        selected = None
        for code in FALLBACK_TIER_1:
            if code not in eligible_by_code:
                continue
            candidate = next((x for x in candidates if str(x.get("provider_code") or "").upper() == code
                              and x.get("available") is True and x.get("evidence_reference")
                              and str(x.get("health_state") or "HEALTHY").upper() == "HEALTHY"
                              and (booking_context == "EXISTING_BOOKING_FULFILLMENT" or x.get("accept_new_bookings", True) is True)), None)
            if candidate:
                selected = candidate
                break
        source_candidates = []
        if selected:
            source_candidates.append({
                "source_id": str(selected.get("connector_id") or selected["provider_code"]),
                "source_type": "AUTHORIZED_FALLBACK",
                "authorized": True,
                "available": True,
                "evidence_reference": selected["evidence_reference"],
            })
        decision = vertical_source_runtime_service.decide("HOTEL", business_id, source_candidates)
        return decision | {
            "fallback_provider": selected.get("provider_code") if selected else None,
            "fallback_used": bool(selected),
            "fail_closed": selected is None,
            "booking_context": booking_context,
            "existing_booking_fulfillment_exit_independent": True,
            "canonical_hotel_id_preserved": business_id,
        }


aoluguya_supply_truth_service = AoluguyaSupplyTruthService()
