"""Money truth and work bounds when one payment has many durable movements."""
from types import SimpleNamespace as Row
import pytest
from go_hotel.services.order_supplier_fulfillment import _payment_state

UNKNOWN='UNKNOWN_EXTERNAL_STATE'
pytestmark=pytest.mark.no_db


class CountedRows(list):
    visits=0
    def __iter__(self):
        for row in super().__iter__():
            self.visits+=1
            yield row


def movement(key,kind,amount,parent=None,**changes):
    return Row(**(dict(money_movement_id=key,movement_type=kind,amount_minor=amount,
        parent_movement_id=parent,state='CONFIRMED',business_type='RIDE_ORDER',
        business_id='order',currency='CNY')|changes))


def evaluate(rows,amount):
    facts=dict(business_type='RIDE_ORDER',business_id='order',payer_id='payer',
               payee_id='supplier',amount_minor=amount,currency='CNY')
    intent=Row(**facts,payment_intent_id='intent',state='SUCCEEDED')
    binding=Row(**facts,legal_entity_id='entity')
    root=Row(business_type='RIDE_ORDER',business_id='order',legal_entity_id='entity')
    class Session:
        def execute(self,*a,**k):return Row(one_or_none=lambda:(intent,root,binding))
        def scalars(self,*a,**k):return Row(all=lambda:rows)
    fulfillment=Row(business_type='RIDE_ORDER',business_id='order',payment_intent_id='intent',supplier_id='supplier')
    order=Row(account_id='payer',total_amount_minor=amount,currency='CNY')
    return _payment_state(Session(),fulfillment,order)


def split_graph(count):
    return CountedRows(row for n in range(count) for row in
        (movement(f'a{n}','AUTHORIZATION',100),movement(f'c{n}','CAPTURE',100,f'a{n}')))


@pytest.mark.parametrize('kind',['REFUND','COMPENSATION'])
@pytest.mark.parametrize('amount,expected',[(0,'PAID'),(50,'PARTIALLY_REFUNDED'),(100,'REFUNDED')])
def test_valid_payment_states(kind,amount,expected):
    rows=split_graph(1)
    if amount:rows.append(movement('r',kind,amount,'c0'))
    assert evaluate(rows,100)==expected


def test_combined_refund_and_compensation_share_parent_budget():
    rows=split_graph(2)
    rows.extend([movement('r','REFUND',60,'c0'),movement('x','COMPENSATION',41,'c0')])
    assert evaluate(rows,200)==UNKNOWN
    rows[-1].amount_minor=40
    assert evaluate(rows,200)=='PARTIALLY_REFUNDED'


def test_parent_capture_overdraw_cannot_hide_in_other_authorization():
    rows=split_graph(2)
    rows[1].amount_minor=101;rows[3].amount_minor=99
    assert evaluate(rows,200)==UNKNOWN


def test_release_and_capture_share_authorization_budget():
    rows=split_graph(2)
    rows.append(movement('release','RELEASE',1,'a0'))
    assert evaluate(rows,200)==UNKNOWN


@pytest.mark.parametrize('changes',[
    {'parent_movement_id':'missing'}, {'parent_movement_id':'c0'},
    {'movement_type':'INVALID'}, {'state':'UNKNOWN_EXTERNAL_STATE'},
    {'currency':'USD'}, {'business_id':'another-order'}, {'business_type':'RAIL_ORDER'},
    {'amount_minor':0}, {'amount_minor':-1}, {'amount_minor':True}, {'amount_minor':1.0},
])
def test_invalid_edges_and_facts_remain_unknown(changes):
    rows=split_graph(1);rows[1].__dict__.update(changes)
    assert evaluate(rows,100)==UNKNOWN


def test_authorization_cannot_have_parent():
    rows=split_graph(1);rows[0].parent_movement_id='c0'
    assert evaluate(rows,100)==UNKNOWN


def test_payout_remains_independent_of_refund_total():
    rows=split_graph(1);rows.append(movement('pay','PAYOUT',100,'c0'))
    assert evaluate(rows,100)=='PAID'


def test_row_order_does_not_change_parent_binding():
    rows=split_graph(20)
    assert evaluate(CountedRows(reversed(rows)),2000)=='PAID'


def test_history_work_is_bounded_linearly(record_property):
    visits=[]
    for parents in (100,1000,2000):
        rows=split_graph(parents)
        assert evaluate(rows,parents*100)=='PAID'
        assert rows.visits<=12*len(rows), (len(rows),rows.visits)
        visits.append((len(rows),rows.visits))
    assert visits[2][1]<=2*visits[1][1]
    record_property('row_visits',repr(visits))
    record_property('scope','In-memory bound graph validation, not full transaction CPU or latency')
