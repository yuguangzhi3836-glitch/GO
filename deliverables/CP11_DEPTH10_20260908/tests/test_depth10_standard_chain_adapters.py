import pytest

from go_hotel.services.chain_hotel_registry import ChainCode
from go_hotel.services.standard_chain_directory_adapters import (
    MarriottDirectoryAdapter, HiltonDirectoryAdapter, IHGDirectoryAdapter,
)


def fetch(html, final):
    return lambda _: (final, html)


def test_marriott_official_link_dedupe_and_cursor():
    html = '''<a href="https://www.marriott.com/en-us/hotels/nycmq-marriott-marquis/">New York Marriott Marquis</a>
              <a href="/en-us/hotels/nycmq-marriott-marquis/">New York Marriott Marquis</a>
              <a href="https://evil.example/en-us/hotels/bad-hotel/">Bad Hotel</a>'''
    adapter = MarriottDirectoryAdapter(page_size=1)
    seeds, cursor = adapter.enumerate_page(fetch(html, "https://www.marriott.com/en-us/hotel-search.mi"))
    assert len(seeds) == 1 and seeds[0].chain == ChainCode.MARRIOTT
    assert seeds[0].official_property_id == "NYCMQ"
    assert cursor is None


def test_hilton_rejects_nonofficial_final_url():
    adapter = HiltonDirectoryAdapter()
    with pytest.raises(ValueError, match="FINAL_URL_NOT_OFFICIAL"):
        adapter.enumerate_page(fetch('<a href="/en/hotels/abcde-test/">Hotel Test</a>', "https://evil.example/locations"))


def test_ihg_extracts_stable_property_code():
    html = '<a href="https://www.ihg.com/hotels/us/en/beijing/bejsa/hoteldetail">InterContinental Beijing Test</a>'
    adapter = IHGDirectoryAdapter()
    seeds, cursor = adapter.enumerate_page(fetch(html, "https://www.ihg.com/hotels/us/en/reservation"))
    assert cursor is None
    assert seeds[0].official_property_id == "BEJSA"


def test_snapshot_drift_fails_closed():
    first = '<a href="/en-us/hotels/nycmq-marriott-marquis/">New York Marriott Marquis</a><a href="/en-us/hotels/bosco-boston-hotel/">Boston Marriott Hotel</a>'
    adapter = MarriottDirectoryAdapter(page_size=1)
    _, cursor = adapter.enumerate_page(fetch(first, "https://www.marriott.com/en-us/hotel-search.mi"))
    changed = first + '<a href="/en-us/hotels/chico-chicago-hotel/">Chicago Marriott Hotel</a>'
    with pytest.raises(ValueError, match="SNAPSHOT_CHANGED"):
        adapter.enumerate_page(fetch(changed, "https://www.marriott.com/en-us/hotel-search.mi"), cursor)
