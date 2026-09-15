"""Configured HTTPS node agent; one bounded poll by default, durable evidence."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import urlsplit

import httpx

from .bridge import AUTHORITY, ACTIONS, Rejected, canonical, digest, now_ms, sign, verify


def https_endpoint(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Rejected('CONTROL_HTTPS_ENDPOINT_REQUIRED')
    if parsed.hostname.lower() in {'localhost','terminal.local'} or parsed.hostname.endswith('.localhost'):
        raise Rejected('CONTROL_LOOPBACK_DENIED')
    try:
        addr = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return value.rstrip('/')
    if not addr.is_global:
        raise Rejected('CONTROL_PRIVATE_ADDRESS_DENIED')
    return value.rstrip('/')


class Transport:
    def __init__(self, endpoint, token, ca_file):
        import ssl
        self.endpoint = https_endpoint(endpoint)
        if len(token) < 32 or not Path(ca_file).is_file():
            raise Rejected('NODE_TOKEN_OR_CA_REQUIRED')
        self.client = httpx.Client(verify=ssl.create_default_context(cafile=str(ca_file)),
                                  timeout=10, follow_redirects=False, trust_env=False,
                                  headers={'Authorization': 'Bearer ' + token})

    def post(self, path, payload):
        with self.client.stream('POST',self.endpoint + path,json=payload) as response:
            if response.status_code != 200:
                raise Rejected('CONTROL_HTTP_' + str(response.status_code))
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 131072:
                    raise Rejected('CONTROL_RESPONSE_TOO_LARGE')
        value = json.loads(data)
        if not isinstance(value,dict):
            raise Rejected('CONTROL_RESPONSE_INVALID')
        return value


class Journal:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        s=self.connection()
        try:
            s.execute('CREATE TABLE IF NOT EXISTS execution (id TEXT PRIMARY KEY, task_hash TEXT NOT NULL, '
                      'result TEXT NOT NULL)')
            s.commit()
        finally:
            s.close()

    def connection(self):
        connection=sqlite3.connect(self.path,timeout=10)
        connection.execute('PRAGMA synchronous=FULL')
        return connection

    def execute_once(self, task, execute):
        # Serialize node workers, retain a completed result even if delivery dies.
        s=self.connection()
        try:
            s.execute('BEGIN IMMEDIATE')
            row=s.execute('SELECT task_hash,result FROM execution WHERE id=?',(task['task_id'],)).fetchone()
            fingerprint=digest(task)
            if row:
                if row[0] != fingerprint:
                    raise Rejected('LOCAL_TASK_REPLAY_CONFLICT')
                return json.loads(row[1])
            result=execute(task['action'],task['target'])
            s.execute('INSERT INTO execution VALUES (?,?,?)',(task['task_id'],fingerprint,canonical(result).decode()))
            s.commit()
            return result
        finally:
            s.close()


def command(argv):
    try:
        result=subprocess.run(argv,capture_output=True,text=True,timeout=10,check=False)
    except subprocess.TimeoutExpired:
        return {'gate':'HOLD','executed':True,'exit_code':None,'reason':'PROBE_TIMEOUT'}
    except OSError:
        return {'gate':'HOLD','executed':False,'exit_code':None,'reason':'PROBE_EXECUTABLE_UNAVAILABLE'}
    return {'gate':'PASS' if result.returncode==0 else 'HOLD','executed':True,'exit_code':result.returncode,
            'stdout':result.stdout[:16384],'stderr':result.stderr[:4096]}


class Probes:
    def __init__(self, targets):
        self.targets=targets

    def __call__(self, action, target):
        config=self.targets.get(target)
        if not isinstance(config,dict) or config.get('action') != action:
            raise Rejected('NODE_TARGET_NOT_APPROVED')
        if action=='file_sha256':
            path=Path(config['path']);root=Path(config['root']).resolve(strict=True)
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root) or path.stat().st_size>536870912:
                raise Rejected('FILE_OUTSIDE_APPROVED_ROOT')
            with path.open('rb') as stream:
                sha=hashlib.file_digest(stream,'sha256').hexdigest()
            return {'gate':'PASS','executed':True,'exit_code':0,'sha256':sha,'target':target}
        if action=='runtime_identity':
            container=config.get('container','')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',container):
                raise Rejected('CONTAINER_INVALID')
            return command(['docker','inspect','--type','container','--format',
                            '{{.Name}}|{{.Image}}|{{.State.Status}}',container])
        if action=='service_status':
            unit=config.get('unit','')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9@_.-]{0,127}\.service',unit):
                raise Rejected('SERVICE_UNIT_INVALID')
            result=command(['systemctl','show',unit,'--no-pager','--property=LoadState,ActiveState,SubState,UnitFileState'])
            if result.get('exit_code')==0 and 'LoadState=not-found' in result.get('stdout',''):
                result.update(gate='HOLD',reason='SERVICE_NOT_FOUND')
            return result
        if action=='http_health':
            url=https_endpoint(config['url'])
            try:
                with httpx.Client(timeout=10,follow_redirects=False,trust_env=False) as client:
                    with client.stream('GET',url) as response:
                        code=response.status_code
                return {'gate':'PASS' if code==200 else 'HOLD','executed':True,
                        'exit_code':0 if code==200 else 1,'http_status':code}
            except httpx.HTTPError:
                return {'gate':'HOLD','executed':True,'exit_code':None,'reason':'HEALTH_TRANSPORT_FAILURE'}
        raise Rejected('APPROVED_RDS_PROBE_NOT_CONFIGURED')


class Agent:
    def __init__(self,node,key,journal,transport,probes,clock=now_ms):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',node) or len(key)<32:
            raise Rejected('NODE_ID_OR_HMAC_KEY_INVALID')
        self.node,self.key,self.journal,self.transport,self.probes,self.clock=node,key,journal,transport,probes,clock

    def once(self):
        delivery=self.transport.post('/v1/nodes/'+self.node+'/lease',{}).get('delivery')
        if delivery is None:
            return {'gate':'IDLE','executed':False}
        envelope=delivery['envelope']
        if not verify(envelope,delivery['signature'],self.key):
            raise Rejected('TASK_SIGNATURE_INVALID')
        task=envelope['task'];current=self.clock()
        if (task.get('schema')!='go.control.task.v1' or task.get('node_id')!=self.node or
            task.get('authority')!=AUTHORITY or task.get('action') not in ACTIONS or
            task.get('issued_ms',current+1)>current+30000 or task.get('expires_ms',0)<=current or
            envelope.get('lease_until_ms',0)<=current or task['expires_ms']-task['issued_ms']>300000):
            raise Rejected('TASK_SCOPE_OR_TIME_INVALID')
        def execute(action,target):
            # Recheck after waiting for another node process's local journal lock.
            if self.clock()>=min(envelope['lease_until_ms'],task['expires_ms']):
                raise Rejected('TASK_EXPIRED_BEFORE_EXECUTION')
            try:
                return self.probes(action,target)
            except (Rejected,KeyError,ValueError):
                return {'gate':'HOLD','executed':False,'exit_code':None,'reason':'PROBE_POLICY_REJECTED'}
        result=self.journal.execute_once(task,execute)
        report={'task_id':task['task_id'],'node_id':self.node,'task_sha256':digest(task),
                'lease_id':envelope['lease_id'],'result':result}
        response=self.transport.post('/v1/nodes/'+self.node+'/evidence',{'report':report,'signature':sign(report,self.key)})
        if response.get('accepted') is not True or response.get('evidence_sha256')!=digest(report):
            raise Rejected('EVIDENCE_ACK_INVALID')
        return {'gate':result['gate'],'executed':result['executed'],'task_id':task['task_id'],
                'evidence_sha256':digest(report),'evidence_accepted':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    required=['CONTROL_API_ENDPOINT','NODE_TOKEN','TASK_HMAC_KEY','CA_PEM','GO_CP_NODE_ID']
    missing=[name for name in required if not os.environ.get(name)]
    if not args.config or not args.config.is_file():missing.append('APPROVED_TARGET_CONFIG')
    if missing:
        print(json.dumps({'gate':'HOLD','executed':False,'reason':'SECURE_TRANSPORT_NOT_CONFIGURED','missing':missing}))
        return 2
    transport=None
    try:
        config=json.loads(args.config.read_text())
        transport=Transport(os.environ['CONTROL_API_ENDPOINT'],os.environ['NODE_TOKEN'],os.environ['CA_PEM'])
        agent=Agent(os.environ['GO_CP_NODE_ID'],os.environ['TASK_HMAC_KEY'],Journal(config['journal']),transport,Probes(config['targets']))
        if args.check:
            print(json.dumps({'gate':'CONFIGURED_NOT_CONNECTED','executed':False,'authority':AUTHORITY}))
            return 0
        result=agent.once();print(json.dumps(result));return 0 if result['gate'] in {'PASS','IDLE'} else 2
    except (Rejected,httpx.HTTPError,ValueError,KeyError,TypeError,OSError):
        print(json.dumps({'gate':'HOLD','executed':False,'reason':'TRANSPORT_OR_CONTRACT_FAILURE'}));return 2
    finally:
        if transport:transport.client.close()


if __name__=='__main__':
    raise SystemExit(main())
