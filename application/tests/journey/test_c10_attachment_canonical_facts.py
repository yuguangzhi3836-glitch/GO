"""Caller display metadata must not replace canonical order facts."""
import pytest
from go_hotel.db.models import GoJourneyItemRow
from go_hotel.journey import service as journey_module
from test_c10_current_status_projection import isolated_session, _seed, OWNER, JOURNEY_ID, ITEM_ID, ORDER_ID

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("vertical", sorted(journey_module.VERTICALS))
@pytest.mark.parametrize("entrypoint", ["attach", "create"])
def test_attachment_preserves_order_facts_and_allows_custom_notes(isolated_session, vertical, entrypoint):
    model = _seed(isolated_session, vertical)
    with isolated_session.begin() as session:
        session.delete(session.get(GoJourneyItemRow, ITEM_ID))
        order = session.get(model, ORDER_ID)
        canonical = journey_module.journey_service._default_snapshot(vertical, order)[3]
    supplied = {key: "CALLER_OVERRIDE" for key in canonical}
    supplied.update(amount_minor=1, currency="USD", traveler_note="Meet in lobby")
    item = {"vertical": vertical, "order_id": ORDER_ID, "facts": supplied, "title": "My custom title"}
    if entrypoint == "create":
        result = journey_module.journey_service.create(OWNER, {"title": "New trip", "items": [item]})
    else:
        result = journey_module.journey_service.attach(OWNER, JOURNEY_ID, item)
    observed = result["timeline"][0]
    assert observed["facts"]["amount_minor"] == 50000
    assert observed["facts"]["currency"] == "CNY"
    assert all(observed["facts"][key] == value for key, value in canonical.items())
    assert observed["facts"]["traveler_note"] == "Meet in lobby"
    assert observed["title"] == "My custom title"
    assert journey_module.journey_service.get(OWNER, result["journey_id"])["timeline"][0]["facts"] == observed["facts"]
    with isolated_session() as session:
        order = session.get(model, ORDER_ID)
        assert order.total_amount_minor == 50000 and order.currency == "CNY"
