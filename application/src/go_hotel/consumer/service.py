from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import IdentityUserRow, ConsumerProfileRow, TravelerProfileRow, ConsumerPaymentMethodRow, ConsumerWalletRow, AuditEventRow
from go_hotel.security.service import identity_service, Principal
from go_hotel.security.crypto import encrypt_secret, decrypt_secret, hash_password
from go_hotel.domain.models import new_id


def now(): return datetime.now(timezone.utc)
def go_id_for(user_id:str): return "GO" + hashlib.sha256(user_id.encode()).hexdigest()[:12].upper()

class ConsumerService:
    def register(self,email:str,password:str,display_name:str|None=None,phone:str|None=None,registration_audit:dict|None=None,verification_proof:dict|None=None):
        email=email.strip().lower()
        t=now(); user_id=new_id("usr")
        try:
            with SessionLocal.begin() as s:
                if verification_proof is not None:
                    from go_hotel.services.registration_verification import consume
                    consume(s, verification_proof, user_id)
                if s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==email)):
                    raise ValueError("EMAIL_ALREADY_REGISTERED")
                s.add(IdentityUserRow(user_id=user_id,username=email,password_hash=hash_password(password),actor_type="CONSUMER",supplier_id=None,roles=["CONSUMER"],status="ACTIVE",token_version=1,created_at=t,updated_at=t))
                s.flush()
                s.add_all([
                    ConsumerProfileRow(user_id=user_id,go_id=go_id_for(user_id),email=email,display_name=display_name,phone_ciphertext=encrypt_secret(phone) if phone else None,locale="zh-CN",status="ACTIVE",created_at=t,updated_at=t),
                    ConsumerWalletRow(wallet_id=new_id("wal"),user_id=user_id,status="ACTIVE",created_at=t,updated_at=t),
                ])
                if registration_audit is not None:
                    s.add(AuditEventRow(audit_id=new_id("aud"),actor_id=user_id,actor_type="CONSUMER",supplier_id=None,roles=["CONSUMER"],session_id=None,action="CONSUMER_REGISTRATION_TERMS_ACCEPTED",resource_type="CONSUMER_REGISTRATION",resource_id=user_id,request_id=registration_audit.get("request_id"),client_ip=registration_audit.get("client_ip"),http_method="POST",path="/v1/consumer/auth/register",before_state=None,after_state={"registration_state":"ACCOUNT_CREATED"},decision_id=None,evidence_id=None,approval_id=None,metadata_json={"term_versions":registration_audit["term_versions"],"term_hashes":registration_audit.get("term_hashes",{}),"accepted_once":True,"personal_vault_opt_in":False,"email_verified":verification_proof is not None,"verification_challenge_id":verification_proof["challenge_id"] if verification_proof else None},created_at=t))
        except IntegrityError:
            with SessionLocal() as s:
                if s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==email)):
                    raise ValueError("EMAIL_ALREADY_REGISTERED") from None
            raise
        return self.profile_by_user(user_id)
    def profile_by_user(self,user_id:str):
        with SessionLocal() as s:
            p=s.get(ConsumerProfileRow,user_id)
            if not p: raise ValueError("CONSUMER_PROFILE_NOT_FOUND")
            return {"user_id":p.user_id,"go_id":p.go_id,"email":p.email,"display_name":p.display_name,"phone":decrypt_secret(p.phone_ciphertext) if p.phone_ciphertext else None,"locale":p.locale,"status":p.status}
    def login(self,email,password,client_ip=None,user_agent=None):
        tokens=identity_service.login(email.strip().lower(),password,client_ip,user_agent)
        p=identity_service.authenticate(tokens["access_token"])
        if p.actor_type!="CONSUMER":
            identity_service.revoke_session(p.session_id); raise ValueError("CONSUMER_IDENTITY_REQUIRED")
        return tokens
    def add_traveler(self,p:Principal,full_name,date_of_birth=None,nationality=None,document_type=None,document_number=None,is_primary=False):
        t=now(); tid=new_id("trav")
        with SessionLocal() as s:
            if is_primary:
                s.execute(update(TravelerProfileRow).where(TravelerProfileRow.user_id==p.user_id).values(is_primary=False))
            r=TravelerProfileRow(traveler_id=tid,user_id=p.user_id,full_name=full_name,date_of_birth=date_of_birth,nationality=nationality,document_type=document_type,document_ciphertext=encrypt_secret(document_number) if document_number else None,is_primary=is_primary,status="ACTIVE",created_at=t,updated_at=t)
            s.add(r); s.commit()
        return self.get_traveler(p,tid)
    def get_traveler(self,p:Principal,tid):
        with SessionLocal() as s:
            r=s.get(TravelerProfileRow,tid)
            if not r or r.user_id!=p.user_id or r.status!="ACTIVE": raise ValueError("TRAVELER_NOT_FOUND")
            doc=decrypt_secret(r.document_ciphertext) if r.document_ciphertext else None
            masked=("*"*max(0,len(doc)-4)+doc[-4:]) if doc else None
            return {"traveler_id":r.traveler_id,"full_name":r.full_name,"date_of_birth":r.date_of_birth,"nationality":r.nationality,"document_type":r.document_type,"document_number_masked":masked,"is_primary":r.is_primary}
    def list_travelers(self,p):
        with SessionLocal() as s:
            ids=[r.traveler_id for r in s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id==p.user_id,TravelerProfileRow.status=="ACTIVE").order_by(TravelerProfileRow.is_primary.desc(),TravelerProfileRow.created_at)).all()]
        return [self.get_traveler(p,x) for x in ids]
    def delete_traveler(self,p,tid):
        with SessionLocal() as s:
            r=s.get(TravelerProfileRow,tid)
            if not r or r.user_id!=p.user_id: raise ValueError("TRAVELER_NOT_FOUND")
            r.status="DELETED"; r.updated_at=now(); s.commit()
    def tokenize_payment_method(self,p,pan,expiry_month,expiry_year,cvc=None,make_default=False):
        # Sprint 1Y uses a deterministic PSP simulator: raw PAN/CVC never persist.
        digits="".join(x for x in pan if x.isdigit())
        if len(digits)<12 or len(digits)>19: raise ValueError("INVALID_CARD")
        provider_token="psptok_"+hashlib.sha256((digits+str(expiry_month)+str(expiry_year)).encode()).hexdigest()[:32]
        fingerprint=hashlib.sha256(digits.encode()).hexdigest()
        brand="VISA" if digits.startswith("4") else "MASTERCARD" if digits.startswith(("5","2")) else "CARD"
        t=now(); pmid=new_id("pm")
        with SessionLocal() as s:
            existing=s.scalar(select(ConsumerPaymentMethodRow).where(ConsumerPaymentMethodRow.user_id==p.user_id,ConsumerPaymentMethodRow.fingerprint==fingerprint,ConsumerPaymentMethodRow.status=="ACTIVE"))
            if existing: return self.payment_method(p,existing.payment_method_id)
            if make_default: s.execute(update(ConsumerPaymentMethodRow).where(ConsumerPaymentMethodRow.user_id==p.user_id).values(is_default=False))
            count=len(s.scalars(select(ConsumerPaymentMethodRow).where(ConsumerPaymentMethodRow.user_id==p.user_id,ConsumerPaymentMethodRow.status=="ACTIVE")).all())
            r=ConsumerPaymentMethodRow(payment_method_id=pmid,user_id=p.user_id,provider="MOCK_PSP_TOKENIZATION",provider_token_ciphertext=encrypt_secret(provider_token),fingerprint=fingerprint,brand=brand,last4=digits[-4:],expiry_month=expiry_month,expiry_year=expiry_year,is_default=(make_default or count==0),status="ACTIVE",created_at=t,updated_at=t)
            s.add(r); s.commit()
        return self.payment_method(p,pmid)
    def payment_method(self,p,pmid):
        with SessionLocal() as s:
            r=s.get(ConsumerPaymentMethodRow,pmid)
            if not r or r.user_id!=p.user_id or r.status!="ACTIVE": raise ValueError("PAYMENT_METHOD_NOT_FOUND")
            return {"payment_method_id":r.payment_method_id,"provider":r.provider,"brand":r.brand,"last4":r.last4,"expiry_month":r.expiry_month,"expiry_year":r.expiry_year,"is_default":r.is_default,"status":r.status}
    def payment_token(self,p,pmid):
        with SessionLocal() as s:
            r=s.get(ConsumerPaymentMethodRow,pmid)
            if not r or r.user_id!=p.user_id or r.status!="ACTIVE": raise ValueError("PAYMENT_METHOD_NOT_FOUND")
            return decrypt_secret(r.provider_token_ciphertext)
    def list_payment_methods(self,p):
        with SessionLocal() as s:
            ids=[x.payment_method_id for x in s.scalars(select(ConsumerPaymentMethodRow).where(ConsumerPaymentMethodRow.user_id==p.user_id,ConsumerPaymentMethodRow.status=="ACTIVE").order_by(ConsumerPaymentMethodRow.is_default.desc(),ConsumerPaymentMethodRow.created_at)).all()]
        return [self.payment_method(p,x) for x in ids]
    def delete_payment_method(self,p,pmid):
        with SessionLocal() as s:
            r=s.get(ConsumerPaymentMethodRow,pmid)
            if not r or r.user_id!=p.user_id: raise ValueError("PAYMENT_METHOD_NOT_FOUND")
            r.status="DELETED"; r.provider_token_ciphertext=encrypt_secret("REVOKED"); r.is_default=False; r.updated_at=now(); s.commit()
    def wallet(self,p):
        with SessionLocal() as s:
            w=s.scalar(select(ConsumerWalletRow).where(ConsumerWalletRow.user_id==p.user_id))
        return {"wallet_id":w.wallet_id,"status":w.status,"payment_methods":self.list_payment_methods(p),"note":"GO Wallet stores tokenized payment references; property-scoped Stay Credit remains outside general wallet balance."}

consumer_service=ConsumerService()
