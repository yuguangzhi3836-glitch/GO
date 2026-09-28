from datetime import datetime, timezone, timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HotelRegistrationDirectRow
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc

def prop(sid='owner'):
    return svc.create_property(sid,'actor',{'name_zh':'Hotel','property_type':'HOTEL'})['property_id']

def reg(sid,pid,hotel,rid,delta=0):
    with SessionLocal.begin() as s:
        s.add(HotelRegistrationDirectRow(hotel_registration_direct_id=rid,hotel_id=hotel,supplier_id=sid,state='SUBMITTED',evidence_json=[],official_supplement_json={'property_id':pid} if pid else {},requested_by='actor',created_at=datetime.now(timezone.utc)+timedelta(seconds=delta)))

def test_multiple_properties_require_selection():
    prop();prop()
    with pytest.raises(ValueError,match='PROPERTY_SELECTION_REQUIRED'):svc.webpage_workspace('owner')

def test_explicit_property_does_not_receive_latest_other_hotel():
    a=prop();b=prop();reg('owner',a,'canonical-a','ra');reg('owner',b,'canonical-b','rb',10)
    assert svc.webpage_workspace('owner',a)['hotel_id']=='canonical-a'
    assert svc.webpage_workspace('owner',b)['hotel_id']=='canonical-b'

def test_unbound_property_does_not_guess_registration():
    a=prop();reg('owner',None,'legacy-hotel','legacy')
    result=svc.webpage_workspace('owner',a)
    assert result['mapped'] is False and 'hotel_id' not in result
    assert result['property']['property_id']==a

def test_foreign_property_and_registration_are_not_visible():
    a=prop();b=prop('other');reg('other',a,'wrong-hotel','wrong')
    assert svc.webpage_workspace('owner',a)['mapped'] is False
    with pytest.raises(ValueError,match='PROPERTY_NOT_FOUND'):svc.webpage_workspace('owner',b)
