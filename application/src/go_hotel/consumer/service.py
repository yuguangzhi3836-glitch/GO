from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from sqlalchemy import select, update
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (IdentityUserRow, ConsumerProfileRow, TravelerProfileRow,
    ConsumerPaymentMethodRow, ConsumerWalletRow, ConsumerWalletLedgerRow, OrderRow,
    PaymentRow, PaymentOrchestrationRow, EventRow)
from go_hotel.security.service import identity_service, Principal
from go_hotel.security.crypto import encrypt_secret, decrypt_secret
from go_hotel.domain.models import new_id
from go_hotel.core.config import settings


def now(): return datetime.now(timezone.utc)
def go_id_for(user_id:str): return "GO" + hashlib.sha256(user_id.encode()).hexdigest()[:12].upper()

class ConsumerService:
    def register(self,email:str,password:str,display_name:str|None=None,phone:str|None=None):
        email=email.strip().lower()
        with SessionLocal() as s:
            if s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==email)):
                raise ValueError("EMAIL_ALREADY_REGISTERED")
        user_id=identity_service.create_user(email,password,"CONSUMER",None,["CONSUMER"])
        t=now()
        with SessionLocal() as s:
            p=ConsumerProfileRow(user_id=user_id,go_id=go_id_for(user_id),email=email,display_name=display_name,phone_ciphertext=encrypt_secret(phone) if phone else None,locale="zh-CN",status="ACTIVE",created_at=t,updated_at=t)
            local_env=settings.app_env.strip().lower() in {"local","test","demo"}
            initial_cash=int(settings.local_wallet_initial_cash_minor) if local_env else 0
            if initial_cash < 0:
                raise ValueError("LOCAL_WALLET_INITIAL_CASH_INVALID")
            w=ConsumerWalletRow(wallet_id=new_id("wal"),user_id=user_id,status="ACTIVE",cash_balance_minor=initial_cash,created_at=t,updated_at=t)
            s.add_all([p,w])
            if initial_cash:
                s.add(ConsumerWalletLedgerRow(wallet_ledger_id=new_id("wle"),wallet_id=w.wallet_id,
                    user_id=user_id,order_id=None,entry_type="LOCAL_INITIAL_CASH_CREDIT",
                    amount_minor=initial_cash,balance_after_minor=initial_cash,currency="CNY",
                    idempotency_key=f"local-initial-wallet-cash:{user_id}:v1",created_at=t))
            s.commit()
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
    def authorize_wallet_hotel_payment(self, p, order_id: str, amount_minor: int,
                                       currency: str, idempotency_key: str):
        """Reserve spendable wallet cash for a hotel order; no external payment channel is called."""
        if currency != "CNY" or type(amount_minor) is not int or amount_minor <= 0:
            raise ValueError("WALLET_PAYMENT_AMOUNT_INVALID")
        from go_hotel.repositories.sql import repo
        from go_hotel.services.consistency import booking_consistency_guard
        order_view = repo.get_order(order_id)
        prebook = repo.get_prebook(order_view.prebook_id) if order_view else None
        offer = repo.get_offer(prebook.offer_id) if prebook else None
        if not order_view or not prebook or not offer:
            raise ValueError("PREBOOK_CONSISTENCY_DATA_MISSING")
        booking_consistency_guard.assert_before_payment(order_view, prebook, offer)
        operation_id = "wallet-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:56]
        t = now()
        with SessionLocal.begin() as s:
            order = s.scalar(select(OrderRow).where(OrderRow.order_id == order_id).with_for_update())
            if not order or order.account_id != p.user_id:
                raise ValueError("ORDER_NOT_FOUND")
            if order.total_amount_minor != amount_minor or order.currency != currency:
                raise ValueError("ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED")
            existing = s.scalar(select(PaymentRow).where(PaymentRow.external_operation_id == operation_id))
            if existing:
                if existing.order_id != order_id or existing.amount_minor != amount_minor or existing.currency != currency:
                    raise ValueError("WALLET_PAYMENT_IDEMPOTENCY_CONFLICT")
                return {"payment_id": existing.payment_id, "status": existing.status,
                        "amount_minor": existing.amount_minor, "currency": existing.currency}
            if order.status == "PAYMENT_AUTHORIZED":
                prior = s.scalar(select(PaymentRow).where(
                    PaymentRow.order_id == order_id, PaymentRow.payment_type == "GO_WALLET",
                    PaymentRow.status == "AUTHORIZED").with_for_update())
                if prior and prior.amount_minor == amount_minor and prior.currency == currency:
                    return {"payment_id": prior.payment_id, "status": prior.status,
                            "amount_minor": prior.amount_minor, "currency": prior.currency}
            if order.status != "PAYMENT_PENDING":
                raise ValueError("ORDER_NOT_PAYABLE")
            wallet = s.scalar(select(ConsumerWalletRow).where(
                ConsumerWalletRow.user_id == p.user_id).with_for_update())
            if not wallet or wallet.status != "ACTIVE":
                raise ValueError("WALLET_NOT_AVAILABLE")
            if wallet.cash_balance_minor < amount_minor:
                raise ValueError("WALLET_INSUFFICIENT_CASH")
            wallet.cash_balance_minor -= amount_minor
            wallet.updated_at = t
            payment_id = new_id("pay")
            s.add(PaymentRow(payment_id=payment_id, order_id=order_id,
                payment_type="GO_WALLET", external_operation_id=operation_id,
                amount_minor=amount_minor, currency=currency, status="AUTHORIZED", created_at=t))
            s.add(ConsumerWalletLedgerRow(wallet_ledger_id=new_id("wle"), wallet_id=wallet.wallet_id,
                user_id=p.user_id, order_id=order_id, entry_type="HOTEL_PAYMENT_DEBIT",
                amount_minor=-amount_minor, balance_after_minor=wallet.cash_balance_minor,
                currency=currency, idempotency_key=f"{operation_id}:debit", created_at=t))
            order.status = "PAYMENT_AUTHORIZED"
            order.version += 1
            order.updated_at = t
            orchestration = s.scalar(select(PaymentOrchestrationRow).where(
                PaymentOrchestrationRow.order_id == order_id).with_for_update())
            if orchestration is None:
                s.add(PaymentOrchestrationRow(orchestration_id=new_id("porch"), order_id=order_id,
                    payment_id=payment_id, phase="AUTHORIZED", compensation_status="NONE",
                    created_at=t, updated_at=t))
            else:
                orchestration.payment_id = payment_id
                orchestration.phase = "AUTHORIZED"
                orchestration.updated_at = t
            s.add(EventRow(event_id=new_id("evt"), event_type="WALLET_PAYMENT_AUTHORIZED",
                aggregate_type="HOTEL_ORDER", aggregate_id=order_id,
                payload={"payment_id": payment_id, "amount_minor": amount_minor,
                         "wallet_id": wallet.wallet_id}, occurred_at=t))
        return {"payment_id": payment_id, "status": "AUTHORIZED",
                "amount_minor": amount_minor, "currency": currency}

    def is_wallet_payment(self, payment_id: str) -> bool:
        with SessionLocal() as s:
            payment = s.get(PaymentRow, payment_id)
            return bool(payment and payment.payment_type == "GO_WALLET")

    def release_wallet_hotel_payment(self, payment_id: str):
        t = now()
        with SessionLocal.begin() as s:
            payment = s.scalar(select(PaymentRow).where(
                PaymentRow.payment_id == payment_id).with_for_update())
            if not payment or payment.payment_type != "GO_WALLET":
                return False
            if payment.status == "VOIDED":
                return True
            if payment.status != "AUTHORIZED":
                raise ValueError("WALLET_PAYMENT_NOT_VOIDABLE")
            wallet = s.scalar(select(ConsumerWalletRow).where(
                ConsumerWalletRow.user_id == s.get(OrderRow, payment.order_id).account_id).with_for_update())
            if not wallet:
                raise ValueError("WALLET_NOT_AVAILABLE")
            wallet.cash_balance_minor += payment.amount_minor
            wallet.updated_at = t
            payment.status = "VOIDED"
            s.add(ConsumerWalletLedgerRow(wallet_ledger_id=new_id("wle"), wallet_id=wallet.wallet_id,
                user_id=wallet.user_id, order_id=payment.order_id, entry_type="HOTEL_PAYMENT_RELEASE",
                amount_minor=payment.amount_minor, balance_after_minor=wallet.cash_balance_minor,
                currency=payment.currency,
                idempotency_key=f"wallet-release:{payment_id}", created_at=t))
        return True
    def payment_method(self,p,pmid):
        with SessionLocal() as s:
            r=s.get(ConsumerPaymentMethodRow,pmid)
            if not r or r.user_id!=p.user_id or r.status!="ACTIVE": raise ValueError("PAYMENT_METHOD_NOT_FOUND")
            result={"payment_method_id":r.payment_method_id,"provider":r.provider,"brand":r.brand,"last4":r.last4,"expiry_month":r.expiry_month,"expiry_year":r.expiry_year,"is_default":r.is_default,"status":r.status}
            return result
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
            was_default=r.is_default
            r.status="DELETED"; r.provider_token_ciphertext=encrypt_secret("REVOKED"); r.is_default=False; r.updated_at=now()
            if was_default:
                replacement=s.scalar(select(ConsumerPaymentMethodRow).where(
                    ConsumerPaymentMethodRow.user_id==p.user_id,
                    ConsumerPaymentMethodRow.status=="ACTIVE",
                    ConsumerPaymentMethodRow.payment_method_id!=pmid).order_by(ConsumerPaymentMethodRow.created_at))
                if replacement: replacement.is_default=True; replacement.updated_at=now()
            s.commit()
    def set_default_payment_method(self,p,pmid):
        with SessionLocal.begin() as s:
            r=s.get(ConsumerPaymentMethodRow,pmid)
            if not r or r.user_id!=p.user_id or r.status!="ACTIVE": raise ValueError("PAYMENT_METHOD_NOT_FOUND")
            s.execute(update(ConsumerPaymentMethodRow).where(
                ConsumerPaymentMethodRow.user_id==p.user_id).values(is_default=False))
            r.is_default=True; r.updated_at=now()
        return self.payment_method(p,pmid)
    def wallet(self,p):
        with SessionLocal() as s:
            w=s.scalar(select(ConsumerWalletRow).where(ConsumerWalletRow.user_id==p.user_id))
        methods=[m for m in self.list_payment_methods(p) if m.get("provider")!="GO_SIMULATOR"]
        return {"wallet_id":w.wallet_id,"status":w.status,
            "cash_balance_minor":int(w.cash_balance_minor),
            "cashback_balance_minor":int(w.cashback_balance_minor),
            "currency":"CNY","bank_card_count":len(methods),
            "payment_methods":methods,
            "note":"酒店订单从钱包现金余额扣款；返现单独展示；银行卡记录不参与本次钱包余额扣款。"}

consumer_service=ConsumerService()
