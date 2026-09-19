"""Explicit direct-file review and publication under existing catalogue authority."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from go_hotel.security.deps import admin_principal, supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.hotel_direct_submission_review import hotel_direct_submission_review_service as reviews
from go_hotel.services.hotel_direct_submission_publication import hotel_direct_submission_publication_service as publication

router = APIRouter(tags=['hotel-direct-submission'])

def writer(p: Principal = Depends(admin_principal)):
    if 'admin:rules' not in p.permissions:
        raise HTTPException(403, detail='PERMISSION_DENIED')
    return p

def call(fn, *args):
    try:
        return {'data': fn(*args)}
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc

class Submission(BaseModel):
    model_config = {'extra':'forbid'}
    manifest: dict
    expected_sha256: str | None = None

class Approval(BaseModel):
    model_config = {'extra':'forbid'}
    expected_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_facts_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

@router.post('/v1/supplier/properties/{property_id}/direct-submission-reviews', status_code=201)
def submit(property_id: str, body: Submission, p: Principal = Depends(supplier_principal)):
    return call(reviews.submit, p.supplier_id, p.user_id, property_id, body.manifest, body.expected_sha256)

@router.get('/v1/supplier/properties/{property_id}/direct-submission-reviews')
def supplier_list(property_id: str, state: str | None = None,
                  offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                  p: Principal = Depends(supplier_principal)):
    return call(reviews.supplier_list, p.supplier_id, property_id, state, offset, limit)

@router.get('/v1/supplier/properties/{property_id}/direct-submission-reviews/{review_id}')
def supplier_read(property_id: str, review_id: str, p: Principal = Depends(supplier_principal)):
    return call(reviews.supplier_get, p.supplier_id, property_id, review_id)

@router.get('/internal/v1/hotel-autopage/direct-submission-reviews')
def list_reviews(property_id: str | None = None, state: str | None = None,
                 offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                 p: Principal = Depends(writer)):
    return call(reviews.list_reviews, property_id, state, offset, limit)

@router.get('/internal/v1/hotel-autopage/direct-submission-reviews/{review_id}/inspection')
def inspection(review_id: str, p: Principal = Depends(writer)):
    return call(reviews.inspection, review_id)

@router.get('/internal/v1/hotel-autopage/direct-submission-reviews/{review_id}/media/{asset_id}')
def review_original(review_id: str, asset_id: str, p: Principal = Depends(writer)):
    try:
        raw, mime = reviews.review_original(review_id, asset_id)
    except ValueError as exc:
        raise HTTPException(404, detail='HOTEL_MEDIA_UNAVAILABLE') from exc
    return Response(raw, media_type=mime, headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'none'",
    })

@router.get('/internal/v1/hotel-autopage/direct-submission-reviews/{review_id}')
def read(review_id: str, p: Principal = Depends(writer)):
    return call(reviews.get, review_id)

@router.post('/internal/v1/hotel-autopage/direct-submission-reviews/{review_id}/approve')
def approve(review_id: str, body: Approval, p: Principal = Depends(writer)):
    return call(reviews.approve, review_id, p.user_id, body.expected_sha256, body.expected_facts_sha256)

@router.post('/internal/v1/hotel-autopage/direct-submission-reviews/{review_id}/revoke')
def revoke(review_id: str, p: Principal = Depends(writer)):
    return call(reviews.revoke, review_id, p.user_id)

@router.post('/internal/v1/hotel-autopage/direct-submission-reviews/{review_id}/publish')
def publish(review_id: str, p: Principal = Depends(writer)):
    # Identities come from the stored review, never a caller-supplied hotel ID.
    review = call(reviews.get, review_id)['data']
    identity = review['manifest']['identity']
    return call(publication.publish, review_id, identity['supplier_id'], identity['property_id'], p.user_id)

@router.get('/v1/hotel-pages/direct-submissions/{review_id}/media/{asset_id}')
def content(review_id: str, asset_id: str):
    try:
        raw, mime = publication.public_content(review_id, asset_id)
    except ValueError as exc:
        raise HTTPException(404, detail='HOTEL_MEDIA_UNAVAILABLE') from exc
    return Response(raw, media_type=mime, headers={
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'none'",
    })
