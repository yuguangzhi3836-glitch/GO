import pytest

from go_hotel.services.chain_hotel_registry import ChainCode
from go_hotel.services.standard_chain_directory_adapters import ShangriLaDirectoryAdapter


def test_shangrila_extracts_city_property_identity_and_dedupes():
    html = '''
    <a href="https://www.shangri-la.com/harbin/shangrila/">Shangri-La Harbin</a>
    <a href="/harbin/shangrila/">Shangri-La Harbin</a>
    <a href="/harbin/songbeishangrila/">Shangri-La Songbei, Harbin</a>
    '''
    adapter = ShangriLaDirectoryAdapter(directory_url="https://www.shangri-la.com/cn/find-a-hotel/", page_size=10)
    seeds, cursor = adapter.enumerate_page(lambda _: ("https://www.shangri-la.com/cn/find-a-hotel/", html))
    assert cursor is None
    assert [s.chain for s in seeds] == [ChainCode.SHANGRI_LA, ChainCode.SHANGRI_LA]
    assert {s.official_property_id for s in seeds} == {"HARBIN__SHANGRILA", "HARBIN__SONGBEISHANGRILA"}


def test_shangrila_rejects_nonofficial_final_directory_host():
    adapter = ShangriLaDirectoryAdapter()
    with pytest.raises(ValueError, match="FINAL_URL_NOT_OFFICIAL"):
        adapter.enumerate_page(lambda _: ("https://example.com/hotels", '<a href="/harbin/shangrila/">X</a>'))


def test_shangrila_snapshot_drift_fails_closed():
    adapter = ShangriLaDirectoryAdapter(page_size=1)
    first = '<a href="/harbin/shangrila/">Shangri-La Harbin</a><a href="/beijing/chinaworld/">China World Hotel Beijing</a>'
    _, cursor = adapter.enumerate_page(lambda _: (adapter.directory_url, first))
    assert cursor
    changed = first + '<a href="/shanghai/pudongshangrila/">Pudong Shangri-La Shanghai</a>'
    with pytest.raises(ValueError, match="SNAPSHOT_CHANGED"):
        adapter.enumerate_page(lambda _: (adapter.directory_url, changed), cursor)
