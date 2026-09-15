from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from go_hotel.db.models import OfferRow
from go_hotel.db.session import SessionLocal
from go_hotel.security.deps import supplier_principal, require_permission
from go_hotel.security.service import Principal
from go_hotel.services import catalog_fare_snapshot as fare

router = APIRouter(prefix='/v1/supplier/catalog-fare', tags=['catalog-fare-rules'],dependencies=[Depends(require_permission('supplier:read'))])


class PublishBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rules: dict
    authority_reference: str = Field(min_length=1, max_length=512)
    expected_version_id: str | None = None
    confirmed: bool = Field(strict=True)


@router.get('/offers')
def offers(p: Principal = Depends(supplier_principal)):
    with SessionLocal() as s:
        rows = s.scalars(select(OfferRow).where(OfferRow.supplier_id == p.supplier_id).order_by(OfferRow.created_at.desc()).limit(100)).all()
        selected = {}
        for o in rows:
            selected.setdefault(fare.family_id(o), o)
        items = [{'offer_id': o.offer_id, **fare.identity(o), 'room_type_id': o.room_type_id,
            'check_in': o.check_in, 'check_out': o.check_out,
            'published_rule': fare.configured(o.offer_id, p.supplier_id)} for o in selected.values()]
    return {'data': {'items': items, 'scope': 'LATEST_100_OWN_CATALOG_OFFERS'}}


@router.get('/offers/{offer_id}')
def current(offer_id: str, p: Principal = Depends(supplier_principal)):
    try:
        return {'data': fare.configured(offer_id, p.supplier_id)}
    except ValueError as exc:
        raise HTTPException(404, detail=str(exc))


@router.post('/offers/{offer_id}/publish',dependencies=[Depends(require_permission('supplier:fare-rules'))])
def publish(offer_id: str, body: PublishBody, p: Principal = Depends(supplier_principal)):
    if not body.confirmed:
        raise HTTPException(409, detail='EXPLICIT_SUPPLIER_RULE_PUBLICATION_REQUIRED')
    try:
        return {'data': fare.publish(offer_id, body.rules, body.authority_reference, p.user_id,
            p.supplier_id, body.expected_version_id)}
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == 'OWN_SUPPLIER_OFFER_REQUIRED' else 409, detail=str(exc))
