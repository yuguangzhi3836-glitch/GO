import pytest

from go_hotel.services.chain_hotel_registry import (
    CHAIN_EXECUTION_ORDER,
    ChainCode,
    ChainDirectoryAdapter,
    OfficialPropertySeed,
    validate_official_seed,
)


def seed(**overrides):
    values = dict(
        chain=ChainCode.HYATT,
        official_property_id="HRBUB",
        name="Aoluguya Hotel",
        property_url="https://www.hyatt.com/example/hrbub",
        directory_url="https://www.hyatt.com/explore-hotels",
        country_code="CN",
        city="Harbin",
    )
    values.update(overrides)
    return OfficialPropertySeed(**values)


def test_locked_chain_order():
    assert CHAIN_EXECUTION_ORDER == (
        ChainCode.HYATT, ChainCode.MARRIOTT, ChainCode.HILTON,
        ChainCode.IHG, ChainCode.H_WORLD, ChainCode.ATOUR,
    )


def test_seed_idempotency_uses_chain_and_official_id_not_display_name():
    a = seed(name="Name A")
    b = seed(name="Renamed Hotel")
    assert a.idempotency_key == b.idempotency_key


def test_seed_rejects_non_official_host():
    with pytest.raises(ValueError, match="CHAIN_SOURCE_HOST_NOT_ALLOWED"):
        validate_official_seed(seed(property_url="https://example.com/hotel"))


def test_seed_rejects_insecure_url():
    with pytest.raises(ValueError, match="CHAIN_OFFICIAL_HTTPS_URL_REQUIRED"):
        validate_official_seed(seed(directory_url="http://www.hyatt.com/explore-hotels"))


def test_adapter_deduplicates_same_official_property():
    class Hyatt(ChainDirectoryAdapter):
        chain = ChainCode.HYATT
    assert len(Hyatt().validate([seed(), seed(name="Alias")])) == 1


def test_adapter_rejects_cross_chain_seed():
    class Hyatt(ChainDirectoryAdapter):
        chain = ChainCode.HYATT
    wrong = seed(chain=ChainCode.MARRIOTT,
                 property_url="https://www.marriott.com/hotels/example",
                 directory_url="https://www.marriott.com/hotel-search.mi")
    with pytest.raises(ValueError, match="CHAIN_ADAPTER_SEED_MISMATCH"):
        Hyatt().validate([wrong])
