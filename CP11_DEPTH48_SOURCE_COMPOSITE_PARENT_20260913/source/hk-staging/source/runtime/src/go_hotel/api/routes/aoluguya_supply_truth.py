from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.aoluguya_supply_truth import aoluguya_supply_truth_service as svc

router = APIRouter(prefix="/internal/v1/aoluguya-supply-truth", tags=["aoluguya-supply-truth-pilot"])


class Payload(BaseModel):
    model_config = {"extra": "allow"}


def call(fn, *args):
    try:
        return {"data": fn(*args)}
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc))


@router.post("/connector/ensure")
def ensure(p: Principal = Depends(admin_principal)):
    return call(svc.ensure_named_connector, p.user_id)


@router.post("/official-snapshot")
def ingest(body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.ingest_official_truth, body.model_dump(exclude_none=True), p.user_id)


@router.get("/gate")
def gate(p: Principal = Depends(admin_principal)):
    return call(svc.evaluate)


@router.get("/official-snapshot-template")
def official_snapshot_template(p: Principal = Depends(admin_principal)):
    return call(svc.official_snapshot_template)


@router.post("/project")
def project(p: Principal = Depends(admin_principal)):
    return call(svc.project_to_hosted_direct, p.user_id)


@router.post("/rollback-cutover")
def rollback_cutover(p: Principal = Depends(admin_principal)):
    return call(svc.rollback_cutover, p.user_id)


@router.get("/status")
def status(p: Principal = Depends(admin_principal)):
    return call(svc.status)


@router.get("/fallback-governance")
def fallback_governance(p: Principal = Depends(admin_principal)):
    return call(svc.fallback_governance)


@router.post("/route")
def route(body: Payload, p: Principal = Depends(admin_principal)):
    return call(svc.route, body.model_dump(exclude_none=True))
