from dataclasses import asdict
from fastapi import APIRouter, Depends
from go_hotel.api.schemas import SearchRequest, PrebookRequest
from go_hotel.services.booking import booking_service
from go_hotel.judgment.service import judgment_service
from go_hotel.services.catalog_fare_snapshot import offer_rule
from go_hotel.security.deps import consumer_principal
from go_hotel.security.service import Principal
from go_hotel.services.consumer_ota_comparison import consumer_ota_comparison_service

router = APIRouter(prefix="/v1")

@router.post("/search/hotels")
async def search_hotels(body: SearchRequest):
    offers = await booking_service.search(body.destination.city_code, body.stay.check_in, body.stay.check_out, body.currency)
    hotels=[]
    for o in offers:
        judgment=judgment_service.public_summary_or_default(o.hotel_id)
        hotels.append({
            "hotel_id":o.hotel_id,
            "name":"Conrad Tokyo",
            "go_score":judgment["go_score"],
            "guest_experience_score":4.5,
            "recommendation_status":judgment["recommendation_status"],
            "judgment_id":judgment["judgment_id"],
            "best_offer":{"offer_id":o.offer_id,"total_amount_minor":o.total_amount_minor,"currency":o.currency,"official_direct":o.official_direct}
        })
    return {"data":{"hotels":hotels}}

@router.post('/search/hotels/member-context')
async def member_context_search(body:SearchRequest,p:Principal=Depends(consumer_principal)):
    offers=await booking_service.search(body.destination.city_code,body.stay.check_in,body.stay.check_out,body.currency)
    search={'city_code':body.destination.city_code,'check_in':body.stay.check_in,'check_out':body.stay.check_out}
    ota=consumer_ota_comparison_service.options(p.user_id,search)
    direct=[{'offer_id':x.offer_id,'hotel_id':x.hotel_id,'total_amount_minor':x.total_amount_minor,'currency':x.currency,'price_scope':'GO_BOOKABLE','official_direct':x.official_direct} for x in offers]
    return {'data':{'comparison_scope':'CURRENT_CONSUMER','go_offers':direct,'ota_options':ota['providers'],'rule':'COMPARE_SAME_DATES_OCCUPANCY_CURRENCY_AND_FINAL_TAXES'}}

@router.post("/offers/{offer_id}/prebook")
async def prebook(offer_id: str, body: PrebookRequest):
    pb = await booking_service.prebook(offer_id)
    return {"data": {"prebook_id": pb.prebook_id, "status": pb.status, "total_amount_minor": pb.total_amount_minor, "currency": pb.currency, "expires_at": pb.expires_at.isoformat(), "fare_rule": offer_rule(offer_id)}}
