import pytest

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    HotelPartnerRatePlanRow,
    HotelPartnerRoomTypeRow,
    HotelPartnerSellableProductRow,
)
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc

SID = "sup_demo"
ACT = "hotel_owner"


def prop(name="GO 测试酒店"):
    return svc.create_property(
        SID,
        ACT,
        {
            "name_zh": name,
            "name_en": "GO Test Hotel",
            "property_type": "HOTEL",
            "address": {"city": "Harbin"},
            "contacts": {"phone": "123"},
            "legal": {"company": "GO Hotel Ltd"},
        },
    )


def room(pid, name="豪华房"):
    return svc.create_room_type(
        SID,
        ACT,
        pid,
        {
            "name_zh": name,
            "physical_room_count": 20,
            "occupancy": {"max_occupancy": 4, "max_adults": 2, "max_children": 2},
            "bed_configurations": [{"bed_type": "KING", "width_cm": 180, "count": 1}],
        },
    )


def product(pid, room_type_id, name):
    return svc.create_product(SID, ACT, pid, {"room_type_id": room_type_id, "name": name})


def rate(pid, sellable_product_id, name):
    return svc.create_rate_plan(
        SID,
        ACT,
        pid,
        {
            "sellable_product_id": sellable_product_id,
            "name": name,
            "payment_type": "PREPAID",
            "cancellation_tiers": [
                {"before_arrival_hours": 48, "charge_percent": 0},
                {"before_arrival_hours": 0, "charge_percent": 100},
            ],
            "default_ari": {"sell_status": "OPEN"},
        },
    )


def test_room_reactivation_preserves_child_state_and_effective_sales_gates():
    p = prop()
    rt = room(p["property_id"])
    active_product = product(p["property_id"], rt["room_type_id"], "双人入住")
    inactive_product = product(p["property_id"], rt["room_type_id"], "三人入住")
    active_rate = rate(p["property_id"], active_product["sellable_product_id"], "灵活含早")
    inactive_rate = rate(p["property_id"], inactive_product["sellable_product_id"], "限时不退")
    svc.set_sellable_product_state(SID, ACT, p["property_id"], inactive_product["sellable_product_id"], "INACTIVE")
    svc.set_rate_plan_state(SID, ACT, p["property_id"], inactive_rate["rate_plan_id"], "INACTIVE")

    disabled = svc.set_room_type_state(SID, ACT, p["property_id"], rt["room_type_id"], "INACTIVE")
    assert disabled["state"] == "INACTIVE"
    disabled_graph = svc.graph(SID, p["property_id"])
    disabled_products = {x["sellable_product_id"]: x for x in disabled_graph["sellable_products"]}
    disabled_rates = {x["rate_plan_id"]: x for x in disabled_graph["rate_plans"]}
    assert disabled_products[active_product["sellable_product_id"]]["state"] == "ACTIVE"
    assert disabled_products[active_product["sellable_product_id"]]["effective_state"] == "INACTIVE"
    assert disabled_products[inactive_product["sellable_product_id"]]["blocked_by"] == [
        "ROOM_TYPE_STATE",
        "SELLABLE_PRODUCT_STATE",
    ]
    assert disabled_rates[active_rate["rate_plan_id"]]["effective_state"] == "INACTIVE"
    assert "ROOM_TYPE_STATE" in disabled_rates[inactive_rate["rate_plan_id"]]["blocked_by"]

    reenabled = svc.set_room_type_state(SID, ACT, p["property_id"], {"room_type_id": rt["room_type_id"], "state": "ACTIVE"})
    assert reenabled["effective_state"] == "ACTIVE"
    reenabled_graph = svc.graph(SID, p["property_id"])
    reenabled_products = {x["sellable_product_id"]: x for x in reenabled_graph["sellable_products"]}
    reenabled_rates = {x["rate_plan_id"]: x for x in reenabled_graph["rate_plans"]}
    assert reenabled_products[active_product["sellable_product_id"]]["effective_state"] == "ACTIVE"
    assert reenabled_products[inactive_product["sellable_product_id"]]["state"] == "INACTIVE"
    assert reenabled_products[inactive_product["sellable_product_id"]]["effective_state"] == "INACTIVE"
    assert reenabled_rates[active_rate["rate_plan_id"]]["effective_state"] == "ACTIVE"
    assert reenabled_rates[inactive_rate["rate_plan_id"]]["effective_state"] == "INACTIVE"


def test_room_state_change_is_persisted_idempotent_and_has_no_failure_side_effect():
    p = prop()
    rt = room(p["property_id"])
    first = svc.set_room_type_state(SID, ACT, p["property_id"], rt["room_type_id"], "INACTIVE")
    second = svc.set_room_type_state(SID, ACT, p["property_id"], rt["room_type_id"], "INACTIVE")
    assert first["state"] == second["state"] == "INACTIVE"

    with SessionLocal() as s:
        persisted = s.get(HotelPartnerRoomTypeRow, rt["room_type_id"])
        assert persisted is not None and persisted.state == "INACTIVE"

    other = prop("另一家酒店")
    with pytest.raises(ValueError, match="ROOM_TYPE_NOT_FOUND"):
        svc.set_room_type_state(SID, ACT, other["property_id"], rt["room_type_id"], "ACTIVE")

    with SessionLocal() as s:
        persisted = s.get(HotelPartnerRoomTypeRow, rt["room_type_id"])
        assert persisted is not None and persisted.state == "INACTIVE"


def test_graph_round_trips_mixed_child_states_after_restart_like_readback():
    p = prop()
    rt = room(p["property_id"])
    primary_product = product(p["property_id"], rt["room_type_id"], "双人入住")
    secondary_product = product(p["property_id"], rt["room_type_id"], "家庭入住")
    primary_rate = rate(p["property_id"], primary_product["sellable_product_id"], "灵活含早")
    secondary_rate = rate(p["property_id"], secondary_product["sellable_product_id"], "限时不退")

    svc.set_sellable_product_state(SID, ACT, p["property_id"], secondary_product["sellable_product_id"], "INACTIVE")
    svc.set_rate_plan_state(SID, ACT, p["property_id"], primary_rate["rate_plan_id"], "INACTIVE")

    with SessionLocal() as s:
        assert s.get(HotelPartnerSellableProductRow, secondary_product["sellable_product_id"]).state == "INACTIVE"
        assert s.get(HotelPartnerRatePlanRow, primary_rate["rate_plan_id"]).state == "INACTIVE"

    graph = svc.graph(SID, p["property_id"])
    products = {x["sellable_product_id"]: x for x in graph["sellable_products"]}
    rates = {x["rate_plan_id"]: x for x in graph["rate_plans"]}
    assert products[primary_product["sellable_product_id"]]["effective_state"] == "ACTIVE"
    assert products[secondary_product["sellable_product_id"]]["effective_state"] == "INACTIVE"
    assert rates[primary_rate["rate_plan_id"]]["effective_state"] == "INACTIVE"
    assert rates[secondary_rate["rate_plan_id"]]["effective_state"] == "INACTIVE"
    assert rates[secondary_rate["rate_plan_id"]]["blocked_by"] == ["SELLABLE_PRODUCT_STATE"]
