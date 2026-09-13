"""Durable read-only task delivery with expiring, fenced, signed evidence.

This store is separate from the business database. No deployment action exists.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request

ACTIONS = frozenset({'runtime_identity', 'http_health', 'service_status', 'file_sha256', 'rds_head_readonly'})
AUTHORITY = 'STAGING_READONLY'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sign(value, key):
    return hmac.new(key.encode(), canonical(value), hashlib.sha256).hexdigest()


def verify(value, signature, key):
    return isinstance(signature, str) and hmac.compare_digest(sign(value, key), signature)


def now_ms():
    return time.time_ns() // 1_000_000


class Rejected(ValueError):
    pass


class Store:
    def __init__(self, path, clock=now_ms):
        self.path = str(path)
        self.clock = clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as s:
            s.execute('CREATE TABLE IF NOT EXISTS task (id TEXT PRIMARY KEY, node TEXT NOT NULL, '
                      'payload TEXT NOT NULL, hash TEXT NOT NULL, state TEXT NOT NULL, expires INTEGER NOT NULL, '
                      'attempts INTEGER NOT NULL DEFAULT 0, lease TEXT, lease_until INTEGER, '
                      'evidence TEXT, evidence_hash TEXT)')

    @contextmanager
    def tx(self):
        s = sqlite3.connect(self.path, timeout=10)
        s.row_factory = sqlite3.Row
        try:
            s.execute('PRAGMA synchronous=FULL')
            s.execute('BEGIN IMMEDIATE')
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    def submit(self, task_id, node, action, target, ttl_seconds=180):
        if not isinstance(task_id, str) or str(uuid.UUID(task_id)) != task_id:
            raise Rejected('TASK_ID_INVALID')
        if action not in ACTIONS or not isinstance(target, str) or not 1 <= len(target) <= 80:
            raise Rejected('READONLY_ACTION_OR_TARGET_INVALID')
        if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 300:
            raise Rejected('TASK_TTL_INVALID')
        intent = {'task_id': task_id, 'node_id': node, 'action': action, 'target': target,
                  'authority': AUTHORITY, 'ttl_seconds': ttl_seconds}
        with self.tx() as s:
            old = s.execute('SELECT * FROM task WHERE id=?', (task_id,)).fetchone()
            if old:
                if old['hash'] != digest(intent):
                    raise Rejected('TASK_IDEMPOTENCY_CONFLICT')
                return json.loads(old['payload'])
            current = self.clock()
            payload = {**intent, 'schema': 'go.control.task.v1', 'issued_ms': current,
                       'expires_ms': current + ttl_seconds * 1000}
            s.execute('INSERT INTO task(id,node,payload,hash,state,expires) VALUES (?,?,?,?,?,?)',
                      (task_id, node, canonical(payload).decode(), digest(intent), 'QUEUED', payload['expires_ms']))
            return payload

    def lease(self, node, key):
        current = self.clock()
        with self.tx() as s:
            s.execute("UPDATE task SET state='HOLD',evidence=? WHERE node=? AND state!='COMPLETE' AND expires<=?",
                      (json.dumps({'gate': 'HOLD', 'reason': 'TASK_EXPIRED'}), node, current))
            s.execute("UPDATE task SET state='HOLD',evidence=? WHERE node=? AND state='LEASED' AND lease_until<=? AND attempts>=3",
                      (json.dumps({'gate': 'HOLD', 'reason': 'DELIVERY_ATTEMPTS_EXHAUSTED'}), node, current))
            row = s.execute("SELECT * FROM task WHERE node=? AND expires>? AND attempts<3 AND "
                            "(state='QUEUED' OR (state='LEASED' AND lease_until<=?)) ORDER BY rowid LIMIT 1",
                            (node, current, current)).fetchone()
            if not row:
                return None
            lease = uuid.uuid4().hex
            until = min(current + 30_000, row['expires'])
            s.execute("UPDATE task SET state='LEASED',lease=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                      (lease, until, row['id']))
            envelope = {'task': json.loads(row['payload']), 'lease_id': lease, 'lease_until_ms': until,
                        'attempt': row['attempts'] + 1}
            return {'envelope': envelope, 'signature': sign(envelope, key)}

    def accept(self, node, report, signature, key):
        if len(canonical(report)) > 131072 or not verify(report, signature, key):
            raise Rejected('EVIDENCE_SIGNATURE_INVALID')
        if set(report) != {'task_id','node_id','task_sha256','lease_id','result'} or report['node_id'] != node:
            raise Rejected('EVIDENCE_IDENTITY_INVALID')
        result = report['result']
        if not isinstance(result, dict) or result.get('gate') not in {'PASS','HOLD'} or type(result.get('executed')) is not bool:
            raise Rejected('EVIDENCE_RESULT_INVALID')
        if result['gate'] == 'PASS' and (not result['executed'] or result.get('exit_code') != 0):
            raise Rejected('SUCCESS_WITHOUT_EXECUTION')
        with self.tx() as s:
            row = s.execute('SELECT * FROM task WHERE id=? AND node=?', (report['task_id'],node)).fetchone()
            if not row or digest(json.loads(row['payload'])) != report['task_sha256']:
                raise Rejected('EVIDENCE_TASK_MISMATCH')
            fingerprint = digest(report)
            if row['state'] == 'COMPLETE':
                if row['evidence_hash'] != fingerprint:
                    raise Rejected('EVIDENCE_REPLAY_CONFLICT')
                return {'accepted': True, 'duplicate': True, 'evidence_sha256': fingerprint}
            if row['state'] != 'LEASED' or row['lease'] != report['lease_id'] or row['lease_until'] <= self.clock():
                raise Rejected('STALE_EVIDENCE_LEASE')
            s.execute("UPDATE task SET state='COMPLETE',evidence=?,evidence_hash=? WHERE id=?",
                      (canonical(report).decode(), fingerprint, row['id']))
            return {'accepted': True, 'duplicate': False, 'evidence_sha256': fingerprint}

    def status(self, task_id):
        with self.tx() as s:
            s.execute("UPDATE task SET state='HOLD',evidence=? WHERE id=? AND state IN ('QUEUED','LEASED') AND expires<=?",
                      (json.dumps({'gate':'HOLD','reason':'TASK_EXPIRED'}),task_id,self.clock()))
            s.execute("UPDATE task SET state='HOLD',evidence=? WHERE id=? AND state='LEASED' AND attempts>=3 AND lease_until<=?",
                      (json.dumps({'gate':'HOLD','reason':'DELIVERY_ATTEMPTS_EXHAUSTED'}),task_id,self.clock()))
            row = s.execute('SELECT * FROM task WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise Rejected('TASK_NOT_FOUND')
            return {'task': json.loads(row['payload']), 'state': row['state'], 'attempts': row['attempts'],
                    'evidence': json.loads(row['evidence']) if row['evidence'] else None}


def create_app(store, nodes, operator_token):
    if len(operator_token) < 32 or not nodes:
        raise Rejected('CONTROL_CONFIGURATION_REQUIRED')
    for node, value in nodes.items():
        if not node or len(value['token']) < 32 or len(value['hmac_key']) < 32 or value['token'] == operator_token:
            raise Rejected('SEPARATE_NODE_CREDENTIALS_REQUIRED')
    app = FastAPI(title='GO Read-only Control Bridge', docs_url=None, redoc_url=None, openapi_url=None)

    def auth(got, expected):
        if not isinstance(got, str) or not hmac.compare_digest(got, 'Bearer ' + expected):
            raise HTTPException(401, 'AUTHENTICATION_REQUIRED')

    def node_auth(node, authorization):
        if node not in nodes:
            raise HTTPException(401, 'AUTHENTICATION_REQUIRED')
        auth(authorization, nodes[node]['token'])
        return nodes[node]

    async def body(request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 131072:
                raise HTTPException(413, 'REQUEST_TOO_LARGE')
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'JSON_OBJECT_REQUIRED')

    @app.post('/v1/tasks')
    async def submit(request: Request, authorization: str | None = Header(default=None)):
        auth(authorization, operator_token)
        value = await body(request)
        try:
            if set(value) != {'task_id','node_id','action','target','ttl_seconds'} or value['node_id'] not in nodes:
                raise Rejected('TASK_CONTRACT_INVALID')
            profile = nodes[value['node_id']].get('targets', {})
            if profile.get(value['target']) != value['action']:
                raise Rejected('TARGET_NOT_APPROVED')
            return store.submit(value['task_id'],value['node_id'],value['action'],value['target'],value['ttl_seconds'])
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(409, str(exc))

    @app.post('/v1/nodes/{node}/lease')
    def lease(node: str, authorization: str | None = Header(default=None)):
        value = node_auth(node, authorization)
        return {'delivery': store.lease(node, value['hmac_key'])}

    @app.post('/v1/nodes/{node}/evidence')
    async def evidence(node: str, request: Request, authorization: str | None = Header(default=None)):
        value = node_auth(node, authorization)
        data = await body(request)
        try:
            return store.accept(node,data['report'],data['signature'],value['hmac_key'])
        except (Rejected,KeyError,TypeError) as exc:
            raise HTTPException(409,str(exc))

    @app.get('/v1/tasks/{task_id}')
    def status(task_id: str, authorization: str | None = Header(default=None)):
        auth(authorization, operator_token)
        try:
            return store.status(task_id)
        except Rejected as exc:
            raise HTTPException(404,str(exc))

    return app
