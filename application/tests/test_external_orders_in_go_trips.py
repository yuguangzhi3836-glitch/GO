from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc


def test_user_imported_ota_order_enters_go_trips_as_pending_verification():
    user='external-trip-user'
    item=svc.import_external_order(user,{'provider':'CTRIP','external_order_id':'C-1001','vertical':'HOTEL','title':'上海酒店','lifecycle_state':'CONFIRMED','payment_state':'PAID','servicing_deep_link':'ctrip://orders/C-1001'})
    assert item['account_id']==user
    assert item['lifecycle_state']=='MANUAL_REVIEW'
    assert item['payment_state']=='UNKNOWN_EXTERNAL_STATE'
    assert item['facts_json']['transaction_platform']=='CTRIP'
    assert item['facts_json']['imported_to_go_trips'] is True
    assert len(svc.list(user))==1


def test_official_provider_projection_preserves_real_external_order_state():
    item=svc.import_external_order('external-trip-official',{'provider':'BOOKING','external_order_id':'B-99','vertical':'HOTEL','title':'Tokyo Hotel','lifecycle_state':'CONFIRMED','payment_state':'PAID','refund_state':'NOT_REQUESTED','evidence_reference':'booking-adapter://event/1'},trusted_provider=True)
    assert item['lifecycle_state']=='CONFIRMED'
    assert item['payment_state']=='PAID'
    assert item['facts_json']['source_verification']=='OFFICIAL_PROVIDER'
    assert item['facts_json']['fulfillment_owner']=='BOOKING'
