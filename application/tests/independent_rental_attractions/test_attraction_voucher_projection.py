"""Real-auth cross-surface terminal voucher regression; preserve stored history."""
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AttractionOrderRow
from go_hotel.core.config import settings
from tests.test_ticket_operations_runtime import login
from test_attraction_independent import booked


def test_refunded_voucher_hidden_consistently_without_erasing_history(client,monkeypatch):
    monkeypatch.setattr(settings,'mfa_required_for_admin',False)
    consumer,oid=booked(client);admin=login('GO_ORDER_OPS')
    with SessionLocal() as s:
        row=s.get(AttractionOrderRow,oid);original=(row.voucher_code,row.supplier_reference)
        assert original[0] and original[1]
    closed=client.post(f'/internal/v1/admin/attractions/orders/{oid}/external-state',headers=admin,json={'state':'CLOSED_BY_SUPPLIER','evidence_reference':'isolated://projection-closure'})
    assert closed.status_code==200,closed.text
    quote=client.get(f'/v1/attractions/orders/{oid}/refund-quote',headers=consumer).json()['data']
    refunded=client.post(f'/v1/attractions/orders/{oid}/refund-confirmed',headers={**consumer,'Idempotency-Key':'independent-voucher-refund'},json={'quote_hash':quote['quote_hash'],'confirmed':True})
    assert refunded.status_code==200,refunded.text
    current=client.get(f'/v1/attractions/orders/{oid}',headers=consumer);assert current.status_code==200,current.text
    listing=client.get('/internal/v1/admin/operations/verticals/ATTRACTION',params={'order_id':oid},headers=admin);assert listing.status_code==200,listing.text
    workspace=client.get(f'/internal/v1/admin/ticket-operations/ATTRACTION/{oid}',headers=admin);assert workspace.status_code==200,workspace.text
    assert [r['order_id'] for r in listing.json()['data']['orders']]==[oid]
    for item in [current.json()['data'],listing.json()['data']['orders'][0],workspace.json()['data']['order']]:
        assert item['status']=='REFUNDED'
        assert item['voucher_code'] is None
        if 'supplier_reference' in item:assert item['supplier_reference'] is None
    assert current.json()['data']['can_redeem'] is False
    with SessionLocal() as s:
        row=s.get(AttractionOrderRow,oid);assert (row.voucher_code,row.supplier_reference)==original
    assert any(e['kind']=='SUPPLIER_CONFIRMED' for e in current.json()['data']['evidence'])
