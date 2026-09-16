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
    assert first["page"] == {"limit": 7, "offset": 0, "has_more": True, "next_offset": 7}
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
