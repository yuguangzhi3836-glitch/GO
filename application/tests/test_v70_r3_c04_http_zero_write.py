"""C04-05: the real authenticated HTTP GET path is zero-write on PostgreSQL."""

from sqlalchemy import event, select

from go_hotel.db.models import AuthSessionRow, MobilityRefundRow as Refund
from go_hotel.db.session import SessionLocal, engine
from go_hotel.security.crypto import decode_jwt
from go_hotel.security.service import identity_service
from go_hotel.api.routes import operations_console as ops
from tests.test_depth33_mobility_refund_consent import booked


def test_admin_reconciliation_http_get_is_zero_write_with_real_auth(client):
    service, owner, order_id = booked('RENTAL')
    quote = service.refund_quote(owner, order_id)
    completed = service.cancel(owner, order_id, quote['quote_hash'])
    refund_id = completed['refund_id']

    with SessionLocal.begin() as session:
        refund = session.scalar(select(Refund).where(Refund.refund_id == refund_id))
        refund.status = 'REFUND_COMPLETED'
        order = session.get(ops.MobilityRentalOrderRow, order_id)
        order.status = 'CONFIRMED'

    before = service.get(owner, order_id)
    token = identity_service.login('go_admin', 'change-me-admin')['access_token']
    session_id = decode_jwt(token)['sid']
    with SessionLocal() as session:
        last_seen_before = session.get(AuthSessionRow, session_id).last_seen_at

    statements = []

    def read_only(connection, cursor, statement, parameters, context, executemany):
        verb = statement.lstrip().split()[0].upper()
        statements.append(verb)
        assert verb == 'SELECT', statement

    event.listen(engine, 'before_cursor_execute', read_only)
    try:
        response = client.get(
            f'/internal/v1/admin/operations/reconciliations/rental/{order_id}/{refund_id}',
            headers={
                'Authorization': 'Bearer ' + token,
                'X-GO-Actor': 'GO_ADMIN',
            },
        )
    finally:
        event.remove(engine, 'before_cursor_execute', read_only)

    assert response.status_code == 200, response.text
    payload = response.json()['data']
    assert payload['diagnosis']['status'] == 'CONTRADICTION'
    assert payload['diagnosis']['read_only'] is True
    assert payload['presentation']['automatic_repair'] is False
    assert statements and set(statements) == {'SELECT'}
    assert service.get(owner, order_id) == before

    with SessionLocal() as session:
        assert session.get(AuthSessionRow, session_id).last_seen_at == last_seen_before
