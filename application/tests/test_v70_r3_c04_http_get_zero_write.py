"""C04-05: real HTTP GET remains read-only on the configured database."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from go_hotel.api.routes import operations_console as ops
from go_hotel.db.models import MobilityRefundRow as Refund
from go_hotel.db.session import SessionLocal, engine
from go_hotel.main import app
from go_hotel.security.deps import admin_principal
from tests.test_depth33_mobility_refund_consent import booked


def test_admin_reconciliation_http_get_is_zero_write():
    service, owner, order_id = booked("RENTAL")
    quote = service.refund_quote(owner, order_id)
    completed = service.cancel(owner, order_id, quote["quote_hash"])
    refund_id = completed["refund_id"]
    with SessionLocal.begin() as session:
        refund = session.scalar(select(Refund).where(Refund.refund_id == refund_id))
        refund.status = "REFUND_COMPLETED"
        session.get(ops.MobilityRentalOrderRow, order_id).status = "CONFIRMED"
    before = service.get(owner, order_id)
    statements = []

    def select_only(connection, cursor, statement, parameters, context, executemany):
        verb = statement.lstrip().split()[0].upper()
        statements.append(verb)
        assert verb == "SELECT", statement

    app.dependency_overrides[admin_principal] = lambda: SimpleNamespace(user_id="c04-http-admin")
    try:
        with TestClient(app) as client:
            event.listen(engine, "before_cursor_execute", select_only)
            try:
                response = client.get(
                    f"/internal/v1/admin/operations/reconciliations/rental/{order_id}/{refund_id}"
                )
            finally:
                event.remove(engine, "before_cursor_execute", select_only)
    finally:
        app.dependency_overrides.pop(admin_principal, None)

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["presentation"]["case"]["read_only"] is True
    assert payload["presentation"]["automatic_repair"] is False
    assert statements and set(statements) == {"SELECT"}
    assert service.get(owner, order_id) == before
