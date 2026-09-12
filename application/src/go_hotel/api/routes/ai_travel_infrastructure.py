from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from go_hotel.core import master_baseline

router = APIRouter(prefix="/v1/ai-infrastructure", tags=["ai-travel-infrastructure"])

class IdentityReleaseRequest(BaseModel):
    external_agent: str = Field(min_length=1, max_length=120)
    consent_ref: str = Field(min_length=1, max_length=200)
    purpose: Literal["QUOTE", "BOOKING", "PAYMENT", "TRIP_SERVICE", "CHANGE_CANCEL"]
    requested_scopes: list[str] = Field(default_factory=list, max_length=20)
    traveler_ref: str | None = None

class BookingOrchestrationRequest(BaseModel):
    external_agent: str = Field(min_length=1, max_length=120)
    consent_ref: str = Field(min_length=1, max_length=200)
    offer_ref: str = Field(min_length=1, max_length=200)
    traveler_ref: str | None = None
    payment_token_ref: str | None = None

ALLOWED_SCOPES = {
    "traveler.name", "traveler.contact", "traveler.document_token",
    "loyalty.reference", "billing.profile_token", "trip.state"
}

@router.get("/manifest")
def capability_manifest():
    return {
        "master_version": master_baseline.MASTER_VERSION,
        "principle": master_baseline.AI_TRAVEL_INFRASTRUCTURE_PRINCIPLE,
        "interaction": "GO_PROVIDES_CAPABILITY_NOT_COMPULSORY_UI_OWNERSHIP",
        "clients": ["CONSUMER", "SUPPLIER", "AI_AGENT"],
        "capabilities": [
            "resolve_travel_intent", "search_comparable_offers", "resolve_traveler",
            "create_booking_intent", "authorize_payment", "confirm_booking",
            "get_trip_state", "cancel_or_change"
        ],
        "protocol_targets": ["REST", "MCP", "A2A"],
        "base_call_price_cny": master_baseline.AI_BASE_INFRASTRUCTURE_CALL_PRICE_CNY,
        "distribution_principle": master_baseline.AI_DISTRIBUTION_PRINCIPLE,
        "paid_recommendation_ranking": False,
        "production_truth": "CAPABILITY_CONTRACT_DOES_NOT_CLAIM_EXTERNAL_AGENT_OR_PROVIDER_IS_LIVE",
    }

@router.post("/identity-release-plan")
def identity_release_plan(req: IdentityReleaseRequest):
    unknown = sorted(set(req.requested_scopes) - ALLOWED_SCOPES)
    if unknown:
        raise HTTPException(status_code=422, detail={"code":"UNSUPPORTED_IDENTITY_SCOPE","scopes":unknown})
    return {
        "external_agent": req.external_agent,
        "consent_ref": req.consent_ref,
        "purpose": req.purpose,
        "approved_scopes": sorted(set(req.requested_scopes)),
        "release_mode": "PURPOSE_BOUND_MINIMUM_NECESSARY",
        "full_vault_export": False,
        "sensitive_payment_credentials_exported": False,
        "requires_go_hosted_authorization": req.purpose in {"PAYMENT", "CHANGE_CANCEL"},
        "state": "PLAN_ONLY",
    }

@router.post("/booking-orchestration-plan")
def booking_orchestration_plan(req: BookingOrchestrationRequest):
    return {
        "external_agent": req.external_agent,
        "offer_ref": req.offer_ref,
        "consent_ref": req.consent_ref,
        "steps": [
            "VERIFY_CONSENT", "RESOLVE_MINIMUM_TRAVELER_DATA", "VERIFY_OFFER_TRUTH",
            "CREATE_IDEMPOTENT_BOOKING_INTENT", "PSP_AUTHORIZATION_IF_REQUIRED",
            "SUPPLIER_CONFIRMATION", "WRITE_TRANSACTION_TRUTH", "ATTACH_TO_GO_TRIP_STATE"
        ],
        "external_agent_receives_full_vault": False,
        "booking_success_may_only_follow_supplier_evidence": True,
        "state": "PLAN_ONLY",
    }
