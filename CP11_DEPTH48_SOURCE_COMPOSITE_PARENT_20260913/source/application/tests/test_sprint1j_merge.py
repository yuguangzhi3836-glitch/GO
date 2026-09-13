from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.domain.models import Offer, new_id
from go_hotel.merge.engine import offer_merge_engine
from go_hotel.merge.identity import room_identity_service
from go_hotel.merge.drift import drift_service
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OfferDriftEventRow, OfferMergeDecisionRow
from go_hotel.routing.sla import sla_service


def mk(connector, room, amount, *, official=False, refundable=True, fare="fr_flex", meal="ROOM_ONLY", inventory=3):
    return Offer(new_id("off"),"htl_conrad_tokyo",room,"rate_std",amount,"CNY","2026-09-01","2026-09-05",official_direct=official,fare_rule_id=fare,connector_id=connector,meal_plan=meal,refundable=refundable,inventory_units=inventory)

def test_room_mapping_merges_equivalent_sources_and_official_wins():
    room_identity_service.map("conn_a","A-DELUXE-KING","room_deluxe_king")
    room_identity_service.map("conn_b","DELUXE KING ROOM","room_deluxe_king")
    sla_service.upsert_snapshot("conn_a",success_rate_bps=9600,confirmation_latency_ms_p95=700,cancel_success_rate_bps=9700,inventory_accuracy_bps=9800,price_consistency_bps=9800,sample_size=100)
    sla_service.upsert_snapshot("conn_b",success_rate_bps=10000,confirmation_latency_ms_p95=200,cancel_success_rate_bps=10000,inventory_accuracy_bps=10000,price_consistency_bps=10000,sample_size=100)
    a=mk("conn_a","A-DELUXE-KING",1500000,official=True)
    b=mk("conn_b","DELUXE KING ROOM",1400000,official=False)
    selected,decisions=offer_merge_engine.merge([a,b])
    assert len(selected)==1
    assert selected[0].connector_id=="conn_a"
    assert decisions[0].alternate_offer_ids==[b.offer_id]
    assert decisions[0].conflicts[0]["type"]=="PRICE_CONFLICT"

def test_material_policy_difference_is_not_collapsed():
    room_identity_service.map("conn_a","A-DELUXE-KING","room_deluxe_king")
    room_identity_service.map("conn_b","DELUXE KING ROOM","room_deluxe_king")
    a=mk("conn_a","A-DELUXE-KING",1500000,official=True,refundable=True,fare="fr_flex")
    b=mk("conn_b","DELUXE KING ROOM",1300000,official=False,refundable=False,fare="fr_nonref")
    selected,decisions=offer_merge_engine.merge([a,b])
    assert len(selected)==2
    assert len(decisions)==2

def test_price_and_inventory_drift_creates_event():
    room_identity_service.map("conn_a","A-DELUXE-KING","room_deluxe_king")
    a=mk("conn_a","A-DELUXE-KING",1500000,official=True,inventory=3)
    drift_service.observe(a,"room_deluxe_king")
    b=mk("conn_a","A-DELUXE-KING",1510000,official=True,inventory=1)
    # same drift key: same rate/stay/source, only observed facts change
    drift_service.observe(b,"room_deluxe_king")
    with SessionLocal() as s:
        rows=s.scalars(select(OfferDriftEventRow)).all()
        assert len(rows)==1
        assert set(rows[0].changed_fields)=={"total_amount_minor","inventory_units"}

def test_merge_governance_api(client):
    r=client.put("/internal/v1/merge/room-mappings",json={"connector_id":"conn_a","external_room_id":"R1","canonical_room_id":"room_1"})
    assert r.status_code==200
    assert r.json()["data"]["status"]=="ACTIVE"
    r=client.get("/internal/v1/merge/drift")
    assert r.status_code==200
