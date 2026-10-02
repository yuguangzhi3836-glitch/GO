import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import PaymentOrderFactBindingRow as Binding,VerticalSourceDecisionRow as Decision
from go_hotel.mobility.rental import damage
from tests.test_rental_supplier_claim import supplier_order
from tests.test_ticket_operations_runtime import login
from test_completed_ledger import money_snapshot

BODY={'amount_minor':10000,'currency':'CNY','pickup_statement':'Independent pickup observation','return_statement':'Independent return observation'}

@pytest.mark.parametrize('fault',['foreign_tenant','readonly','binding_payee','binding_currency','source_tenant'])
def test_supplier_http_claim_rejects_bad_authority_without_effect(client,fault):
    owner,oid,actor=supplier_order(client)
    headers=login('READ_ONLY' if fault=='readonly' else 'SUPPLIER_OWNER','foreign-supplier' if fault=='foreign_tenant' else actor.supplier_id)
    if fault.startswith('binding_') or fault=='source_tenant':
        with SessionLocal.begin() as s:
            binding=s.scalar(select(Binding).where(Binding.business_id==oid))
            if fault=='binding_payee':binding.payee_id='foreign-supplier'
            elif fault=='binding_currency':binding.currency='USD'
            else:s.get(Decision,binding.source_decision_id).selected_source_id='foreign-supplier'
    before=money_snapshot()
    response=client.post(f'/v1/supplier/mobility/rentals/orders/{oid}/operations/cases',headers={**headers,'Idempotency-Key':'independent-claim'},json=BODY)
    assert response.status_code in [403,404],response.text
    assert client.get(f'/v1/mobility/rentals/orders/{oid}/operations',headers=headers).status_code in [403,404]
    with SessionLocal() as s:assert damage._history(s,oid)==[]
    assert money_snapshot()==before


def test_supplier_http_can_claim_only_not_adjudicate_or_expand_default_order_access(client):
    owner,oid,actor=supplier_order(client);headers=login('SUPPLIER_OWNER',actor.supplier_id)
    before=money_snapshot()
    response=client.post(f'/v1/supplier/mobility/rentals/orders/{oid}/operations/cases',headers={**headers,'Idempotency-Key':'independent-claim'},json=BODY)
    assert response.status_code==200,response.text
    case=response.json()['data'];cid=case['case_id']
    assert case['supplier_evidence_status']=='SUPPLIER_STATEMENT_UNVERIFIED'
    replay=client.post(f'/v1/supplier/mobility/rentals/orders/{oid}/operations/cases',headers={**headers,'Idempotency-Key':'independent-claim'},json=BODY)
    assert replay.json()==response.json()
    response=client.post(f'/internal/v1/admin/mobility/rentals/orders/{oid}/operations/cases/{cid}/decision',headers={**headers,'Idempotency-Key':'review'},json={'expected_version':1,'award_minor':10000,'statement':'Self adjudication forbidden'})
    assert response.status_code==403,response.text
    with SessionLocal() as s:
        assert len(damage._history(s,oid))==1
        with pytest.raises(ValueError,match='MOBILITY_ORDER_NOT_FOUND'):damage._order(s,actor,oid)
    assert money_snapshot()==before
