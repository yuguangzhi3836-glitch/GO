"""C04 reduction authority; actual capture and compensation stay with C11."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement, JourneyRecoveryEvidenceChainRow as EvidenceRow
from go_hotel.mobility.rental import damage, deposit_authority as authority
from tests.test_rental_damage_disputes import order, OWNER, MAKER, CHECKER, principal, Order, ev

@pytest.fixture
def case(order):
    with SessionLocal.begin() as s:s.get(Order,order).status='CONFIRMED'
    p=authority.propose(OWNER,order,'propose');a=authority.accept(OWNER,order,p['obligation_id'],'accept',1,p['source_hash'],True)
    with SessionLocal.begin() as s:s.get(Order,order).status='COMPLETED'
    c=damage.open_case(MAKER,order,'case',10000,'CNY',ev('a'),ev('b'))
    damage.respond(OWNER,order,c['case_id'],'respond',1,'DISPUTE',ev('c'))
    damage.adjudicate(CHECKER,order,c['case_id'],'decide',2,8000,'Original reviewed liability',ev('d'))
    old=authority.decision_preview(CHECKER,order,a['obligation_id'],c['case_id'])
    return order,a,c['case_id'],old

def reduce(case,award=3000):
    oid,a,cid,old=case
    damage.appeal(OWNER,oid,cid,'appeal',3,'Further evidence',ev('e'))
    damage.review_appeal(principal('reviewer2'),oid,cid,'review',4,award,'Reduced liability',ev('f'))
    return authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)

@pytest.mark.parametrize('award',[3000,0])
def test_reduction_reproduces_old_hash_and_preserves_history(case,award):
    oid,a,cid,old=case;new=reduce(case,award)
    assert new['awarded_minor']==award and new['case_version']==5
    assert new['prior_decisions']==[{'case_version':3,'decision_hash':old['decision_hash'],'awarded_minor':8000,'reviewer_id':CHECKER.user_id}]
    assert new['authority_scope']=='REDUCE_ONLY' and new['financial_effect_asserted'] is False
    with SessionLocal.begin() as s:
        assert authority.resolve_compensation(s,oid,a['obligation_id'],cid,5,new['decision_hash'])==new
        assert s.scalar(select(func.count()).select_from(Movement))==0
        assert next(e['case'] for e in damage._history(s,oid) if e['case']['version']==3)['awarded_minor']==8000

@pytest.mark.parametrize('award',[8000,9000])
def test_no_initial_equal_or_upward_reduction_authority(case,award):
    oid,a,cid,old=case
    with pytest.raises(ValueError,match='APPEAL_REQUIRED'):authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)
    damage.appeal(OWNER,oid,cid,'appeal',3,'reason',ev('e'))
    damage.review_appeal(principal('reviewer2'),oid,cid,'review',4,award,'Reconsidered liability',ev('f'))
    with pytest.raises(ValueError,match='REDUCTION_REQUIRED'):authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)

def test_new_appeal_invalidates_prior_compensation_version(case):
    oid,a,cid,_=case;new=reduce(case)
    damage.appeal(OWNER,oid,cid,'appeal2',5,'Further review',ev('a'))
    with SessionLocal.begin() as s,pytest.raises(ValueError,match='DECISION_HELD'):
        authority.resolve_compensation(s,oid,a['obligation_id'],cid,5,new['decision_hash'])
    damage.review_appeal(principal('reviewer3'),oid,cid,'review2',6,1000,'Second reduction',ev('b'))
    with SessionLocal.begin() as s,pytest.raises(ValueError,match='VERSION_CONFLICT'):
        authority.resolve_compensation(s,oid,a['obligation_id'],cid,5,new['decision_hash'])
    latest=authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)
    assert latest['case_version']==7 and [x['awarded_minor'] for x in latest['prior_decisions']]==[8000,3000]
    assert latest['prior_decisions'][1]['decision_hash']==new['decision_hash']

def test_preview_permissions_and_conflicting_review_replay(case):
    oid,a,cid,_=case;new=reduce(case)
    with pytest.raises(PermissionError):authority.compensation_preview(OWNER,oid,a['obligation_id'],cid)
    with pytest.raises(PermissionError):authority.compensation_preview(principal('readonly',permissions={'admin:read'}),oid,a['obligation_id'],cid)
    with pytest.raises(ValueError,match='IDEMPOTENCY_CONFLICT'):
        damage.review_appeal(principal('reviewer2'),oid,cid,'review',4,2000,'Reduced liability',ev('f'))
    assert authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)==new

def test_competing_reductions_have_one_current_authority(case):
    oid,a,cid,_=case;damage.appeal(OWNER,oid,cid,'appeal',3,'reason',ev('e'))
    def decide(uid):
        try:
            damage.review_appeal(principal(uid),oid,cid,'review',4,3000,uid,ev('f'));return 'PASS'
        except ValueError as e:
            assert 'VERSION_CONFLICT' in str(e);return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(decide,['reviewer2','reviewer3']))==['CONFLICT','PASS']
    fact=authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)
    assert len(fact['prior_decisions'])==1 and fact['reviewer_id'] in {'reviewer2','reviewer3'}

def test_semantic_history_rewrite_rejected(case):
    oid,a,cid,_=case;reduce(case)
    from go_hotel.services.rc20_vertical_evidence import _stable_hash
    with SessionLocal.begin() as s:
        rows=list(s.scalars(select(EvidenceRow).where(EvidenceRow.execution_id==f'rc20:RENTAL:{oid}').order_by(EvidenceRow.sequence_no)));previous='GENESIS'
        for row in rows:
            body=deepcopy(row.evidence_json)
            if body['kind']=='DAMAGE_CASE_EVENT' and body['payload']['case']['version']==3:body['payload']['case']['awarded_minor']=7000
            body['previous_hash']=previous;row.previous_hash=previous;row.evidence_json=body;row.evidence_hash=_stable_hash(body)
            row.entry_hash=_stable_hash({'evidence_hash':row.evidence_hash,'previous_hash':previous,'sequence_no':row.sequence_no});previous=row.entry_hash
    with pytest.raises(ValueError,match='LINEAGE_INVALID'):authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)


def test_historical_compensation_authority_survives_later_pending_and_upward_review(case):
    oid,a,cid,_=case;reduced=reduce(case)
    with SessionLocal.begin() as s:
        assert authority.resolve_compensation_history(s,oid,a['obligation_id'])==[reduced]
    damage.appeal(OWNER,oid,cid,'appeal2',5,'Reopen review',ev('a'))
    with SessionLocal.begin() as s:
        assert authority.resolve_compensation_history(s,oid,a['obligation_id'])==[reduced]
    with SessionLocal.begin() as s,pytest.raises(ValueError,match='DECISION_HELD'):
        authority.resolve_compensation(s,oid,a['obligation_id'],cid,5,reduced['decision_hash'])
    damage.review_appeal(principal('reviewer3'),oid,cid,'review2',6,5000,'Upward reconsideration',ev('b'))
    current=authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)
    # Current 5000 remains below the original 8000 decision. C11 separately
    # refuses any target above the actual post-refund net captured amount.
    assert current['awarded_minor']==5000 and current['case_version']==7
    with SessionLocal.begin() as s:
        assert authority.resolve_compensation_history(s,oid,a['obligation_id'])==[reduced,current]


def test_multiple_historical_reductions_preserve_exact_current_hash_at_each_revision(case):
    oid,a,cid,_=case;first=reduce(case)
    damage.appeal(OWNER,oid,cid,'appeal2',5,'More evidence',ev('a'))
    damage.review_appeal(principal('reviewer3'),oid,cid,'review2',6,0,'No liability',ev('b'))
    second=authority.compensation_preview(CHECKER,oid,a['obligation_id'],cid)
    with SessionLocal.begin() as s:
        assert authority.resolve_compensation_history(s,oid,a['obligation_id'])==[first,second]
        assert s.scalar(select(func.count()).select_from(Movement))==0
