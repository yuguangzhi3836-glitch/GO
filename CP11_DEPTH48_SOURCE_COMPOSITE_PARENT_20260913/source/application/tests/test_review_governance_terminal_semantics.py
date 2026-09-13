import csv
from pathlib import Path

MATRIX = Path(__file__).resolve().parents[1] / 'specs' / 'state_machine_matrix.csv'


def review_rows():
    with MATRIX.open(newline='', encoding='utf-8') as f:
        return [r for r in csv.DictReader(f) if r['machine'] == 'REVIEW']


def test_review_completion_is_submission_final_but_governance_nonterminal():
    rows = review_rows()
    completed = [r for r in rows if r['event'] == 'REVIEW_COMPLETED']
    assert len(completed) == 2
    assert all(r['to_state'] == 'COMPLETED' for r in completed)
    assert all(r['terminal'].lower() == 'false' for r in completed)
    assert all('immutable' in r['notes'].lower() for r in completed)


def test_completed_review_governance_chain_remains_reachable():
    rows = review_rows()
    edge = {(r['from_state'], r['event']): r for r in rows}
    assert edge[('COMPLETED', 'REVIEW_DISPUTED')]['to_state'] == 'DISPUTED'
    assert edge[('DISPUTED', 'REVIEW_FROZEN')]['to_state'] == 'FROZEN'
    assert edge[('FROZEN', 'REVIEW_REINSTATED')]['to_state'] == 'COMPLETED'
    assert edge[('FROZEN', 'REVIEW_INVALIDATED')]['to_state'] == 'INVALIDATED'


def test_completed_review_stays_submission_immutable_after_governance_state_change(client):
    from datetime import datetime, timezone, timedelta
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import ReviewSessionRow

    ci=(datetime.now(timezone.utc)+timedelta(days=20)).date().isoformat()
    co=(datetime.now(timezone.utc)+timedelta(days=22)).date().isoformat()
    s=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':ci,'check_out':co},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'})
    off=s.json()['data']['hotels'][0]['best_offer']
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/orders',headers={'Idempotency-Key':'ord-review-gov'},json={'prebook_id':pb['prebook_id'],'account_id':'acct_demo'}).json()['data']
    client.post(f"/v1/orders/{o['order_id']}/payments",headers={'Idempotency-Key':'pay-review-gov'},json={'payment_method_token':'pm_success','amount_minor':o['total_amount_minor'],'currency':'CNY'})
    assert client.post(f"/internal/v1/orders/{o['order_id']}/confirm").status_code==200
    rid=client.post(f"/internal/v1/orders/{o['order_id']}/reviews/eligibility",json={'verified_stay':True}).json()['data']['review_id']
    done=client.post(f'/v1/reviews/{rid}/star',json={'star':5})
    assert done.status_code==200 and done.json()['data']['status']=='COMPLETED'

    with SessionLocal.begin() as db:
        row=db.get(ReviewSessionRow,rid)
        assert row.completed_at is not None
        row.status='DISPUTED'

    for path,payload in [
        (f'/v1/reviews/{rid}/star', {'star':4}),
        (f'/v1/reviews/{rid}/tags', {'tags':['GREAT_SERVICE']}),
        (f'/v1/reviews/{rid}/content', {'text':'mutate after dispute','photo_refs':[]}),
    ]:
        resp=client.post(path,json=payload)
        assert resp.status_code==409
        assert resp.json()['detail']['code']=='REVIEW_ALREADY_COMPLETED'
