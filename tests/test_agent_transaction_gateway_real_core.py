from fastapi import FastAPI
from fastapi.testclient import TestClient

from go_hotel.agent_gateway.a2a import GO_TRANSACTION_EXTENSION
from go_hotel.agent_gateway.contracts import AgentContext,AgentProtocol
from go_hotel.agent_gateway.protocol_http import build_a2a_router,build_mcp_router
from go_hotel.agent_gateway.canonical_core import GoTransactionCore
from go_hotel.agent_gateway.rest import build_agent_router
from go_hotel.agent_gateway.service import AgentTransactionGateway

SCOPES=frozenset({'offers:read','reserve:write','payments:write','commit:write','orders:read'})
TRAVELER='agent-traveler-1';AGENT='agent-parity-1'

def authorize(token,agent_id,request_id,trace_id,purpose):
 assert agent_id==AGENT and request_id and trace_id and purpose in {'book-travel','pay-travel'}
 protocol={'Bearer apple':AgentProtocol.APPLE_APP_INTENTS,'Bearer mcp':AgentProtocol.MCP,'Bearer a2a':AgentProtocol.A2A}.get(token,AgentProtocol.REST)
 return AgentContext(request_id,trace_id,agent_id,protocol,purpose,SCOPES,TRAVELER)

def headers(token='rest',purpose='book-travel'):
 return {'Authorization':f'Bearer {token}','X-GO-Agent-ID':AGENT,'X-GO-Request-ID':f'{token}-req','X-GO-Trace-ID':f'{token}-trace','X-GO-Purpose':purpose}

def mcp_call(client,name,args,rpc_id=1):
 h={**headers('mcp'),'MCP-Protocol-Version':'2026-07-28','Mcp-Method':'tools/call','Mcp-Name':name}
 r=client.post('/mcp',headers=h,json={'jsonrpc':'2.0','id':rpc_id,'method':'tools/call','params':{'name':name,'arguments':args}});assert r.status_code==200,r.text
 body=r.json();assert 'error' not in body,body;return body['result']['structuredContent']['data']

def a2a_call(client,skill,payload,rpc_id=1):
 h={**headers('a2a'),'A2A-Version':'1.0'}
 msg={'messageId':f'msg-{rpc_id}','role':'ROLE_USER','parts':[{'text':skill}],'extensions':[GO_TRANSACTION_EXTENSION],'metadata':{'goSkill':skill,'payload':payload}}
 r=client.post('/a2a/v1',headers=h,json={'jsonrpc':'2.0','id':rpc_id,'method':'SendMessage','params':{'message':msg}});assert r.status_code==200,r.text
 body=r.json();assert 'error' not in body,body;return body['result']['message']['parts'][0]['data']['data']

def same(items,keys):
 first=items[0]
 for item in items[1:]:assert {k:item[k] for k in keys}=={k:first[k] for k in keys}

def app():
 gw=AgentTransactionGateway(GoTransactionCore());a=FastAPI();a.include_router(build_agent_router(gw,authorize));a.include_router(build_mcp_router(gw,authorize));a.include_router(build_a2a_router(gw,authorize));return a

def test_one_native_flight_transaction_is_identical_across_rest_mcp_a2a_and_apple():
 search={'origin':'SHA','destination':'PEK','departure_date':'2026-10-01','cabin':'ECONOMY','currency':'CNY','adults':1}
 with TestClient(app()) as c:
  card=c.get('/.well-known/agent-card.json').json();assert card['supportedInterfaces'][0]['protocolBinding']=='JSONRPC' and card['supportedInterfaces'][0]['protocolVersion']=='1.0'
  offer=c.post('/v1/agent/offers',headers=headers(),json={'product_type':'FLIGHT','search':search}).json()['data']['items'][0]
  reserve={'offer_id':offer['offer_id'],'quote_hash':offer['quote_hash'],'search':search,'booking':{'passengers':[{'full_name':'Agent Traveler','type':'ADT'}]},'idempotency_key':'parity-reserve-1'}
  rr=c.post('/v1/agent/reserves',headers=headers(),json=reserve).json()['data'];rm=mcp_call(c,'go.travel.reserve',reserve,2);ra=a2a_call(c,'reserve',reserve,3);rapple=c.post('/v1/agent/reserves',headers=headers('apple'),json=reserve).json()['data']
  same([rr,rm,ra,rapple],['reserve_id','order_id','offer_id','product_type','status','total_minor','currency','inventory_version'])
  payment={'reserve_id':rr['reserve_id'],'expected_total_minor':rr['total_minor'],'currency':rr['currency'],'payment_method_id':'pm_agent_contract','idempotency_key':'parity-payment-1'}
  pr=c.post('/v1/agent/payments',headers=headers(purpose='pay-travel'),json=payment).json()['data'];pm=mcp_call(c,'go.travel.payment.prepare',payment,4);pa=a2a_call(c,'payment.prepare',payment,5);papple=c.post('/v1/agent/payments',headers=headers('apple','pay-travel'),json=payment).json()['data']
  same([pr,pm,pa,papple],['payment_truth_id','reserve_id','product_type','state','total_minor','currency','captured']);assert pr['state']=='SUCCEEDED' and pr['captured'] is True
  commit={'reserve_id':rr['reserve_id'],'payment_truth_id':pr['payment_truth_id'],'idempotency_key':'parity-commit-1'}
  cr=c.post('/v1/agent/commits',headers=headers(),json=commit).json()['data'];cm=mcp_call(c,'go.travel.commit',commit,6);ca=a2a_call(c,'commit',commit,7);capple=c.post('/v1/agent/commits',headers=headers('apple'),json=commit).json()['data']
  keys=['order_id','reserve_id','product_type','status','supplier_confirmation','payment_state','transaction_version','total_minor','currency'];same([cr,cm,ca,capple],keys);assert cr['status']=='TICKETED' and cr['payment_state']=='SUCCEEDED'
  oid=cr['order_id'];or_=c.get('/v1/agent/orders/'+oid,headers=headers()).json()['data'];om=mcp_call(c,'go.travel.order.get',{'order_id':oid},8);oa=a2a_call(c,'order.get',{'order_id':oid},9);oapple=c.get('/v1/agent/orders/'+oid,headers=headers('apple')).json()['data'];same([or_,om,oa,oapple],['order_id','status','supplier_confirmation','payment_state','transaction_version','total_minor','currency'])

def test_protocol_headers_and_payment_truth_fail_closed():
 with TestClient(app()) as c:
  h={**headers('mcp'),'MCP-Protocol-Version':'2026-07-28','Mcp-Method':'tools/call','Mcp-Name':'wrong'}
  r=c.post('/mcp',headers=h,json={'jsonrpc':'2.0','id':10,'method':'tools/call','params':{'name':'go.travel.order.get','arguments':{'order_id':'FLIGHT:nope'}}});assert r.status_code==400 and r.json()['error']['code']==-32020
  r=c.post('/a2a/v1',headers={**headers('a2a'),'A2A-Version':'0.3'},json={'jsonrpc':'2.0','id':11,'method':'SendMessage','params':{}});assert r.status_code==400
