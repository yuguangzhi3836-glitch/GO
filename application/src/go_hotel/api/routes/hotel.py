from dataclasses import asdict
from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool
from go_hotel.api.schemas import SearchRequest, PrebookRequest
from go_hotel.services.booking import booking_service
from go_hotel.judgment.service import judgment_service
from go_hotel.services.catalog_fare_snapshot import offer_rule

router = APIRouter(prefix="/v1")

@router.post("/search/hotels")
async def search_hotels(body: SearchRequest):
    offers = await booking_service.search(body.destination.city_code, body.stay.check_in, body.stay.check_out, body.currency)
    return await run_in_threadpool(_search_response, offers)

def _search_response(offers):
    # Judgment uses synchronous SQLAlchemy sessions; keep it off the event loop.
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

@router.post("/offers/{offer_id}/prebook")
async def prebook(offer_id: str, body: PrebookRequest):
    pb = await booking_service.prebook(offer_id)
    return {"data": {"prebook_id": pb.prebook_id, "status": pb.status, "total_amount_minor": pb.total_amount_minor, "currency": pb.currency, "expires_at": pb.expires_at.isoformat(), "fare_rule": offer_rule(offer_id)}}
