import pytest

from go_hotel.services.hyatt_directory_adapter import HyattDirectoryAdapter


HTML = '''
<html><body>
<a href="/en-US/hotel/china/park-hyatt-beijing/beiph">Park Hyatt Beijing</a>
<a href="/en-US/hotel/china/grand-hyatt-beijing/beigh">Grand Hyatt Beijing</a>
<a href="/en-US/hotel/china/park-hyatt-beijing/beiph">Park Hyatt Beijing</a>
<a href="https://example.com/en-US/hotel/china/fake/xxxxx">Fake Hotel</a>
<a href="/en-US/destinations/chinese-mainland">View Hotel</a>
</body></html>
'''


def fetch(url):
    return "https://www.hyatt.com/zh-CN/destinations/chinese-mainland", HTML


def test_hyatt_directory_enumerates_unique_official_properties():
    adapter = HyattDirectoryAdapter(page_size=10)
    seeds, cursor = adapter.enumerate_page(fetch)
    assert cursor is None
    assert [x.official_property_id for x in seeds] == ["BEIGH", "BEIPH"]
    assert {x.name for x in seeds} == {"Grand Hyatt Beijing", "Park Hyatt Beijing"}
    assert all(x.property_url.startswith("https://www.hyatt.com/") for x in seeds)


def test_hyatt_directory_cursor_is_resumable_and_snapshot_bound():
    adapter = HyattDirectoryAdapter(page_size=1)
    first, cursor = adapter.enumerate_page(fetch)
    assert len(first) == 1 and cursor
    second, end = adapter.enumerate_page(fetch, cursor)
    assert len(second) == 1 and end is None
    assert first[0].official_property_id != second[0].official_property_id

    def changed(url):
        return "https://www.hyatt.com/zh-CN/destinations/chinese-mainland", HTML + "<!-- changed -->"
    with pytest.raises(ValueError, match="HYATT_DIRECTORY_SNAPSHOT_CHANGED"):
        adapter.enumerate_page(changed, cursor)


def test_hyatt_directory_rejects_redirect_to_non_official_host():
    adapter = HyattDirectoryAdapter()
    with pytest.raises(ValueError, match="HYATT_DIRECTORY_FINAL_URL_NOT_OFFICIAL"):
        adapter.enumerate_page(lambda url: ("https://example.com/list", HTML))


def test_hyatt_directory_fails_closed_on_same_code_conflicting_names():
    html = '''
    <a href="/en-US/hotel/china/a/beiph">Park Hyatt Beijing</a>
    <a href="/en-US/hotel/china/b/beiph">Different Hotel</a>
    '''
    adapter = HyattDirectoryAdapter()
    with pytest.raises(ValueError, match="HYATT_DIRECTORY_PROPERTY_NAME_CONFLICT"):
        adapter.enumerate_page(lambda url: (url, html))
