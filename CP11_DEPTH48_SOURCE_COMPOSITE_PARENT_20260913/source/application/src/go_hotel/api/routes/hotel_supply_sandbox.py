from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.hotel_supply_sandbox import hotel_supply_sandbox_certification_service as svc

router = APIRouter(prefix="/internal/v1/hotel-supply-sandbox", tags=["hotel-supply-sandbox-certification"])


class Payload(BaseModel):
    model_config = {"extra": "allow"}


def call(fn, *args):
    try:
        return {"data": fn(*args)}
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc))


@router.get("/dashboard")
def dashboard(p: Principal = Depends(admin_principal)):
    return {"data": svc.dashboard()}


@router.post("/connectors")
def register(body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.register, body.model_dump(exclude_none=True), p.user_id)


@router.post("/connectors/{connector_id}/authority")
def authority(connector_id: str, body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.bind_authority, connector_id, body.model_dump(exclude_none=True), p.user_id)


@router.post("/connectors/{connector_id}/credential")
def credential(connector_id: str, body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.bind_credential, connector_id, body.model_dump(exclude_none=True), p.user_id)


@router.post("/connectors/{connector_id}/mapping")
def mapping(connector_id: str, body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.set_mapping, connector_id, body.model_dump(exclude_none=True), p.user_id)


@router.get("/connectors/{connector_id}/readiness")
def readiness(connector_id: str, p: Principal = Depends(admin_principal)):
    return call(svc.readiness, connector_id)


@router.post("/connectors/{connector_id}/provider-adapter-contract")
def provider_adapter_contract(connector_id: str, body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.set_provider_adapter_contract, connector_id, body.model_dump(exclude_none=True), p.user_id)


@router.get("/connectors/{connector_id}/provider-adapter-readiness")
def provider_adapter_readiness(connector_id: str, p: Principal = Depends(admin_principal)):
    return call(svc.provider_adapter_readiness, connector_id)


@router.post("/connectors/{connector_id}/framework-certify")
def framework_certify(connector_id: str, body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.framework_certify, connector_id, body.model_dump(exclude_none=True), p.user_id)


@router.post("/connectors/{connector_id}/external-certify")
def external_certify(connector_id: str, body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.external_certify, connector_id, body.model_dump(exclude_none=True), p.user_id)
