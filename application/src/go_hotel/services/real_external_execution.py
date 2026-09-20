from datetime import datetime,timezone,timedelta
import hashlib,hmac,json,os,uuid
from urllib.parse import urlparse
import httpx
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    ExternalSandboxExecutionAuthorizationRow as Authorization,
    NamedSupplierAdapterBindingRow as AdapterBinding, NamedSupplierAdapterRow as Adapter,
    ExternalSandboxCredentialBindingRow as Credential,
    OmnichannelPaymentIntentRow as Intent, OmnichannelPaymentAttemptRow as Attempt,
    OrderSupplierFulfillmentRow as Fulfillment,
    ExternalTruthOperationRow as TruthOp, ExternalTruthWebhookReceiptRow as TruthWebhook,
    ExternalTruthBankFeedReceiptRow as BankFeedReceipt,
    PspSettlementLineRow as PspLine, BankStatementLineRow as BankLine,
)
from go_hotel.services.omnichannel_payment import omnichannel_payment_service
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service
from go_hotel.services.unified_money_movement import unified_money_movement_service
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement

PAYMENT_OPS={'AUTHORIZE','CAPTURE','REFUND'}
SUPPLIER_OPS={'BOOK','QUERY','CANCEL'}
def now(): return datetime.now(timezone.utc)
def utc(v): return v.replace(tzinfo=timezone.utc) if v and v.tzinfo is None else v
def ident(p): return f'{p}_{uuid.uuid4().hex}'
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r): return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

class RealExternalExecutionService:
    """0100 fail-closed network boundary. A transport response is never a booking/payment fact.
    Only signed callbacks and durable settlement/bank facts can advance 0099 truth states.
    """
    def _authorization(self,s,authorization_id,vertical):
        auth=s.get(Authorization,authorization_id)
        if not auth or auth.state!='APPROVED_EXTERNAL_SANDBOX_ONLY': raise ValueError('APPROVED_EXTERNAL_SANDBOX_AUTHORIZATION_REQUIRED')
        if utc(auth.expires_at)<=now(): raise ValueError('EXTERNAL_SANDBOX_AUTHORIZATION_EXPIRED')
        bid=auth.psp_adapter_binding_id if vertical=='PAYMENT' else auth.hotel_adapter_binding_id
        binding=s.get(AdapterBinding,bid); adapter=s.get(Adapter,binding.named_adapter_id) if binding else None
        if not binding or binding.state!='BOUND_AND_ATTESTED' or not adapter or adapter.vertical!=vertical: raise ValueError('ATTESTED_ADAPTER_BINDING_REQUIRED')
        credential=s.get(Credential,binding.credential_binding_id)
        if not credential or credential.access_test_state!='PASS': raise ValueError('VERIFIED_EXTERNAL_CREDENTIAL_BINDING_REQUIRED')
        return auth,binding,adapter,credential
    def _secret(self,credential):
        ref=credential.secret_reference or ''
        if not ref.startswith('env://'): raise ValueError('RUNTIME_SECRET_RESOLVER_NOT_CONFIGURED_FOR_CREDENTIAL_REFERENCE')
        key=ref[6:]
        secret=os.getenv(key)
        if not secret: raise ValueError('RUNTIME_EXTERNAL_SECRET_NOT_AVAILABLE')
        return secret
    def _endpoint(self,binding):
        url=binding.endpoint_reference
        parsed=urlparse(url)
        if parsed.scheme!='https' and not (parsed.scheme=='http' and os.getenv('GO_ALLOW_HTTP_EXTERNAL_SANDBOX')=='1'):
            raise ValueError('HTTPS_EXTERNAL_SANDBOX_ENDPOINT_REQUIRED')
        if not parsed.netloc: raise ValueError('VALID_EXTERNAL_SANDBOX_ENDPOINT_REQUIRED')
        return url
    def _network_enabled(self):
        if os.getenv('GO_EXTERNAL_SANDBOX_NETWORK_ENABLED')!='1': raise ValueError('REAL_EXTERNAL_NETWORK_EXECUTION_NOT_ENABLED')
    def _post_json(self,url,payload,headers):
        timeout=float(os.getenv('GO_EXTERNAL_SANDBOX_TIMEOUT_SECONDS','10'))
        with httpx.Client(timeout=timeout,follow_redirects=False) as client:
            return client.post(url,json=payload,headers=headers)
    def _signed_headers(self,secret,idempotency_key,payload):
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'),default=str).encode()
        sig=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
        return {'X-GO-Idempotency-Key':idempotency_key,'X-GO-Signature-SHA256':sig,'Content-Type':'application/json'}
    def execute_payment(self,intent_id,authorization_id,b):
        operation=b.get('operation','AUTHORIZE')
        if operation not in PAYMENT_OPS: raise ValueError('UNSUPPORTED_REAL_PAYMENT_OPERATION')
        self._network_enabled()
        with SessionLocal() as s:
            old=s.scalar(select(TruthOp).where(TruthOp.idempotency_key==b['idempotency_key']))
            if old:return out(old)
            auth,binding,adapter,credential=self._authorization(s,authorization_id,'PAYMENT')
            intent=s.scalar(select(Intent).where(Intent.payment_intent_id==intent_id).with_for_update())
            if not intent: raise ValueError('PAYMENT_INTENT_NOT_FOUND')
            inflight=s.scalar(select(TruthOp).where(TruthOp.payment_intent_id==intent_id,TruthOp.operation_type==operation,TruthOp.state.in_(['DISPATCHING','TRANSPORT_ACCEPTED_PENDING_SIGNED_CALLBACK','UNKNOWN_EXTERNAL_STATE'])).with_for_update())
            if inflight: raise ValueError('EXTERNAL_PAYMENT_OPERATION_RECONCILIATION_REQUIRED')
            if operation=='AUTHORIZE' and intent.state!='READY': raise ValueError('PAYMENT_INTENT_NOT_READY_FOR_EXTERNAL_AUTHORIZE')
            if operation in {'CAPTURE','REFUND'} and intent.state!='SUCCEEDED': raise ValueError('PAYMENT_SUCCESS_REQUIRED_FOR_EXTERNAL_MONEY_OPERATION')
            if 'amount_minor' in b and int(b['amount_minor'])!=intent.amount_minor: raise ValueError('EXTERNAL_PAYMENT_PARTIAL_AMOUNT_NOT_SUPPORTED')
            movements=s.scalars(select(Movement).where(Movement.root_payment_intent_id==intent_id,Movement.state=='CONFIRMED').with_for_update()).all()
            authorized=sum(x.amount_minor for x in movements if x.movement_type=='AUTHORIZATION');captured=sum(x.amount_minor for x in movements if x.movement_type=='CAPTURE');refunded=sum(x.amount_minor for x in movements if x.movement_type=='REFUND')
            if operation=='CAPTURE' and authorized<intent.amount_minor: raise ValueError('EXTERNAL_CAPTURE_REQUIRES_CONFIRMED_AUTHORIZATION')
            if operation=='CAPTURE' and captured+intent.amount_minor>authorized: raise ValueError('EXTERNAL_CAPTURE_EXCEEDS_CONFIRMED_AUTHORIZATION')
            if operation=='REFUND' and captured<intent.amount_minor: raise ValueError('EXTERNAL_REFUND_REQUIRES_CONFIRMED_CAPTURE')
            if operation=='REFUND' and refunded+intent.amount_minor>captured: raise ValueError('EXTERNAL_REFUND_EXCEEDS_CONFIRMED_CAPTURE')
            if operation=='AUTHORIZE':
                active=s.scalar(select(Attempt).where(Attempt.payment_intent_id==intent_id,Attempt.state.in_(['PROCESSING','UNKNOWN_EXTERNAL_STATE'])).with_for_update())
                if active:raise ValueError('ACTIVE_OR_UNKNOWN_ATTEMPT_BLOCKS_RESEND')
                n=(s.scalar(select(func.max(Attempt.attempt_no)).where(Attempt.payment_intent_id==intent_id)) or 0)+1
                attempt=Attempt(payment_attempt_id=ident('opa'),payment_intent_id=intent_id,channel=intent.selected_channel,attempt_no=n,external_operation_id=None,channel_idempotency_key=b['idempotency_key'],state='PROCESSING',external_invoked=True,created_at=now(),updated_at=now());s.add(attempt);s.flush()
            else: attempt=None
            payload={'contract_version':'GO_EXTERNAL_TRUTH_V1','vertical':'PAYMENT','operation':operation,'payment_intent_id':intent_id,'payment_attempt_id':attempt.payment_attempt_id if attempt else None,'amount_minor':intent.amount_minor,'currency':intent.currency,'payer_id':intent.payer_id,'payee_id':intent.payee_id,'idempotency_key':b['idempotency_key']}
            secret=self._secret(credential);url=self._endpoint(binding);headers=self._signed_headers(secret,b['idempotency_key'],payload);req_hash=digest(payload)
            # Durable dispatch claim commits before any network boundary. A process
            # death after this point is reconciliation-only, never permission to resend.
            record=TruthOp(external_truth_operation_id=ident('eto'),execution_authorization_id=authorization_id,payment_intent_id=intent_id,supplier_fulfillment_id=None,vertical='PAYMENT',operation_type=operation,idempotency_key=b['idempotency_key'],endpoint_reference=url,external_operation_id=None,http_status=None,state='DISPATCHING',request_hash=req_hash,response_hash=None,evidence_reference=None,started_at=now(),completed_at=None)
            s.add(record);s.flush();operation_id=record.external_truth_operation_id;s.commit()
        try:
            resp=self._post_json(url,payload,headers);body=resp.json() if resp.content else {};status=resp.status_code;ext=body.get('external_operation_id') or body.get('transaction_id')
            transport_state='TRANSPORT_ACCEPTED_PENDING_SIGNED_CALLBACK' if 200<=status<300 and ext else ('UNKNOWN_EXTERNAL_STATE' if 200<=status<300 else 'TRANSPORT_REJECTED')
        except (httpx.TimeoutException,httpx.TransportError) as e:
            body={'transport_error':type(e).__name__};status=None;ext=None;transport_state='UNKNOWN_EXTERNAL_STATE'
        with SessionLocal() as s:
            record=s.scalar(select(TruthOp).where(TruthOp.external_truth_operation_id==operation_id).with_for_update())
            if not record or record.state!='DISPATCHING':raise ValueError('EXTERNAL_PAYMENT_DISPATCH_CLAIM_CHANGED_RECONCILIATION_REQUIRED')
            record.external_operation_id=ext;record.http_status=status;record.state=transport_state;record.response_hash=digest(body);record.evidence_reference=body.get('evidence_reference');record.completed_at=now()
            if attempt:
                a=s.scalar(select(Attempt).where(Attempt.payment_attempt_id==attempt.payment_attempt_id).with_for_update());i=s.scalar(select(Intent).where(Intent.payment_intent_id==intent_id).with_for_update())
                a.external_operation_id=ext;a.state='UNKNOWN_EXTERNAL_STATE' if transport_state=='UNKNOWN_EXTERNAL_STATE' else ('PROCESSING' if transport_state.startswith('TRANSPORT_ACCEPTED') else 'FAILED');a.updated_at=now()
                if transport_state=='UNKNOWN_EXTERNAL_STATE':i.state='UNKNOWN_EXTERNAL_STATE';i.updated_at=now()
            elif transport_state=='UNKNOWN_EXTERNAL_STATE':
                i=s.scalar(select(Intent).where(Intent.payment_intent_id==intent_id).with_for_update());i.state='UNKNOWN_EXTERNAL_STATE';i.updated_at=now()
            result=out(record);s.commit()
        if transport_state in {'UNKNOWN_EXTERNAL_STATE','TRANSPORT_ACCEPTED_PENDING_SIGNED_CALLBACK'}:
            from go_hotel.services.production_connector_runtime import production_connector_runtime_service
            result['command_center_reconciliation']=production_connector_runtime_service.admit_payment_unknown(operation_id)
        return result
    def execute_supplier(self,fulfillment_id,authorization_id,b):
        operation=b.get('operation','BOOK')
        if operation not in SUPPLIER_OPS:raise ValueError('UNSUPPORTED_REAL_SUPPLIER_OPERATION')
        self._network_enabled()
        with SessionLocal() as s:
            old=s.scalar(select(TruthOp).where(TruthOp.idempotency_key==b['idempotency_key']))
            if old:return out(old)
            auth,binding,adapter,credential=self._authorization(s,authorization_id,'HOTEL')
            f=s.scalar(select(Fulfillment).where(Fulfillment.order_supplier_fulfillment_id==fulfillment_id).with_for_update())
            if not f:raise ValueError('SUPPLIER_FULFILLMENT_NOT_FOUND')
            if operation=='BOOK' and f.state!='CAPTURE_CONFIRMED_READY_FOR_SUPPLIER':raise ValueError('CAPTURE_CONFIRMED_READY_FOR_SUPPLIER_REQUIRED')
            payload={'contract_version':'GO_EXTERNAL_TRUTH_V1','vertical':'HOTEL','operation':operation,'supplier_fulfillment_id':fulfillment_id,'business_type':f.business_type,'business_id':f.business_id,'supplier_id':f.supplier_id,'supplier_idempotency_key':f.supplier_idempotency_key,'idempotency_key':b['idempotency_key'],'facts':b.get('facts',{})}
            secret=self._secret(credential);url=self._endpoint(binding);headers=self._signed_headers(secret,b['idempotency_key'],payload);req_hash=digest(payload)
        try:
            resp=self._post_json(url,payload,headers);body=resp.json() if resp.content else {};status=resp.status_code;ext=body.get('external_operation_id') or body.get('booking_operation_id');transport_state='TRANSPORT_ACCEPTED_PENDING_SIGNED_CALLBACK' if 200<=status<300 else 'TRANSPORT_REJECTED'
        except (httpx.TimeoutException,httpx.TransportError) as e:
            body={'transport_error':type(e).__name__};status=None;ext=None;transport_state='UNKNOWN_EXTERNAL_STATE'
        with SessionLocal() as s:
            f=s.scalar(select(Fulfillment).where(Fulfillment.order_supplier_fulfillment_id==fulfillment_id).with_for_update())
            f.external_operation_id=ext or f.external_operation_id;f.state='UNKNOWN_EXTERNAL_STATE' if transport_state=='UNKNOWN_EXTERNAL_STATE' else ('SUPPLIER_MUTATION_SENT' if transport_state.startswith('TRANSPORT_ACCEPTED') else 'SUPPLIER_FAILED');f.updated_at=now()
            r=TruthOp(external_truth_operation_id=ident('eto'),execution_authorization_id=authorization_id,payment_intent_id=f.payment_intent_id,supplier_fulfillment_id=fulfillment_id,vertical='HOTEL',operation_type=operation,idempotency_key=b['idempotency_key'],endpoint_reference=url,external_operation_id=ext,http_status=status,state=transport_state,request_hash=req_hash,response_hash=digest(body),evidence_reference=body.get('evidence_reference'),started_at=now(),completed_at=now());s.add(r);s.commit();return out(r)
    def _verify_callback(self,s,operation_id,delivery_id,payload,signature):
        old=s.scalar(select(TruthWebhook).where(TruthWebhook.delivery_id==delivery_id))
        if old:
            if old.payload_hash!=digest(payload):
                raise ValueError('EXTERNAL_CALLBACK_DELIVERY_PAYLOAD_CONFLICT')
            return None,old
        op=s.get(TruthOp,operation_id)
        if not op:raise ValueError('EXTERNAL_TRUTH_OPERATION_NOT_FOUND')
        auth,binding,adapter,credential=self._authorization(s,op.execution_authorization_id,op.vertical)
        secret=self._secret(credential);raw=json.dumps(payload,sort_keys=True,separators=(',',':'),default=str).encode();expected=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature):raise ValueError('EXTERNAL_CALLBACK_SIGNATURE_INVALID')
        return op,None
    def payment_callback(self,operation_id,delivery_id,payload,signature):
        """Commit a verified receipt, payment state, and money movement as one fact."""
        with SessionLocal() as s:
            op,old=self._verify_callback(s,operation_id,delivery_id,payload,signature)
            if old:return {'duplicate':True,'receipt':out(old)}
            if op.vertical!='PAYMENT':raise ValueError('PAYMENT_OPERATION_REQUIRED')
            required=('state','operation','amount_minor','currency','external_operation_id','occurred_at')
            if any(payload.get(x) in (None,'') for x in required):raise ValueError('EXTERNAL_PAYMENT_CALLBACK_FACTS_REQUIRED')
            try:
                occurred_at=datetime.fromisoformat(str(payload['occurred_at']).replace('Z','+00:00'))
            except ValueError as exc:
                raise ValueError('EXTERNAL_PAYMENT_CALLBACK_TIMESTAMP_INVALID') from exc
            occurred_at=utc(occurred_at)
            if occurred_at<now()-timedelta(hours=24) or occurred_at>now()+timedelta(minutes=5):
                raise ValueError('EXTERNAL_PAYMENT_CALLBACK_OUTSIDE_REPLAY_WINDOW')
            i=s.scalar(select(Intent).where(Intent.payment_intent_id==op.payment_intent_id).with_for_update())
            if not i:raise ValueError('PAYMENT_INTENT_NOT_FOUND')
            if payload['operation']!=op.operation_type:raise ValueError('EXTERNAL_PAYMENT_CALLBACK_OPERATION_MISMATCH')
            if int(payload['amount_minor'])!=i.amount_minor:raise ValueError('EXTERNAL_PAYMENT_CALLBACK_AMOUNT_MISMATCH')
            if payload['currency']!=i.currency:raise ValueError('EXTERNAL_PAYMENT_CALLBACK_CURRENCY_MISMATCH')
            callback_operation_id=payload['external_operation_id']
            if op.external_operation_id and callback_operation_id!=op.external_operation_id:raise ValueError('EXTERNAL_PAYMENT_CALLBACK_OPERATION_REFERENCE_MISMATCH')
            mapped={'SUCCEEDED':'SUCCEEDED','FAILED':'FAILED','PENDING':'UNKNOWN_EXTERNAL_STATE'}.get(payload['state'])
            if not mapped:raise ValueError('INVALID_EXTERNAL_PAYMENT_STATE')
            terminal=f'CALLBACK_{mapped}'
            if op.state in {'CALLBACK_SUCCEEDED','CALLBACK_FAILED'}:
                if op.state!=terminal:raise ValueError('EXTERNAL_PAYMENT_TERMINAL_STATE_CONFLICT')
            else:
                op.state=terminal
            if op.operation_type=='AUTHORIZE':
                a=s.scalar(select(Attempt).where(Attempt.payment_intent_id==op.payment_intent_id,Attempt.channel_idempotency_key==op.idempotency_key).with_for_update())
                if not a:raise ValueError('EXTERNAL_PAYMENT_ATTEMPT_NOT_FOUND')
                omnichannel_payment_service._transition(s,a,i,mapped,callback_operation_id)
            r=TruthWebhook(external_truth_webhook_receipt_id=ident('etw'),external_truth_operation_id=operation_id,source_vertical='PAYMENT',delivery_id=delivery_id,signature_scheme='HMAC_SHA256',signature_verified=True,supplier_state=mapped,payload_hash=digest(payload),received_at=now())
            s.add(r);s.flush()
            movement=None
            if mapped=='SUCCEEDED':
                evidence=[f'external-webhook://{delivery_id}']
                if op.operation_type=='AUTHORIZE':
                    movement=unified_money_movement_service.record_verified_external_fact_in_session(s,op.payment_intent_id,{'movement_type':'AUTHORIZATION','amount_minor':int(payload['amount_minor']),'evidence':evidence,'mode':'EXTERNAL_CERTIFIED_FACT','external_reference':callback_operation_id},'ext-auth:'+op.idempotency_key,'p0-0100',r.external_truth_webhook_receipt_id)
                elif op.operation_type=='CAPTURE':
                    parent=s.scalar(select(Movement).where(Movement.root_payment_intent_id==op.payment_intent_id,Movement.movement_type=='AUTHORIZATION',Movement.state=='CONFIRMED').order_by(Movement.created_at.desc()).with_for_update())
                    if not parent:raise ValueError('CONFIRMED_EXTERNAL_AUTHORIZATION_REQUIRED_BEFORE_CAPTURE')
                    movement=unified_money_movement_service.record_verified_external_fact_in_session(s,op.payment_intent_id,{'movement_type':'CAPTURE','parent_movement_id':parent.money_movement_id,'amount_minor':int(payload['amount_minor']),'evidence':evidence,'mode':'EXTERNAL_CERTIFIED_FACT','external_reference':callback_operation_id},'ext-cap:'+op.idempotency_key,'p0-0100',r.external_truth_webhook_receipt_id)
                elif op.operation_type=='REFUND':
                    parent=s.scalar(select(Movement).where(Movement.root_payment_intent_id==op.payment_intent_id,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED').order_by(Movement.created_at.desc()).with_for_update())
                    if not parent:raise ValueError('CONFIRMED_EXTERNAL_CAPTURE_REQUIRED_BEFORE_REFUND')
                    movement=unified_money_movement_service.record_verified_external_fact_in_session(s,op.payment_intent_id,{'movement_type':'REFUND','parent_movement_id':parent.money_movement_id,'amount_minor':int(payload['amount_minor']),'evidence':evidence,'mode':'EXTERNAL_CERTIFIED_FACT','external_reference':callback_operation_id},'ext-ref:'+op.idempotency_key,'p0-0100',r.external_truth_webhook_receipt_id)
            receipt=out(r);intent=out(i)
            s.commit()
            return {'duplicate':False,'receipt':receipt,'intent':intent,'money_movement':movement}
    def supplier_callback(self,operation_id,delivery_id,payload,signature):
        with SessionLocal() as s:
            op,old=self._verify_callback(s,operation_id,delivery_id,payload,signature)
            if old:return {'duplicate':True,'receipt':out(old)}
            if op.vertical!='HOTEL':raise ValueError('HOTEL_SUPPLIER_OPERATION_REQUIRED')
            state={'CONFIRMED':'SUPPLIER_CONFIRMED','FAILED':'SUPPLIER_FAILED','PENDING':'UNKNOWN_EXTERNAL_STATE'}.get(payload.get('state'))
            if not state:raise ValueError('INVALID_SUPPLIER_CALLBACK_STATE')
            r=TruthWebhook(external_truth_webhook_receipt_id=ident('etw'),external_truth_operation_id=operation_id,source_vertical='HOTEL',delivery_id=delivery_id,signature_scheme='HMAC_SHA256',signature_verified=True,supplier_state=state,payload_hash=digest(payload),received_at=now());s.add(r);s.commit()
        result=order_supplier_fulfillment_service.record_supplier_fact(op.supplier_fulfillment_id,{'state':state,'external_operation_id':payload.get('external_operation_id') or op.external_operation_id,'supplier_confirmation_reference':payload.get('supplier_confirmation_reference'),'evidence_reference':f'external-webhook://{delivery_id}'})
        return {'duplicate':False,'receipt':out(r),'result':result}
    def psp_settlement_callback(self,operation_id,delivery_id,payload,signature):
        with SessionLocal() as s:
            op,old=self._verify_callback(s,operation_id,delivery_id,payload,signature)
            if old:return {'duplicate':True,'receipt':out(old)}
            if op.vertical!='PAYMENT':raise ValueError('PAYMENT_OPERATION_REQUIRED')
            if op.operation_type!='CAPTURE':raise ValueError('PSP_SETTLEMENT_CAPTURE_OPERATION_REQUIRED')
            required=('external_transaction_id','amount_minor','currency','evidence_reference','occurred_at')
            if any(payload.get(x) in (None,'') for x in required):raise ValueError('PSP_SETTLEMENT_FACT_REQUIRED')
            intent=s.get(Intent,op.payment_intent_id)
            if not intent or int(payload['amount_minor'])!=intent.amount_minor or payload['currency']!=intent.currency:
                raise ValueError('PSP_SETTLEMENT_PAYMENT_FACT_MISMATCH')
            capture=s.scalar(select(Movement).where(
                Movement.root_payment_intent_id==op.payment_intent_id,
                Movement.movement_type=='CAPTURE',
                Movement.state=='CONFIRMED',
            ))
            if not capture:raise ValueError('PSP_SETTLEMENT_CONFIRMED_CAPTURE_REQUIRED')
            r=TruthWebhook(external_truth_webhook_receipt_id=ident('etw'),external_truth_operation_id=operation_id,source_vertical='PAYMENT',delivery_id=delivery_id,signature_scheme='HMAC_SHA256',signature_verified=True,supplier_state='SETTLEMENT_FACT_RECEIVED',payload_hash=digest(payload),received_at=now());s.add(r);s.flush()
            line=omnichannel_payment_service.ingest_psp_line_in_session(s,op.payment_intent_id,payload)
            receipt=out(r);s.commit()
        return {'duplicate':False,'receipt':receipt,'psp_line':line}
    def bank_feed(self,provider_key,delivery_id,payload,signature):
        key=os.getenv(f'GO_BANK_FEED_KEY_{provider_key.upper()}')
        if not key:raise ValueError('BANK_FEED_SIGNATURE_KEY_NOT_CONFIGURED')
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'),default=str).encode();expected=hmac.new(key.encode(),raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature):raise ValueError('BANK_FEED_SIGNATURE_INVALID')
        payload_hash=digest(payload)
        with SessionLocal() as s:
            old=s.scalar(select(BankFeedReceipt).where(BankFeedReceipt.delivery_id==delivery_id).with_for_update())
            if old:
                if old.payload_hash!=payload_hash:raise ValueError('BANK_FEED_DELIVERY_PAYLOAD_CONFLICT')
                return {'duplicate':True,'receipt':out(old)}
            lines=[omnichannel_payment_service.ingest_bank_line_in_session(s,line) for line in payload.get('lines',[])]
            r=BankFeedReceipt(bank_feed_receipt_id=ident('bfr'),provider_key=provider_key,delivery_id=delivery_id,signature_verified=True,payload_hash=payload_hash,imported_line_count=len(lines),evidence_reference=payload.get('evidence_reference',f'bank-feed://{provider_key}/{delivery_id}'),received_at=now());s.add(r);s.flush()
            receipt=out(r);s.commit();return {'duplicate':False,'receipt':receipt,'lines':lines}
    def reconcile(self,intent_id,external_transaction_id):
        return omnichannel_payment_service.reconcile(intent_id,{'external_transaction_id':external_transaction_id})
    def readiness(self):
        return {'network_enabled':os.getenv('GO_EXTERNAL_SANDBOX_NETWORK_ENABLED')=='1','postgres_test_database_configured':bool(os.getenv('POSTGRES_TEST_DATABASE_URL')),'real_supplier_connected':False,'real_psp_connected':False,'certified_external_sandbox':False,'production_live':False}

real_external_execution_service=RealExternalExecutionService()
