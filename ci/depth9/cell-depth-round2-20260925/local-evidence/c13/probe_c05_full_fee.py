from test_c05_cancellation_policy import BODY, confirm, svc
from ride_cancellation_fixture import synthetic_policy, accepted_body

def test_fully_retained_fee_can_finish_cancellation_without_zero_money_movement():
    with synthetic_policy(before=16800, after=16800):
        oid = confirm(svc.create('owner', accepted_body(svc, BODY)))
    quote = svc.refund_quote('owner', oid)
    assert quote['refund_amount_minor'] == 0
    result = svc.cancel('owner', oid, quote['quote_hash'])
    assert result['refund_amount_minor'] == 0
