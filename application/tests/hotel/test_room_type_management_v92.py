import os

import pytest

os.environ["DATABASE_URL"] = "sqlite:////tmp/gh-aw/agent/go_partner_room_type_v92.db"

from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc


SID = "sup_room_v92"
OTHER_SID = "sup_room_other_v92"
ACT = "hotel_owner_v92"


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def prop(supplier_id=SID):
    return svc.create_property(
        supplier_id,
        ACT,
        {
            "name_zh": "GO 房型管理测试酒店",
            "name_en": "GO Room Type Test Hotel",
            "property_type": "HOTEL",
            "address": {"city": "Beijing"},
            "contacts": {"phone": "123456"},
            "legal": {"company": "GO Room Type Test Ltd"},
        },
    )


def room(pid):
    return svc.create_room_type(
        SID,
        ACT,
        pid,
        {
            "name_zh": "豪华大床房",
            "name_en": "Deluxe King",
            "physical_room_count": 12,
            "occupancy": {"max_occupancy": 3, "max_adults": 2, "max_children": 1},
            "bed_configurations": [{"bed_type": "KING", "width_cm": 180, "count": 1}],
            "attributes": {"area_sqm": 45, "window_type": "WINDOW", "view_type": "城市景观"},
            "media": [{"url": "https://example.test/room.jpg"}],
        },
    )


def rate(pid):
    rt = room(pid)
    product = svc.create_product(SID, ACT, pid, {"room_type_id": rt["room_type_id"], "name": "双人入住"})
    rate_plan = svc.create_rate_plan(
        SID,
        ACT,
        pid,
        {
            "sellable_product_id": product["sellable_product_id"],
            "name": "灵活含早",
            "payment_type": "PREPAID",
            "cancellation_tiers": [
                {"before_arrival_hours": 48, "charge_percent": 0},
                {"before_arrival_hours": 0, "charge_percent": 100},
            ],
            "default_ari": {"sell_status": "OPEN"},
        },
    )
    return rt, product, rate_plan


def test_room_type_update_preserves_unspecified_fields_and_reloads_from_graph():
    p = prop()
    rt = room(p["property_id"])
    updated = svc.update_room_type(
        SID,
        ACT,
        p["property_id"],
        rt["room_type_id"],
        {
            "name_zh": "行政大床房",
            "physical_room_count": 18,
            "occupancy": {"max_occupancy": 4, "max_adults": 2, "max_children": 2},
            "attributes": {"area_sqm": 52, "window_type": "WINDOW", "view_type": "园景"},
        },
    )

    assert updated["name_zh"] == "行政大床房"
    assert updated["physical_room_count"] == 18
    assert updated["occupancy_json"]["max_occupancy"] == 4
    assert updated["bed_configurations_json"] == [{"bed_type": "KING", "width_cm": 180, "count": 1}]
    assert updated["media_json"] == [{"url": "https://example.test/room.jpg"}]

    graph = svc.graph(SID, p["property_id"])
    room_row = next(x for x in graph["room_types"] if x["room_type_id"] == rt["room_type_id"])
    assert room_row["name_zh"] == "行政大床房"
    assert room_row["attributes_json"]["view_type"] == "园景"
    assert room_row["media_json"] == [{"url": "https://example.test/room.jpg"}]


def test_room_type_disable_enable_cascades_to_sellable_layers_and_is_idempotent():
    p = prop()
    rt, product, rate_plan = rate(p["property_id"])

    disabled = svc.set_room_type_state(SID, ACT, p["property_id"], rt["room_type_id"], "inactive")
    assert disabled["room_type"]["state"] == "INACTIVE"
    assert [x["state"] for x in disabled["sellable_products"]] == ["INACTIVE"]
    assert [x["state"] for x in disabled["rate_plans"]] == ["INACTIVE"]

    disabled_again = svc.set_room_type_state(SID, ACT, p["property_id"], rt["room_type_id"], "INACTIVE")
    assert disabled_again["room_type"]["state"] == "INACTIVE"

    with pytest.raises(ValueError, match="ROOM_TYPE_NOT_ACTIVE"):
        svc.create_product(SID, ACT, p["property_id"], {"room_type_id": rt["room_type_id"], "name": "停售后不可新增"})

    reenabled = svc.set_room_type_state(SID, ACT, p["property_id"], rt["room_type_id"], "ACTIVE")
    assert reenabled["room_type"]["state"] == "ACTIVE"
    assert [x["sellable_product_id"] for x in reenabled["sellable_products"]] == [product["sellable_product_id"]]
    assert [x["rate_plan_id"] for x in reenabled["rate_plans"]] == [rate_plan["rate_plan_id"]]
    assert [x["state"] for x in reenabled["sellable_products"]] == ["ACTIVE"]
    assert [x["state"] for x in reenabled["rate_plans"]] == ["ACTIVE"]


def test_room_type_update_rejects_invalid_payload_and_cross_supplier_access():
    p = prop()
    rt = room(p["property_id"])
    other_property = prop(OTHER_SID)

    with pytest.raises(ValueError, match="INVALID_PHYSICAL_ROOM_COUNT"):
        svc.update_room_type(SID, ACT, p["property_id"], rt["room_type_id"], {"physical_room_count": 0})
    with pytest.raises(ValueError, match="INVALID_OCCUPANCY_CONSTRAINT"):
        svc.update_room_type(
            SID,
            ACT,
            p["property_id"],
            rt["room_type_id"],
            {"occupancy": {"max_occupancy": 3, "max_adults": 1, "max_children": 1}},
        )
    with pytest.raises(ValueError, match="PROPERTY_NOT_FOUND"):
        svc.update_room_type(OTHER_SID, ACT, p["property_id"], rt["room_type_id"], {"name_zh": "越权编辑"})
    with pytest.raises(ValueError, match="PROPERTY_NOT_FOUND"):
        svc.set_room_type_state(SID, ACT, other_property["property_id"], rt["room_type_id"], "INACTIVE")

    graph = svc.graph(SID, p["property_id"])
    room_row = next(x for x in graph["room_types"] if x["room_type_id"] == rt["room_type_id"])
    assert room_row["name_zh"] == "豪华大床房"
    assert room_row["physical_room_count"] == 12
