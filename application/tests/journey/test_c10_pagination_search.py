"""C10 bounded Journey pagination/search contract."""
import pytest

from go_hotel.journey import service as journey_module
from test_c10_batch_list_projection import grow
from test_c10_current_status_projection import MEMBER, OWNER, _seed, isolated_session

pytestmark = pytest.mark.no_db


def test_list_page_bounds_result_and_reports_next_offset(isolated_session):
    _seed(isolated_session, "HOTEL")
    grow(isolated_session, "HOTEL", 31)

    first = journey_module.journey_service.list_page(OWNER, limit=7, offset=0)
    second = journey_module.journey_service.list_page(OWNER, limit=7, offset=7)

    assert len(first["items"]) == len(second["items"]) == 7
    assert {k:first["page"][k] for k in ("limit","offset","has_more","next_offset")} == {"limit": 7, "offset": 0, "has_more": True, "next_offset": 7}
    assert first["page"]["next_cursor"]
    assert second["page"]["offset"] == 7
    assert {row["journey_id"] for row in first["items"]}.isdisjoint(
        row["journey_id"] for row in second["items"]
    )


def test_list_page_shared_access_search_and_limit_clamp(isolated_session):
    _seed(isolated_session, "HOTEL")
    grow(isolated_session, "HOTEL", 4)

    found = journey_module.journey_service.list_page(MEMBER, limit=500, query="J0003")
    missing = journey_module.journey_service.list_page(MEMBER, query="not-present")

    assert found["page"]["limit"] == 100
    assert [row["journey_id"] for row in found["items"]] == ["c10_batch_j0003"]
    assert found["query"] == "j0003"
    assert missing["items"] == []


def test_list_page_clamps_pathological_deep_offset(isolated_session):
    _seed(isolated_session, "HOTEL")
    page = journey_module.journey_service.list_page(OWNER, limit=20, offset=10**9)
    assert page["page"]["offset"] == 10000
    assert page["items"] == []


def test_keyset_cursor_pages_without_duplicate_or_skip(isolated_session):
    _seed(isolated_session, "HOTEL")
    grow(isolated_session, "HOTEL", 31)
    seen = []
    cursor = None
    while True:
        page = journey_module.journey_service.list_page(OWNER, limit=6, cursor=cursor)
        ids = [row["journey_id"] for row in page["items"]]
        assert set(seen).isdisjoint(ids)
        seen.extend(ids)
        cursor = page["page"]["next_cursor"]
        if not page["page"]["has_more"]:
            assert cursor is None
            break
    assert len(seen) == len(set(seen)) == 31


def test_cursor_rejects_tamper_query_scope_and_offset_mix(isolated_session):
    _seed(isolated_session, "HOTEL")
    grow(isolated_session, "HOTEL", 4)
    first = journey_module.journey_service.list_page(OWNER, limit=2, query="j")
    cursor = first["page"]["next_cursor"]
    assert cursor
    with pytest.raises(ValueError, match="JOURNEY_CURSOR_INVALID"):
        journey_module.journey_service.list_page(OWNER, limit=2, query="j", cursor=cursor[:-1] + ("A" if cursor[-1] != "A" else "B"))
    with pytest.raises(ValueError, match="JOURNEY_CURSOR_INVALID"):
        journey_module.journey_service.list_page(OWNER, limit=2, query="different", cursor=cursor)
    with pytest.raises(ValueError, match="JOURNEY_CURSOR_OFFSET_CONFLICT"):
        journey_module.journey_service.list_page(OWNER, limit=2, offset=1, query="j", cursor=cursor)
