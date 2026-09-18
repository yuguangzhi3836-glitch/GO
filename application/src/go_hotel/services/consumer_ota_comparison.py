from __future__ import annotations

import os
from urllib.parse import quote_plus

from sqlalchemy import select

from go_hotel.db.models import ProfileImportJobRow
from go_hotel.db.session import SessionLocal


class ConsumerOtaComparisonService:
    PROVIDERS={
        'CTRIP':('携程','GO_CTRIP_CONSUMER_DEEP_LINK'),
        'MEITUAN':('美团','GO_MEITUAN_CONSUMER_DEEP_LINK'),
        'FLIGGY':('飞猪','GO_FLIGGY_CONSUMER_DEEP_LINK'),
        'BOOKING':('Booking.com','GO_BOOKING_CONSUMER_DEEP_LINK'),
    }
    def options(self,user_id,search):
        with SessionLocal() as s:
            jobs=s.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user_id,ProfileImportJobRow.status=='COMPLETED')).all()
        linked={str(x.source_provider or '').upper() for x in jobs if (x.metadata_json or {}).get('connection_intent')}
        params={
            'city':search.get('city_code') or '', 'checkin':search.get('check_in') or '',
            'checkout':search.get('check_out') or '', 'hotel_id':search.get('hotel_id') or '',
            'adults':search.get('adults') or 1, 'rooms':search.get('rooms') or 1,
        }
        items=[]
        for provider,(label,env_name) in self.PROVIDERS.items():
            template=os.getenv(env_name);deep_link=None
            if template:
                deep_link=template
                for key,value in params.items():deep_link=deep_link.replace('{'+key+'}',quote_plus(str(value)))
            authorized=provider in linked
            items.append({'provider':provider,'label':label,'account_holder_authorized':authorized,'price_scope':'MEMBER_ACCOUNT' if authorized else 'PUBLIC_OR_LOGIN_REQUIRED','member_price_status':'AVAILABLE_FROM_OFFICIAL_ADAPTER' if authorized else 'VISIBLE_AFTER_PROVIDER_LOGIN','deep_link':deep_link,'login_session':'PROVIDER_APP','credentials_received_by_go':False,'price_disclosure':'FINAL_PRICE_MUST_BE_REVALIDATED_AT_PROVIDER'})
        return {'comparison_scope':'CURRENT_CONSUMER','offers_must_share_search_and_occupancy':True,'providers':items}


consumer_ota_comparison_service=ConsumerOtaComparisonService()
