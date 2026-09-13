from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from go_hotel.go_ai.service import go_ai_service
from go_hotel.security.deps import admin_principal, consumer_principal
from go_hotel.security.service import Principal

router = APIRouter(tags=["go-ai"])


class GOAIRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    task_type: str = "GENERAL"
    region: str = "GLOBAL"
    language: str | None = None
    context: dict = Field(default_factory=dict)
    max_output_tokens: int = Field(default=1200, ge=1, le=8000)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)


class HotelRecommendationBody(BaseModel):
    hotel_ids: list[str] = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=50)


def _call(fn, *args, **kwargs):
    try:
        return {"data": fn(*args, **kwargs)}
    except ValueError as exc:
        detail = str(exc)
        status = 503 if detail in {"GO_AI_NO_ELIGIBLE_MODEL_PROVIDER", "GO_AI_ALL_ELIGIBLE_PROVIDERS_FAILED"} else 409
        if detail == "GO_AI_REQUEST_NOT_FOUND":
            status = 404
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/v1/go-ai/orchestrate")
def go_ai_orchestrate(body: GOAIRequestBody, p: Principal = Depends(consumer_principal)):
    return _call(
        go_ai_service.orchestrate,
        message=body.message,
        region=body.region,
        language=body.language,
        context=body.context,
        account_id=p.user_id,
        max_output_tokens=body.max_output_tokens,
        temperature=body.temperature,
    )


@router.post("/v1/go-ai")
def go_ai(body: GOAIRequestBody, p: Principal = Depends(consumer_principal)):
    return _call(
        go_ai_service.respond,
        message=body.message,
        task_type=body.task_type,
        region=body.region,
        language=body.language,
        context=body.context,
        account_id=p.user_id,
        max_output_tokens=body.max_output_tokens,
        temperature=body.temperature,
    )


@router.post("/v1/go-ai/hotel-recommendations")
def hotel_recommendations(body: HotelRecommendationBody, p: Principal = Depends(consumer_principal)):
    return _call(go_ai_service.recommend_hotels, hotel_ids=body.hotel_ids, limit=body.limit)


@router.get("/internal/v1/go-ai/providers")
def provider_status(p: Principal = Depends(admin_principal)):
    return {"data": go_ai_service.provider_status()}


@router.post("/internal/v1/go-ai/providers/reload")
def reload_providers(p: Principal = Depends(admin_principal)):
    go_ai_service.reload_registry()
    return {"data": go_ai_service.provider_status()}


@router.get("/internal/v1/go-ai/requests/{request_id}")
def request_audit(request_id: str, p: Principal = Depends(admin_principal)):
    return _call(go_ai_service.request_audit, request_id)
