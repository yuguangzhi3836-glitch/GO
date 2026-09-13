import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import uuid

import pytest
from fastapi.testclient import TestClient

from go_hotel.control_plane.bridge import Store,create_app,digest,sign,Rejected
from go_hotel.control_plane.worker import Agent,Journal,Probes,https_endpoint,command

pytestmark=pytest.mark.no_db
KEY='isolated-hmac-key-'+'k'*32
TOKEN='isolated-node-token-'+'n'*32
OPERATOR='isolated-operator-token-'+'o'*32


@pytest.fixture
def rig(tmp_path):
    clock=[1000000]
    store=Store(tmp_path/'control.db',clock=lambda:clock[0])
    nodes={'hk-test':{'token':TOKEN,'hmac_key':KEY,'targets':{'artifact':'file_sha256'}}}
    client=TestClient(create_app(store,nodes,OPERATOR))
    class Wire:
        drop=False
        def post(self,path,payload):
            if self.drop and path.endswith('/evidence'):
                self.drop=False
                raise ConnectionError('isolated drop before receipt')
            r=client.post(path,json=payload,headers={'Authorization':'Bearer '+TOKEN})
            assert r.status_code==200,r.text
            return r.json()
    wire=Wire();data=tmp_path/'artifact.zip';data.write_bytes(b'preserved-source')
    probes=Probes({'artifact':{'action':'file_sha256','path':str(data),'root':str(tmp_path)}})
    agent=Agent('hk-test',KEY,Journal(tmp_path/'node.db'),wire,probes,clock=lambda:clock[0])
    return store,client,agent,wire,clock,probes


def submit(store):
    return store.submit(str(uuid.uuid4()),'hk-test','file_sha256','artifact')


def test_authenticated_command_evidence_roundtrip(rig):
    store,client,agent,wire,clock,probes=rig
    task={'task_id':str(uuid.uuid4()),'node_id':'hk-test','action':'file_sha256','target':'artifact','ttl_seconds':180}
    assert client.post('/v1/tasks',json=task,headers={'Authorization':'Bearer '+TOKEN}).status_code==401
    response=client.post('/v1/tasks',json=task,headers={'Authorization':'Bearer '+OPERATOR})
    assert response.status_code==200
    result=agent.once();assert result['gate']=='PASS' and result['evidence_accepted']
    status=store.status(task['task_id']);assert status['state']=='COMPLETE'
    assert status['evidence']['result']['sha256']==__import__('hashlib').sha256(b'preserved-source').hexdigest()
    assert agent.once()=={'gate':'IDLE','executed':False}


def test_lost_receipt_and_node_restart_do_not_repeat_probe(rig):
    store,client,agent,wire,clock,probes=rig;task=submit(store);wire.drop=True;calls=[]
    agent.probes=lambda *args:(calls.append(args) or probes(*args))
    with pytest.raises(ConnectionError):agent.once()
    clock[0]+=31000
    restarted=Agent('hk-test',KEY,Journal(agent.journal.path),wire,agent.probes,clock=lambda:clock[0])
    assert restarted.once()['gate']=='PASS'
    assert len(calls)==1 and store.status(task['task_id'])['attempts']==2


def test_old_lease_and_conflicting_result_are_rejected(rig):
    store,_,agent,wire,clock,_=rig;task=submit(store);first=store.lease('hk-test',KEY)['envelope']
    clock[0]+=31000;second=store.lease('hk-test',KEY)['envelope']
    report={'task_id':task['task_id'],'node_id':'hk-test','task_sha256':digest(task),'lease_id':first['lease_id'],
            'result':{'gate':'PASS','executed':True,'exit_code':0}}
    with pytest.raises(Rejected,match='STALE'):store.accept('hk-test',report,sign(report,KEY),KEY)
    report['lease_id']=second['lease_id'];assert store.accept('hk-test',report,sign(report,KEY),KEY)['accepted']
    assert store.accept('hk-test',report,sign(report,KEY),KEY)['duplicate']
    report['result']['gate']='HOLD'
    with pytest.raises(Rejected,match='REPLAY_CONFLICT'):store.accept('hk-test',report,sign(report,KEY),KEY)


def test_expired_task_and_bounded_delivery_attempts(rig):
    store,_,agent,wire,clock,_=rig;task=submit(store)
    for i in range(3):assert store.lease('hk-test',KEY);clock[0]+=31000
    assert store.lease('hk-test',KEY) is None
    assert store.status(task['task_id'])['evidence']['reason']=='DELIVERY_ATTEMPTS_EXHAUSTED'
    expired=submit(store);clock[0]+=181000;assert store.lease('hk-test',KEY) is None
    assert store.status(expired['task_id'])['evidence']['reason']=='TASK_EXPIRED'


def test_parallel_lease_has_single_owner(rig):
    store,*_=rig;submit(store)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:store.lease('hk-test',KEY),range(4)))
    assert sum(x is not None for x in results)==1


def test_operator_observes_expiry_without_node_poll(rig):
    store,_,_,_,clock,_=rig;task=submit(store)
    clock[0]+=181000
    status=store.status(task['task_id'])
    assert status['state']=='HOLD' and status['evidence']['reason']=='TASK_EXPIRED'


@pytest.mark.parametrize('action',['shell','service_restart','runtime_cutover','db_write','deploy','set_authority'])
def test_write_actions_are_unavailable(rig,action):
    store,*_=rig
    with pytest.raises(Rejected):store.submit(str(uuid.uuid4()),'hk-test',action,'artifact')


@pytest.mark.parametrize('url',['http://goaidirect.cn','https://127.0.0.1','https://localhost','https://[::1]',
    'https://10.0.0.1','https://user:pass@example.com','https://example.com?token=secret'])
def test_transport_rejects_unapproved_url_shapes(url):
    with pytest.raises(Rejected):https_endpoint(url)


def test_wrong_signature_does_not_execute(rig):
    store,_,agent,wire,clock,_=rig;submit(store)
    original=wire.post
    def tamper(path,payload):
        value=original(path,payload)
        if path.endswith('/lease'):value['delivery']['signature']='bad'
        return value
    wire.post=tamper
    with pytest.raises(Rejected,match='SIGNATURE'):agent.once()
    with agent.journal.connection() as s:assert s.execute('SELECT count(*) FROM execution').fetchone()[0]==0


def test_probe_failure_cannot_be_a_passing_gate(tmp_path):
    result=command(['/no/such/go-probe']);assert result['gate']=='HOLD' and not result['executed']
    result=command([__import__('sys').executable,'-c','raise SystemExit(7)'])
    assert result['gate']=='HOLD' and result['exit_code']==7


def test_task_id_is_bound_to_intent(rig):
    store,*_=rig;task=submit(store)
    assert store.submit(task['task_id'],'hk-test','file_sha256','artifact')==task
    with pytest.raises(Rejected,match='IDEMPOTENCY_CONFLICT'):store.submit(task['task_id'],'hk-test','file_sha256','other')


def test_file_probe_cannot_escape_approved_root(tmp_path):
    outside=tmp_path/'outside';outside.write_text('private')
    root=tmp_path/'safe';root.mkdir();link=root/'link';link.symlink_to(outside)
    for path in [outside,link]:
        probe=Probes({'x':{'action':'file_sha256','path':str(path),'root':str(root)}})
        with pytest.raises(Rejected):probe('file_sha256','x')


def test_node_cannot_claim_success_without_running(rig):
    store,*_=rig;task=submit(store);lease=store.lease('hk-test',KEY)['envelope']
    report={'task_id':task['task_id'],'node_id':'hk-test','task_sha256':digest(task),'lease_id':lease['lease_id'],
            'result':{'gate':'PASS','executed':False,'exit_code':0}}
    with pytest.raises(Rejected,match='SUCCESS_WITHOUT'):store.accept('hk-test',report,sign(report,KEY),KEY)
