from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    SupplierConnectorOnboardingRow, ConnectorCredentialRow, PropertyMappingCandidateRow,
    ConnectorActivationAuditRow, ConnectorCertificationRow, HotelExternalIdentityRow, ConnectorKmsBindingRow,
)
from go_hotel.domain.models import new_id
from go_hotel.services.connectors import connector_service
from go_hotel.core.config import settings


def now(): return datetime.now(timezone.utc)

ALLOWED_TRANSITIONS = {
    "DRAFT": {"CREDENTIALS_PENDING", "SUSPENDED"},
    "CREDENTIALS_PENDING": {"MAPPING_PENDING", "SUSPENDED"},
    "MAPPING_PENDING": {"CERTIFICATION_PENDING", "SUSPENDED"},
    "CERTIFICATION_PENDING": {"CERTIFIED", "MAPPING_PENDING", "SUSPENDED"},
    "CERTIFIED": {"ACTIVATION_PENDING", "SUSPENDED"},
    "ACTIVATION_PENDING": {"ACTIVE", "CERTIFIED", "SUSPENDED"},
    "ACTIVE": {"SUSPENDED", "REVOKED"},
    "SUSPENDED": {"CREDENTIALS_PENDING", "MAPPING_PENDING", "CERTIFICATION_PENDING", "CERTIFIED", "ACTIVE", "REVOKED"},
    "REVOKED": set(),
}

class OnboardingService:
    def _row(self, onboarding_id: str):
        with SessionLocal() as s:
            r=s.get(SupplierConnectorOnboardingRow,onboarding_id)
            if not r: raise KeyError("ONBOARDING_NOT_FOUND")
            return self._dict(r)
    @staticmethod
    def _dict(r):
        return {"onboarding_id":r.onboarding_id,"supplier_id":r.supplier_id,"connector_id":r.connector_id,"environment":r.environment,"status":r.status,"rollout_percent":r.rollout_percent,"last_certification_id":r.last_certification_id,"created_at":r.created_at,"updated_at":r.updated_at,"activated_at":r.activated_at,"suspended_at":r.suspended_at}
    def create(self,supplier_id:str,connector_id:str,environment:str="SANDBOX"):
        registry_meta = {m.connector_id for m in __import__('go_hotel.connectors.registry',fromlist=['registry']).registry.list()}
        # onboarding may precede runtime registration for a contracted adapter, but connector ID must be known in source or explicitly named.
        if not connector_id.startswith("conn_"): raise ValueError("INVALID_CONNECTOR_ID")
        with SessionLocal.begin() as s:
            existing=s.scalar(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.supplier_id==supplier_id,SupplierConnectorOnboardingRow.connector_id==connector_id,SupplierConnectorOnboardingRow.environment==environment))
            if existing: return self._dict(existing)
            r=SupplierConnectorOnboardingRow(onboarding_id=new_id("onb"),supplier_id=supplier_id,connector_id=connector_id,environment=environment,status="DRAFT",rollout_percent=0,created_at=now(),updated_at=now())
            s.add(r); s.flush(); self._audit(s,r,"DRAFT","DRAFT","ONBOARDING_CREATED","system",{})
            return self._dict(r)
    def list(self):
        with SessionLocal() as s: return [self._dict(r) for r in s.scalars(select(SupplierConnectorOnboardingRow).order_by(SupplierConnectorOnboardingRow.created_at.desc())).all()]
    def reject_inline_credentials(self,*args,**kwargs):
        # Wave 07 hard boundary retained for explicit legacy callers.
        raise ValueError("INLINE_PROVIDER_SECRET_FORBIDDEN_USE_CREDENTIAL_REFERENCE")
    def store_credential_reference(self,onboarding_id:str,credential_reference:str,actor_id:str="system",purpose:str="PROVIDER_AUTH"):
        from go_hotel.core.provider_onboarding_governance_v1 import validate_credential_reference
        reference=validate_credential_reference(credential_reference)
        scheme=reference.split("://",1)[0].upper().replace("-","_")
        with SessionLocal.begin() as s:
            r=s.execute(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.onboarding_id==onboarding_id).with_for_update()).scalar_one()
            old=s.scalars(select(ConnectorKmsBindingRow).where(ConnectorKmsBindingRow.connector_id==r.connector_id,ConnectorKmsBindingRow.purpose==purpose,ConnectorKmsBindingRow.state=="ACTIVE")).all()
            for binding in old: binding.state="REVOKED"; binding.updated_at=now()
            binding=ConnectorKmsBindingRow(kms_binding_id=new_id("kms"),connector_id=r.connector_id,provider=scheme,resource_reference=reference,purpose=purpose,access_test_json={"state":"REFERENCE_ONLY_NOT_LIVE_TESTED","external_call_executed":False},state="ACTIVE",updated_at=now())
            s.add(binding)
            if r.status=="DRAFT": self._transition(s,r,"CREDENTIALS_PENDING","CREDENTIAL_REFERENCE_BOUND",actor_id,{"kms_binding_id":binding.kms_binding_id,"provider":scheme,"purpose":purpose})
            if r.status=="CREDENTIALS_PENDING": self._transition(s,r,"MAPPING_PENDING","CREDENTIAL_REFERENCE_READY",actor_id,{"kms_binding_id":binding.kms_binding_id,"reference_only":True})
            self._audit(s,r,r.status,r.status,"CREDENTIAL_REFERENCE_BOUND",actor_id,{"kms_binding_id":binding.kms_binding_id,"provider":scheme,"purpose":purpose,"reference_only":True})
            return {"kms_binding_id":binding.kms_binding_id,"credential_reference":reference,"provider":scheme,"purpose":purpose,"status":binding.state,"reference_only":True,"external_call_executed":False}
    def credential_metadata(self,onboarding_id:str):
        with SessionLocal() as s:
            onb=s.get(SupplierConnectorOnboardingRow,onboarding_id)
            if not onb: raise KeyError("ONBOARDING_NOT_FOUND")
            rows=s.scalars(select(ConnectorKmsBindingRow).where(ConnectorKmsBindingRow.connector_id==onb.connector_id).order_by(ConnectorKmsBindingRow.updated_at.desc())).all()
            return [{"kms_binding_id":r.kms_binding_id,"provider":r.provider,"purpose":r.purpose,"status":r.state,"reference_only":True,"external_call_executed":False,"updated_at":r.updated_at} for r in rows]
    def propose_mapping(self,onboarding_id:str,external_hotel_id:str,proposed_hotel_id:str|None,external_name:str|None=None,external_address:str|None=None,confidence_bps:int=0,match_method:str="MANUAL"):
        with SessionLocal.begin() as s:
            onb=s.get(SupplierConnectorOnboardingRow,onboarding_id)
            if not onb: raise KeyError("ONBOARDING_NOT_FOUND")
            existing=s.scalar(select(PropertyMappingCandidateRow).where(PropertyMappingCandidateRow.onboarding_id==onboarding_id,PropertyMappingCandidateRow.external_hotel_id==external_hotel_id))
            if existing:
                existing.proposed_hotel_id=proposed_hotel_id; existing.external_name=external_name; existing.external_address=external_address; existing.confidence_bps=confidence_bps; existing.match_method=match_method; existing.status="PROPOSED"; existing.reviewed_at=None; existing.reviewed_by=None
                r=existing
            else:
                r=PropertyMappingCandidateRow(mapping_id=new_id("map"),onboarding_id=onboarding_id,connector_id=onb.connector_id,external_hotel_id=external_hotel_id,proposed_hotel_id=proposed_hotel_id,external_name=external_name,external_address=external_address,confidence_bps=confidence_bps,match_method=match_method,status="PROPOSED",created_at=now())
                s.add(r)
            return self._mapping_dict(r)
    def mappings(self,onboarding_id:str):
        with SessionLocal() as s: return [self._mapping_dict(r) for r in s.scalars(select(PropertyMappingCandidateRow).where(PropertyMappingCandidateRow.onboarding_id==onboarding_id).order_by(PropertyMappingCandidateRow.created_at)).all()]
    @staticmethod
    def _mapping_dict(r):
        return {"mapping_id":r.mapping_id,"external_hotel_id":r.external_hotel_id,"proposed_hotel_id":r.proposed_hotel_id,"external_name":r.external_name,"confidence_bps":r.confidence_bps,"match_method":r.match_method,"status":r.status,"reviewed_by":r.reviewed_by,"review_note":r.review_note}
    def review_mapping(self,mapping_id:str,decision:str,actor_id:str,note:str|None=None):
        decision=decision.upper()
        if decision not in {"APPROVE","REJECT"}: raise ValueError("INVALID_MAPPING_DECISION")
        with SessionLocal.begin() as s:
            r=s.execute(select(PropertyMappingCandidateRow).where(PropertyMappingCandidateRow.mapping_id==mapping_id).with_for_update()).scalar_one()
            onb=s.execute(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.onboarding_id==r.onboarding_id).with_for_update()).scalar_one()
            if decision=="APPROVE":
                if not r.proposed_hotel_id: raise ValueError("CANONICAL_HOTEL_ID_REQUIRED")
                r.status="APPROVED"
                ident=s.scalar(select(HotelExternalIdentityRow).where(HotelExternalIdentityRow.connector_id==r.connector_id,HotelExternalIdentityRow.external_hotel_id==r.external_hotel_id))
                if ident is None:
                    ident=HotelExternalIdentityRow(connector_id=r.connector_id,external_hotel_id=r.external_hotel_id,hotel_id=r.proposed_hotel_id,match_confidence_bps=r.confidence_bps,match_method=r.match_method,status="ACTIVE",created_at=now(),updated_at=now()); s.add(ident)
                else:
                    ident.hotel_id=r.proposed_hotel_id; ident.match_confidence_bps=r.confidence_bps; ident.match_method=r.match_method; ident.status="ACTIVE"; ident.updated_at=now()
            else: r.status="REJECTED"
            r.reviewed_by=actor_id; r.review_note=note; r.reviewed_at=now(); s.flush()
            approved=s.scalar(select(func.count()).select_from(PropertyMappingCandidateRow).where(PropertyMappingCandidateRow.onboarding_id==r.onboarding_id,PropertyMappingCandidateRow.status=="APPROVED")) or 0
            if approved>0 and onb.status=="MAPPING_PENDING": self._transition(s,onb,"CERTIFICATION_PENDING","PROPERTY_MAPPING_APPROVED",actor_id,{"mapping_id":mapping_id})
            return self._mapping_dict(r)
    async def certify(self,onboarding_id:str,actor_id:str="system"):
        with SessionLocal() as s:
            onb=s.get(SupplierConnectorOnboardingRow,onboarding_id)
            if not onb: raise KeyError("ONBOARDING_NOT_FOUND")
            connector_id=onb.connector_id
            if onb.status not in {"CERTIFICATION_PENDING","CERTIFIED"}: raise ValueError("ONBOARDING_NOT_READY_FOR_CERTIFICATION")
        report=await connector_service.certify(connector_id)
        with SessionLocal.begin() as s:
            onb=s.execute(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.onboarding_id==onboarding_id).with_for_update()).scalar_one()
            cert=s.scalar(select(ConnectorCertificationRow).where(ConnectorCertificationRow.connector_id==connector_id).order_by(ConnectorCertificationRow.certification_id.desc()))
            onb.last_certification_id=cert.certification_id if cert else None
            if report.get("passed"):
                self._transition(s,onb,"CERTIFIED","SANDBOX_CERTIFICATION_PASSED",actor_id,{"certification_id":onb.last_certification_id})
            else:
                self._audit(s,onb,onb.status,onb.status,"SANDBOX_CERTIFICATION_FAILED",actor_id,{"report":report})
        return report
    def request_activation(self,onboarding_id:str,actor_id:str):
        with SessionLocal.begin() as s:
            onb=s.execute(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.onboarding_id==onboarding_id).with_for_update()).scalar_one()
            self._assert_activation_ready(s,onb)
            self._transition(s,onb,"ACTIVATION_PENDING","ACTIVATION_REQUESTED",actor_id,{})
            return self._dict(onb)
    def activate(self,onboarding_id:str,actor_id:str,rollout_percent:int|None=None):
        pct=rollout_percent if rollout_percent is not None else settings.connector_initial_rollout_percent
        if pct<1 or pct>100: raise ValueError("INVALID_ROLLOUT_PERCENT")
        with SessionLocal.begin() as s:
            onb=s.execute(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.onboarding_id==onboarding_id).with_for_update()).scalar_one()
            if onb.status not in {"ACTIVATION_PENDING","SUSPENDED"}: raise ValueError("ACTIVATION_NOT_PENDING")
            self._assert_activation_ready(s,onb)
            old=onb.status; onb.status="ACTIVE"; onb.rollout_percent=pct; onb.activated_at=now(); onb.suspended_at=None; onb.updated_at=now(); self._audit(s,onb,old,"ACTIVE","CONNECTOR_ACTIVATED",actor_id,{"rollout_percent":pct})
            return self._dict(onb)
    def set_rollout(self,onboarding_id:str,actor_id:str,percent:int):
        if percent<0 or percent>100: raise ValueError("INVALID_ROLLOUT_PERCENT")
        with SessionLocal.begin() as s:
            onb=s.execute(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.onboarding_id==onboarding_id).with_for_update()).scalar_one()
            if onb.status!="ACTIVE": raise ValueError("CONNECTOR_NOT_ACTIVE")
            old=onb.rollout_percent; onb.rollout_percent=percent; onb.updated_at=now(); self._audit(s,onb,"ACTIVE","ACTIVE","ROLLOUT_CHANGED",actor_id,{"from":old,"to":percent})
            return self._dict(onb)
    def suspend(self,onboarding_id:str,actor_id:str,reason:str):
        with SessionLocal.begin() as s:
            onb=s.execute(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.onboarding_id==onboarding_id).with_for_update()).scalar_one()
            old=onb.status; onb.status="SUSPENDED"; onb.rollout_percent=0; onb.suspended_at=now(); onb.updated_at=now(); self._audit(s,onb,old,"SUSPENDED",reason,actor_id,{})
            return self._dict(onb)
    def _assert_activation_ready(self,s,onb):
        cred=s.scalar(select(ConnectorKmsBindingRow).where(ConnectorKmsBindingRow.connector_id==onb.connector_id,ConnectorKmsBindingRow.purpose=="PROVIDER_AUTH",ConnectorKmsBindingRow.state=="ACTIVE"))
        maps=s.scalar(select(func.count()).select_from(PropertyMappingCandidateRow).where(PropertyMappingCandidateRow.onboarding_id==onb.onboarding_id,PropertyMappingCandidateRow.status=="APPROVED")) or 0
        cert=s.get(ConnectorCertificationRow,onb.last_certification_id) if onb.last_certification_id else None
        if not cred: raise ValueError("ACTIVE_CREDENTIAL_REQUIRED")
        if maps<1: raise ValueError("APPROVED_PROPERTY_MAPPING_REQUIRED")
        if not cert or not cert.passed: raise ValueError("PASSED_CERTIFICATION_REQUIRED")
    def _transition(self,s,row,to_status,reason,actor_id,detail):
        old=row.status
        if old!=to_status and to_status not in ALLOWED_TRANSITIONS.get(old,set()): raise ValueError(f"INVALID_ONBOARDING_TRANSITION:{old}->{to_status}")
        row.status=to_status; row.updated_at=now(); self._audit(s,row,old,to_status,reason,actor_id,detail)
    def _audit(self,s,row,from_status,to_status,reason,actor_id,detail):
        s.add(ConnectorActivationAuditRow(onboarding_id=row.onboarding_id,from_status=from_status,to_status=to_status,reason=reason,actor_id=actor_id,detail=detail,occurred_at=now()))

onboarding_service=OnboardingService()
