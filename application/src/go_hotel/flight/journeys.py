"""Reference revision: explicit, simulated single/return/multi-city journeys.

Each selected leg is priced by the server. This is an independent-ticket
composition, never represented as an airline through fare or protected connection.
Same-day combinations, child/infant mixes, and partial aftersales remain unsupported.
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.db.models import FlightOfferRow
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import new_id
from go_hotel.flight.service import flight_service, now
from go_hotel.flight.airports import resolve_airport


TripType = Literal["ONE_WAY", "ROUND_TRIP", "MULTI_CITY"]


class Leg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    departure_date: date

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def normalize_airport(cls, value):
        return resolve_airport(value)['iata'] if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_leg(self):
        if self.origin == self.destination:
            raise ValueError("出发地与目的地不能相同")
        if self.departure_date < date.today():
            raise ValueError("出发日期不能早于今天")
        return self


class JourneySearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip_type: TripType
    legs: list[Leg] = Field(min_length=1, max_length=6)
    cabin: Literal["ECONOMY"] = "ECONOMY"
    currency: Literal["CNY"] = "CNY"
    adults: int = Field(default=1,strict=True,ge=1,le=9)

    @model_validator(mode="after")
    def validate_journey(self):
        if self.trip_type == "ONE_WAY" and len(self.legs) != 1:
            raise ValueError("单程必须包含 1 段行程")
        if self.trip_type == "ROUND_TRIP":
            if len(self.legs) != 2:
                raise ValueError("往返必须包含 2 段行程")
            first, last = self.legs
            if (first.origin, first.destination) != (last.destination, last.origin):
                raise ValueError("返程必须与去程起终点对应；开放口行程请选择多程")
        if self.trip_type == "MULTI_CITY" and len(self.legs) < 2:
            raise ValueError("多程至少包含 2 段行程")
        for previous, current in zip(self.legs, self.legs[1:]):
            if current.departure_date <= previous.departure_date:
                raise ValueError("当前组合仅支持后续行程在前一段的次日或之后出发")
        return self


class JourneyCompose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip_type: TripType
    offer_ids: list[str] = Field(min_length=1, max_length=6)


def search_journey(request: JourneySearch):
    production_truth_required("FLIGHT", "JOURNEY_SEARCH")
    return {
        "trip_type": request.trip_type,
        "data_mode": "SIMULATION",
        "external_live": False,
        "passenger_count": request.adults,
        "ticketing_basis": "INDEPENDENT_TICKETS",
        "legs": [
            {
                "leg_index": index,
                "criteria": leg.model_dump(mode="json"),
                "items": flight_service.search(
                    **leg.model_dump(mode="json"),
                    cabin=request.cabin, currency=request.currency, adults=request.adults,
                ),
            }
            for index, leg in enumerate(request.legs)
        ],
    }


def compose_journey(request: JourneyCompose):
    production_truth_required("FLIGHT", "JOURNEY_COMPOSE")
    if len(set(request.offer_ids)) != len(request.offer_ids):
        raise ValueError("FLIGHT_JOURNEY_INVALID:DUPLICATE_OFFER")
    with SessionLocal.begin() as session:
        offers = [session.get(FlightOfferRow, oid) for oid in request.offer_ids]
        if any(o is None or o.expires_at <= now() for o in offers):
            raise ValueError("FLIGHT_JOURNEY_INVALID:OFFER_EXPIRED_OR_MISSING")
        if any(len(o.segments) != 1 or o.segments[0].get("source_offer_id") for o in offers):
            raise ValueError("FLIGHT_JOURNEY_INVALID:COMPOSITE_NESTING")
        if len({(o.currency, o.cabin) for o in offers}) != 1:
            raise ValueError("FLIGHT_JOURNEY_INVALID:CURRENCY_OR_CABIN_MISMATCH")
        counts={o.segments[0].get('passenger_count',1) for o in offers}
        if len(counts)!=1:raise ValueError('FLIGHT_JOURNEY_INVALID:PASSENGER_COUNT_MISMATCH')
        adults=next(iter(counts))
        # Revalidate database facts; never trust a client-supplied route or total.
        try:
            JourneySearch(
                trip_type=request.trip_type,
                legs=[{"origin": o.origin, "destination": o.destination,
                       "departure_date": o.departure_date} for o in offers],
                currency=offers[0].currency, cabin=offers[0].cabin, adults=adults,
            )
        except ValueError as exc:
            raise ValueError("FLIGHT_JOURNEY_INVALID:ROUTE_OR_DATE") from exc
        segments = [
            {**o.segments[0], "leg_index": index, "source_offer_id": o.offer_id,
             "trip_type": request.trip_type, "fare_family": o.fare_family,
             "passenger_count": adults,
             "total_amount_minor": o.total_amount_minor, "tax_amount_minor": o.tax_amount_minor,
             "currency": o.currency, "baggage": o.baggage,
             "change_policy": o.change_policy, "refund_policy": o.refund_policy,
             "data_mode": "SIMULATION", "ticketing_basis": "INDEPENDENT_TICKETS"}
            for index, o in enumerate(offers)
        ]
        combined = FlightOfferRow(
            offer_id=new_id("flt_jny"), origin=offers[0].origin,
            destination=offers[-1].destination, departure_date=offers[0].departure_date,
            carrier_code=offers[0].carrier_code, flight_number=offers[0].flight_number,
            cabin=offers[0].cabin, fare_family="GO Independent Journey",
            total_amount_minor=sum(o.total_amount_minor for o in offers),
            tax_amount_minor=sum(o.tax_amount_minor for o in offers), currency=offers[0].currency,
            baggage={"per_leg": True},
            change_policy={"allowed": len(offers) == 1 and offers[0].change_policy.get("allowed", False),
                           "fee_minor": offers[0].change_policy.get("fee_minor", 0),
                           "per_leg": True, "partial_change_supported": False},
            refund_policy={"allowed": all(o.refund_policy.get("allowed") for o in offers),
                           "fee_minor": sum(o.refund_policy.get("fee_minor", 0) for o in offers),
                           "scope": "WHOLE_ITINERARY", "partial_refund_supported": False},
            segments=segments, expires_at=min(o.expires_at for o in offers), created_at=now(),
        )
        session.add(combined)
        session.flush()
        return flight_service._offer(combined)
