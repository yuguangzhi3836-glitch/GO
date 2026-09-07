from go_hotel.services.chain_autonomous_build import discovery_seed
from go_hotel.services.chain_hotel_registry import ChainCode, OfficialPropertySeed


def test_verified_chain_seed_maps_to_group_official_discovery():
    official = OfficialPropertySeed(
        chain=ChainCode.HYATT,
        official_property_id="BEIPH",
        name="Park Hyatt Beijing",
        property_url="https://www.hyatt.com/en-US/hotel/china/park-hyatt-beijing/beiph",
        directory_url="https://www.hyatt.com/zh-CN/destinations/chinese-mainland",
        country_code="CN",
        city="Beijing",
    )
    seed = discovery_seed(official)
    assert seed["external_ids"]["chain:hyatt"] == "BEIPH"
    assert seed["source_hints"] == [{
        "kind": "GROUP_OFFICIAL",
        "source_key": "chain:hyatt",
        "external_hotel_id": "BEIPH",
        "url": official.property_url,
        "rights_status": "PUBLIC_BUSINESS_FACT",
        "confidence_bps": 9900,
    }]
