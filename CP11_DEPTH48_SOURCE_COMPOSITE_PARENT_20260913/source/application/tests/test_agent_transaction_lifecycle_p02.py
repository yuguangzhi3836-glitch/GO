import asyncio,time
import pytest
from go_hotel.agent_gateway.a2a import A2AAdapter
from go_hotel.agent_gateway.auth import signed_agent_authorizer
from go_hotel.agent_gateway.contracts import (AgentContext,AgentProtocol,CommitRequest,ExpireRequest,LifecycleExecuteRequest,LifecycleQuoteRequest,OfferRequest,PaymentRequest,ReserveRequest)
from go_hotel.agent_gateway.lifecycle_core import GoTransactionCore
from go_hotel.agent_gateway.mcp import MCPAdapter
from go_hotel.agent_gateway.service import AgentTransactionGateway
from go_hotel.security.crypto import encode_jwt

SCOPES=frozenset({'offers:read','reserve:write','payments:write','commit:write','orders:read','aftersales:write'})
TRAVELER='lifecycle-owner'
def ctx(protocol=AgentProtocol.REST):return AgentContext('r','t','agent-life',protocol,'manage-travel',SCOPES,TRAVELER)
def run(x):return asyncio.run(x)

def reserve(gw,v,search,booking,key):
 c=ctx();o=run(gw.offers(c,OfferRequest(v,search))).data['items'][0]
 return run(gw.reserve(c,ReserveRequest(o['offer_id'],o['quote_hash'],search,booking,key))).data

def committed(gw,v,search,booking,key):
 c=ctx();r=reserve(gw,v,search,booking,key+'-r');p=run(gw.payment(c,PaymentRequest(r['reserve_id'],r['total_minor'],r['currency'],'pm-life',key+'-p'))).data
 return run(gw.commit(c,CommitRequest(r['reserve_id'],p['payment_truth_id'],key+'-c'))).data

def test_signed_lifecycle_token_requires_manage_travel_and_aftersales_scope():
 now=int(time.time());token=encode_jwt({'typ':'GO_AGENT_ACCESS','iss':'GO_COMMAND_CENTER','aud':'GO_AGENT_GATEWAY','sub':'agent-life','agent_id':'agent-life','protocol':'REST','purposes':['manage-travel'],'scopes':list(SCOPES),'traveler_ref':TRAVELER,'iat':now,'exp':now+600})
 c=signed_agent_authorizer('Bearer '+token,'agent-life','req','trace','manage-travel');assert c.purpose=='manage-travel' and 'aftersales:write' in c.scopes
 with pytest.raises(PermissionError,match='PURPOSE'):signed_agent_authorizer('Bearer '+token,'agent-life','req','trace','book-travel')

def test_release_and_expire_use_native_capacity_truth_and_replay():
 gw=AgentTransactionGateway(GoTransactionCore());search={'origin_station':'SHA','destination_station':'HGH','travel_date':'2026-10-20','currency':'CNY'}
 r=reserve(gw,'RAIL',search,{'passengers':[{'full_name':'A'}],'quantity':1},'rel')
 first=run(gw.release(ctx(),r['reserve_id'],'rel-key')).data;again=run(gw.release(ctx(AgentProtocol.MCP),r['reserve_id'],'rel-key')).data
 assert first==again and first['state']=='RELEASED' and first['capacity_released'] is True
 r2=reserve(gw,'RAIL',search,{'passengers':[{'full_name':'B'}],'quantity':1},'exp');raw=r2['reserve_id'].split(':',1)[1]
 from go_hotel.db.session import SessionLocal
 from go_hotel.db.models import VerticalPaymentDeadlineRow
 from go_hotel.services import vertical_reservation_expiry as expiry
 from go_hotel.autonomy.durable import db_now_ms,digest
 with SessionLocal.begin() as s:
  d=s.get(VerticalPaymentDeadlineRow,('RAIL',raw));d.expires_ms=db_now_ms(s)-1;d.created_ms=d.expires_ms-expiry.HOLD_MS;d.terms_hash=digest(expiry.terms(d))
 out=run(gw.expire(ctx(),ExpireRequest(r2['reserve_id'],'exp-key'))).data;replay=run(gw.expire(ctx(AgentProtocol.A2A),ExpireRequest(r2['reserve_id'],'exp-key'))).data
 assert out==replay and out['state']=='EXPIRED' and out['order_truth']['status']=='CANCELLED'

def test_refund_and_change_execute_against_native_order_and_money_truth():
 gw=AgentTransactionGateway(GoTransactionCore());c=ctx()
 flight=committed(gw,'FLIGHT',{'origin':'SHA','destination':'PEK','departure_date':'2026-10-21','currency':'CNY','adults':1},{'passengers':[{'full_name':'A','type':'ADT'}]},'flt')
 q=run(gw.lifecycle_quote(c,LifecycleQuoteRequest(flight['order_id'],'REFUND',{},'rq'))).data
 x=run(gw.lifecycle_execute(c,LifecycleExecuteRequest(flight['order_id'],'REFUND',q.get('quote_id'),q['quote_hash'],{},None,'rx'))).data
 assert x['order_truth']['status']=='REFUNDED' and x['native_result']['status']=='REFUND_COMPLETED'
 ride=committed(gw,'RIDE',{'pickup':'PVG','dropoff':'Hotel','pickup_at':'2026-10-22T10:00:00','currency':'CNY'},{'passengers':[{'full_name':'A'}]},'ride')
 changes={'new_time':'2026-10-22T11:00:00'};q=run(gw.lifecycle_quote(c,LifecycleQuoteRequest(ride['order_id'],'CHANGE',changes,'cq'))).data
 x=run(gw.lifecycle_execute(c,LifecycleExecuteRequest(ride['order_id'],'CHANGE',q['quote_id'],q['quote_hash'],changes,None,'cx'))).data
 assert x['order_truth']['evidence']['native']['pickup_at']=='2026-10-22T11:00:00'

def test_four_protocol_contexts_share_one_lifecycle_idempotency_fact():
 gw=AgentTransactionGateway(GoTransactionCore());flight=committed(gw,'FLIGHT',{'origin':'SHA','destination':'PEK','departure_date':'2026-10-23','currency':'CNY','adults':1},{'passengers':[{'full_name':'A','type':'ADT'}]},'par');oid=flight['order_id']
 args={'order_id':oid,'action':'REFUND','changes':{},'idempotency_key':'quote-parity'}
 rest=run(gw.lifecycle_quote(ctx(AgentProtocol.REST),LifecycleQuoteRequest(oid,'REFUND',{},'quote-parity'))).data
 mcp=run(MCPAdapter(gw).call_tool(ctx(AgentProtocol.MCP),'go.travel.lifecycle.quote',args)).data
 a2a=run(A2AAdapter(gw).execute(ctx(AgentProtocol.A2A),'lifecycle.quote',args)).data
 apple=run(gw.lifecycle_quote(ctx(AgentProtocol.APPLE_APP_INTENTS),LifecycleQuoteRequest(oid,'REFUND',{},'quote-parity'))).data
 assert rest==mcp==a2a==apple
 execute={'order_id':oid,'action':'REFUND','quote_id':rest.get('quote_id'),'quote_hash':rest['quote_hash'],'changes':{},'payment_method_id':None,'idempotency_key':'exec-parity'}
 r=run(gw.lifecycle_execute(ctx(AgentProtocol.REST),LifecycleExecuteRequest(**execute))).data;m=run(MCPAdapter(gw).call_tool(ctx(AgentProtocol.MCP),'go.travel.lifecycle.execute',execute)).data;a=run(A2AAdapter(gw).execute(ctx(AgentProtocol.A2A),'lifecycle.execute',execute)).data;p=run(gw.lifecycle_execute(ctx(AgentProtocol.APPLE_APP_INTENTS),LifecycleExecuteRequest(**execute))).data
 assert r==m==a==p and r['order_truth']['status']=='REFUNDED'

def test_change_quote_hash_mismatch_fails_closed_before_native_mutation():
 gw=AgentTransactionGateway(GoTransactionCore());c=ctx();ride=committed(gw,'RIDE',{'pickup':'PVG','dropoff':'Hotel','pickup_at':'2026-10-24T10:00:00','currency':'CNY'},{'passengers':[{'full_name':'A'}]},'ride-hash');changes={'new_time':'2026-10-24T12:00:00'}
 q=run(gw.lifecycle_quote(c,LifecycleQuoteRequest(ride['order_id'],'CHANGE',changes,'hash-q'))).data
 with pytest.raises(ValueError,match='CHANGE_QUOTE_RECONFIRM_REQUIRED'):run(gw.lifecycle_execute(c,LifecycleExecuteRequest(ride['order_id'],'CHANGE',q['quote_id'],'0'*64,changes,None,'hash-x')))
 truth=run(gw.order(c,ride['order_id'])).data;assert truth['evidence']['native']['pickup_at']=='2026-10-24T10:00:00'

def test_hotel_cancel_and_change_use_native_fare_engine():
 gw=AgentTransactionGateway(GoTransactionCore());c=ctx();hotel=committed(gw,'HOTEL',{'city_code':'TYO','check_in':'2026-10-25','check_out':'2026-10-26','currency':'CNY'},{'fare_confirmed':True,'simulation_fixture':True},'hotel-cancel')
 q=run(gw.lifecycle_quote(c,LifecycleQuoteRequest(hotel['order_id'],'CANCEL',{},'hotel-cq'))).data;x=run(gw.lifecycle_execute(c,LifecycleExecuteRequest(hotel['order_id'],'CANCEL',q['quote_id'],q['quote_hash'],{},None,'hotel-cx'))).data
 assert x['order_truth']['status'] in {'CANCELLED','REFUNDED'}
 hotel=committed(gw,'HOTEL',{'city_code':'TYO','check_in':'2026-10-27','check_out':'2026-10-28','currency':'CNY'},{'fare_confirmed':True,'simulation_fixture':True},'hotel-change');changes={'new_check_in':'2026-10-28','new_check_out':'2026-10-29'}
 q=run(gw.lifecycle_quote(c,LifecycleQuoteRequest(hotel['order_id'],'CHANGE',changes,'hotel-chq'))).data;x=run(gw.lifecycle_execute(c,LifecycleExecuteRequest(hotel['order_id'],'CHANGE',q['quote_id'],q['quote_hash'],changes,'pm_success','hotel-chx'))).data
 assert x['order_truth']['order_id']==hotel['order_id']
