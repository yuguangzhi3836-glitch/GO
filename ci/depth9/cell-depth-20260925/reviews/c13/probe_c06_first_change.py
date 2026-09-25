from test_depth21_refund_recovery import booked


def test_prechange_reconciliation_cannot_resolve_first_change():
    svc, owner, oid = booked('ATTRACTION')
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://old-unknown', 'ops')
    svc.admin_external_state(oid, 'CONFIRMED', 'isolated://old-confirm', 'ops', 'OLD-SUP', 'OLD-VOUCHER')
    quote = svc.change_quote(owner, oid, '2026-09-17')
    svc.execute_change(owner, oid, quote['quote_id'])
    before = svc.get(owner, oid)
    try:
        svc.admin_external_state(oid, 'CONFIRMED', 'isolated://old-confirm', 'ops', 'OLD-SUP', 'OLD-VOUCHER')
    except ValueError:
        assert svc.get(owner, oid) == before
        return
    raise AssertionError('old unbound reconciliation confirmed first change')
