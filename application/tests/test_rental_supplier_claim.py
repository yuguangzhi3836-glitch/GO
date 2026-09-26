"""Supplier statement authority stays distinct from adjudication and money."""
import pytest
from sqlalchemy import select
from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent, PaymentOrderFactBindingRow as Binding
from go_hotel.db.session import SessionLocal
from go_hotel.security.service import Principal
from go_hotel.mobility.rental.service import rental_service
from go_hotel.mobility.rental import damage
from go_hotel.api.routes.rental_operations import workspace
from tests.test_depth06_rental_settlement import paid, balances
from tests.test_rental_damage_disputes import ev, CHECKER


def supplier_order(client):
    owner,oid,_=paid(client)
    rental_service.fulfill(owner,oid,'PICKUP','isolated://pickup')
    rental_service.fulfill(owner,oid,'RETURN','isolated://return')
    with SessionLocal() as s:
        intent=s.scalar(select(Intent).where(Intent.business_id==oid))
        supplier=intent.payee_id
    actor=Principal('supplier-claimant','supplier-claimant','SUPPLIER_USER',supplier,[],'isolated',{'supplier:orders'})
    return owner,oid,actor


def test_bound_supplier_claim_consumer_dispute_independent_adjudication(client):
    owner,oid,actor=supplier_order(client)
    assert workspace(actor,oid)['actions']==['OPEN']
    before=balances()
    c=damage.open_case(actor,oid,'claim',10000,'CNY',ev('a'),ev('b'))
    assert c['supplier_evidence_status']=='SUPPLIER_STATEMENT_UNVERIFIED'
    assert damage.open_case(actor,oid,'claim',10000,'CNY',ev('a'),ev('b'))==c
    consumer=Principal(owner,owner,'CONSUMER',None,[],'isolated',set())
    damage.respond(consumer,oid,c['case_id'],'dispute',1,'DISPUTE',ev('c'))
    with pytest.raises(PermissionError):
        damage.adjudicate(actor,oid,c['case_id'],'self-review',2,10000,'supplier cannot judge',ev('d'))
    result=damage.adjudicate(CHECKER,oid,c['case_id'],'review',2,3000,'independent isolated review',ev('d'))
    assert result['awarded_minor']==3000 and workspace(actor,oid)['cases'][0]['actions']==[]
    assert balances()==before


@pytest.mark.parametrize('fault',['foreign_tenant','no_permission','broken_binding'])
def test_supplier_claim_requires_current_tenant_binding(client,fault):
    owner,oid,actor=supplier_order(client)
    if fault=='foreign_tenant':
        actor=Principal(actor.user_id,actor.user_id,actor.actor_type,'another-supplier',[],'isolated',actor.permissions)
    elif fault=='no_permission':
        actor=Principal(actor.user_id,actor.user_id,actor.actor_type,actor.supplier_id,[],'isolated',set())
    else:
        with SessionLocal.begin() as s:
            s.scalar(select(Binding).where(Binding.business_id==oid)).payee_id='another-supplier'
    before=balances()
    with pytest.raises((ValueError,PermissionError)):
        damage.open_case(actor,oid,'claim',10000,'CNY',ev('a'),ev('b'))
    with pytest.raises(ValueError):workspace(actor,oid)
    with SessionLocal() as s:assert damage._history(s,oid)==[]
    assert balances()==before
