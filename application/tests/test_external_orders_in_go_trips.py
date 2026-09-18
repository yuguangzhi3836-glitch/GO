import pytest
from concurrent.futures import ThreadPoolExecutor

from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc


def official(account='external-trip-official', event='evt-1', at='2026-09-18T10:00:00Z', adapter_id='booking-orders-v1', **overrides):
    body = {'provider':'BOOKING','external_order_id':'B-99','vertical':'HOTEL','title':'Tokyo Hotel','lifecycle_state':'CONFIRMED','payment_state':'PAID','refund_state':'NOT_REQUESTED','source_event_id':event,'source_updated_at':at,'evidence_reference':f'booking-adapter://event/{event}','servicing_deep_link':'booking://orders/B-99','change_allowed':True,'cancel_allowed':True}
    body.update(overrides)
    return svc.import_external_order(account,body,trusted_provider=True,adapter_id=adapter_id)


def test_user_import_is_untrusted_idempotent_and_does_not_expose_submitted_link():
    user='external-trip-user';body={'provider':'CTRIP','external_order_id':'C-1001','vertical':'HOTEL','title':'上海酒店','lifecycle_state':'CONFIRMED','payment_state':'PAID','change_allowed':True,'cancel_allowed':True,'servicing_deep_link':'ctrip://orders/C-1001'}
    first=svc.import_external_order(user,body);again=svc.import_external_order(user,body)
    assert first['account_id']==user
    assert first['lifecycle_state']=='MANUAL_REVIEW'
    assert first['payment_state']==first['refund_state']=='UNKNOWN_EXTERNAL_STATE'
    assert first['change_allowed'] is first['cancel_allowed'] is False
    assert first['facts_json']['servicing_deep_link'] is None
    assert first['facts_json']['fulfillment_owner']=='CTRIP'
    assert first['facts_json']['go_role']=='AGGREGATION_AND_NAVIGATION'
    assert again['consumer_unified_lifecycle_id']==first['consumer_unified_lifecycle_id'] and again['stale_ignored'] is True
    assert len(svc.detail(user,first['consumer_unified_lifecycle_id'])['events'])==1


def test_official_adapter_updates_lifecycle_and_provider_owned_actions():
    first=official();updated=official(event='evt-2',at='2026-09-18T11:00:00Z',lifecycle_state='CANCELLED',payment_state='REFUNDED',refund_state='REFUND_COMPLETED',change_allowed=False,cancel_allowed=False)
    assert first['lifecycle_state']=='CONFIRMED'
    assert updated['lifecycle_state']=='CANCELLED' and updated['refund_state']=='REFUND_COMPLETED'
    assert updated['facts_json']['source_verification']=='OFFICIAL_PROVIDER'
    assert updated['facts_json']['fulfillment_owner']=='BOOKING'
    assert updated['facts_json']['service_actions']['refund_or_cancel']['owner']=='BOOKING'
    assert len(svc.detail(updated['account_id'],updated['consumer_unified_lifecycle_id'])['events'])==2


def test_official_event_replay_and_out_of_order_update_are_idempotent():
    current=official(account='external-trip-replay',event='evt-current',at='2026-09-18T12:00:00Z')
    official(account='external-trip-replay',event='evt-next',at='2026-09-18T12:01:00Z',lifecycle_state='IN_PROGRESS')
    replay=official(account='external-trip-replay',event='evt-current',at='2026-09-18T12:02:00Z',lifecycle_state='FAILED')
    old=official(account='external-trip-replay',event='evt-old',at='2026-09-18T11:59:59Z',lifecycle_state='FAILED')
    assert replay['stale_ignored'] is old['stale_ignored'] is True
    assert replay['lifecycle_state']==old['lifecycle_state']=='IN_PROGRESS'
    assert len(svc.detail(current['account_id'],current['consumer_unified_lifecycle_id'])['events'])==2


def test_adapter_identity_evidence_and_deep_links_fail_closed():
    with pytest.raises(ValueError,match='TRUSTED_OTA_ADAPTER_REQUIRED'):official(account='external-trip-wrong-adapter',adapter_id='ctrip-orders-v1')
    with pytest.raises(ValueError,match='COMPLETE_OTA_EVENT_EVIDENCE_REQUIRED'):official(account='external-trip-no-event',source_event_id='')
    with pytest.raises(ValueError,match='INVALID_EXTERNAL_SERVICE_LINK'):official(account='external-trip-link',servicing_deep_link='javascript:alert(1)')


def test_same_provider_order_identifier_is_isolated_between_accounts():
    left=svc.import_external_order('account-left',{'provider':'CTRIP','external_order_id':'shared-id','vertical':'HOTEL'})
    right=svc.import_external_order('account-right',{'provider':'CTRIP','external_order_id':'shared-id','vertical':'HOTEL'})
    assert left['order_id']!=right['order_id']
    assert len(svc.list('account-left'))==len(svc.list('account-right'))==1
    with pytest.raises(ValueError,match='NOT_FOUND'):svc.detail('account-right',left['consumer_unified_lifecycle_id'])


def test_concurrent_user_import_has_one_trip_and_one_event():
    body={'provider':'CTRIP','external_order_id':'concurrent-shared-id','vertical':'HOTEL'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=[future.result() for future in [pool.submit(svc.import_external_order,'concurrent-account',body) for _ in range(4)]]
    assert len({item['consumer_unified_lifecycle_id'] for item in results})==1
    item=results[0]
    assert len(svc.detail('concurrent-account',item['consumer_unified_lifecycle_id'])['events'])==1
