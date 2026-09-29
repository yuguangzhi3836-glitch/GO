"""Authenticated privacy intake; recorded requests are not deletion receipts."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from go_hotel.security.deps import consumer_principal, supplier_principal, admin_principal
from go_hotel.security.service import Principal
from go_hotel.services import registration_privacy as privacy
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import PrivacyRequestRow, AuditEventRow
from go_hotel.domain.models import new_id
from datetime import datetime, timezone

router=APIRouter(tags=['registration-privacy'])


class RequestBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: Literal['ACCESS','CORRECTION','DELETION','WITHDRAWAL','CLOSURE','RESTRICTION','TRANSFER']


def overview(p,response):
    response.headers['Cache-Control']='no-store'
    return {'data':{'decisions':privacy.own_history(p.user_id),'requests':privacy.requests_for(p.user_id),
        'intake_available':True,'operational_readiness':privacy.operational_evidence_status()['ready'],
        'notice':'申请提交后等待核验处理，不表示数据已删除或账号已注销。',
        'vault_consents_url':'/v1/consumer/profile/consents' if p.actor_type=='CONSUMER' else None}}


@router.get('/v1/consumer/privacy')
def consumer_overview(response:Response,p:Principal=Depends(consumer_principal)):
    return overview(p,response)


@router.get('/bff/privacy')
def supplier_overview(response:Response,p:Principal=Depends(supplier_principal)):
    return overview(p,response)


@router.post('/v1/consumer/privacy/requests',status_code=202)
def consumer_request(body:RequestBody,p:Principal=Depends(consumer_principal)):
    return {'data':privacy.submit_request(p.user_id,body.kind)}


@router.post('/bff/privacy/requests',status_code=202)
def supplier_request(body:RequestBody,p:Principal=Depends(supplier_principal)):
    return {'data':privacy.submit_request(p.user_id,body.kind)}


def privacy_operator(p:Principal=Depends(admin_principal)):
    if 'admin:trust' not in p.permissions:
        raise HTTPException(403,detail='PRIVACY_OPERATOR_REQUIRED')
    return p


@router.get('/internal/privacy/requests')
def queue(response:Response,p:Principal=Depends(privacy_operator)):
    response.headers['Cache-Control']='no-store'
    with SessionLocal() as s:
        rows=s.scalars(select(PrivacyRequestRow).where(PrivacyRequestRow.status.in_(['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION'])).order_by(PrivacyRequestRow.due_ms).limit(100))
        return {'data':{'items':[privacy.case_view(x) for x in rows],'maintenance':privacy.maintenance_status()}}


class ResolutionBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_status: Literal['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION']
    status: Literal['IN_REVIEW','COMPLETED','REJECTED','RESTRICTED_RETENTION']
    evidence_ref: str=Field(min_length=1,max_length=512)
    summary: str=Field(min_length=1,max_length=1000)
    legal_basis: str=Field(default='',max_length=500)
    restricted_scope: str=Field(default='',max_length=500)
    next_review_ms: int|None=None


@router.post('/internal/privacy/requests/{request_id}/resolution')
def resolve(request_id:str,body:ResolutionBody,p:Principal=Depends(privacy_operator)):
    with SessionLocal.begin() as s:
        row=s.scalar(select(PrivacyRequestRow).where(PrivacyRequestRow.request_id==request_id).with_for_update())
        if not row:raise HTTPException(404,detail='PRIVACY_REQUEST_NOT_FOUND')
        if row.status!=body.expected_status:raise HTTPException(409,detail='PRIVACY_REQUEST_CHANGED')
        if row.status=='RECEIVED' and body.status!='IN_REVIEW':raise HTTPException(409,detail='PRIVACY_REVIEW_REQUIRED')
        if body.status in ('REJECTED','RESTRICTED_RETENTION') and not body.legal_basis.strip():
            raise HTTPException(422,detail='PRIVACY_LEGAL_BASIS_REQUIRED')
        if body.status=='RESTRICTED_RETENTION' and (not body.restricted_scope.strip() or not body.next_review_ms or body.next_review_ms<=privacy.now_ms()):
            raise HTTPException(422,detail='PRIVACY_RESTRICTION_SCOPE_AND_REVIEW_REQUIRED')
        before=row.status
        row.status=body.status;row.updated_ms=privacy.now_ms()
        row.resolution={'operator':p.user_id,'evidence_ref':body.evidence_ref,'summary':body.summary,
                        'legal_basis':body.legal_basis,'restricted_scope':body.restricted_scope}
        if body.status=='RESTRICTED_RETENTION':row.due_ms=body.next_review_ms
        s.add(AuditEventRow(audit_id=new_id('aud'),actor_id=p.user_id,actor_type=p.actor_type,
            supplier_id=p.supplier_id,roles=list(p.roles),session_id=p.session_id,
            action='PRIVACY_REQUEST_RESOLVED',resource_type='PRIVACY_REQUEST',resource_id=request_id,
            request_id=None,client_ip=None,http_method='POST',path='/internal/privacy/requests/resolution',
            before_state={'status':before},after_state={'status':row.status},decision_id=None,
            evidence_id=None,approval_id=None,metadata_json=row.resolution,created_at=datetime.now(timezone.utc)))
        return {'data':privacy.case_view(row)}
