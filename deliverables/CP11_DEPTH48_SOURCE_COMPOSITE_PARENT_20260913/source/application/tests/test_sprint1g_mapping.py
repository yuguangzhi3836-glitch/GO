import json
from pathlib import Path
from go_hotel.connectors.mapping import CanonicalOfferMapping
from go_hotel.connectors.siteminder.normalizer import SiteMinderCanonicalNormalizer

def test_siteminder_synthetic_canonical_offer_mapping():
    payload=json.loads(Path("tests/fixtures/siteminder/synthetic_search.json").read_text())
    mapping=CanonicalOfferMapping(offers_path="inventory",external_property_id="property.id",external_room_id="room.id",external_rate_id="rate.id",amount_minor="price.minor",currency="price.currency",check_in="stay.check_in",check_out="stay.check_out")
    n=SiteMinderCanonicalNormalizer("conn_siteminder_channels_plus",mapping,lambda x:"htl_001" if x=="SM-PROP-001" else None)
    offers=n.normalize_search(payload)
    assert len(offers)==1
    o=offers[0]; assert o.hotel_id=="htl_001"; assert o.total_amount_minor==1523200; assert o.currency=="CNY"

def test_unmapped_property_is_not_exposed():
    payload={"inventory":[{"property":{"id":"UNKNOWN"},"room":{"id":"R"},"rate":{"id":"X"},"price":{"minor":100,"currency":"USD"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-02"}}]}
    mapping=CanonicalOfferMapping(offers_path="inventory",external_property_id="property.id",external_room_id="room.id",external_rate_id="rate.id",amount_minor="price.minor",currency="price.currency",check_in="stay.check_in",check_out="stay.check_out")
    assert SiteMinderCanonicalNormalizer("c",mapping,lambda _:None).normalize_search(payload)==[]
