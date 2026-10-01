"""Offline candidate; no network, shell, credential provisioning or installed dispatch.
Trusted integration must supply pinned public keys and live host identity.
"""
import base64
import hashlib
import json
import re
import sqlite3
import time
from cryptography.exceptions import InvalidSignature


class Reject(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(raw):
    if not isinstance(raw, bytes) or len(raw) > 16384:
        raise Reject('size_or_type')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Reject('duplicate_key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Reject('constant')))
    except (ValueError, UnicodeError) as exc:
        raise Reject('invalid_json') from exc


def fields(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise Reject('fields')


def signed(body, private_key):
    return canonical({'body': body, 'signature': base64.b64encode(
        private_key.sign(canonical(body))).decode()})


def verified(raw, public_key):
    value = decode(raw)
    fields(value, 'body signature')
    try:
        signature = base64.b64decode(value['signature'], validate=True)
        public_key.verify(signature, canonical(value['body']))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise Reject('signature') from exc
    return value['body']


def window(body, now, maximum):
    if any(type(body[k]) is not int for k in ('issued_at', 'expires_at')):
        raise Reject('time_type')
    if not body['issued_at'] <= now < body['expires_at']:
        raise Reject('expired_or_future')
    if not 0 < body['expires_at'] - body['issued_at'] <= maximum:
        raise Reject('lifetime')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,79}', value):
        raise Reject('identifier')


def hex_digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise Reject('digest')


REGISTRATION_FIELDS = ('version kind environment host_id agent_id generation candidate_sha '
                       'plan_sha256 executor_sha256 evidence_key_sha256 approval_ref '
                       'issued_at expires_at actions')
TASK_FIELDS = ('version kind task_id nonce environment host_id agent_id generation '
               'registration_sha256 action parameters issued_at expires_at')
ACTION = 'RUNTIME_HOST_PROBE_V1'  # Proposed protocol, NOT an installed Boss action.


def registration(raw, authority_key, now):
    body = verified(raw, authority_key)
    fields(body, REGISTRATION_FIELDS)
    if type(body['version']) is not int or body['version'] != 1 or body['kind'] != 'runtime-host-registration':
        raise Reject('version_or_kind')
    for key in ('environment', 'host_id', 'agent_id', 'approval_ref'):
        identifier(body[key])
    if body['environment'] in ('HK-STAGING-01', 'Production', 'PRODUCTION'):
        raise Reject('protected_environment')
    if type(body['generation']) is not int or body['generation'] < 1:
        raise Reject('generation')
    if not isinstance(body['candidate_sha'], str) or not re.fullmatch('[0-9a-f]{40}', body['candidate_sha']):
        raise Reject('candidate')
    for key in ('plan_sha256', 'executor_sha256', 'evidence_key_sha256'):
        hex_digest(body[key])
    if body['actions'] != [ACTION]:
        raise Reject('action_scope')
    window(body, now, 86400)
    return body


class Registry:
    """Caller must use a dedicated protected local DB, never the Runtime state DB.
    Generation changes require a new authority-signed registration. Claim is committed
    before observation; a crash leaves CLAIMED, never automatically re-executed.
    """
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS registry (
          environment TEXT PRIMARY KEY, host TEXT UNIQUE, agent TEXT UNIQUE,
          generation INTEGER, digest TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, nonce TEXT UNIQUE, task_digest TEXT,
          state TEXT, evidence BLOB);
        ''')

    def enroll(self, raw, authority_key, now):
        clock = now if callable(now) else lambda fixed=now: fixed
        body = registration(raw, authority_key, clock())
        self.db.execute('BEGIN IMMEDIATE')
        try:
            window(body, clock(), 86400)
            old = self.db.execute('SELECT generation,digest,host,agent FROM registry WHERE environment=?',
                                  (body['environment'],)).fetchone()
            if old and old[1] == digest(body):
                self.db.execute('COMMIT')
                return 'UNCHANGED'
            if old and (body['generation'] <= old[0] or (body['host_id'], body['agent_id']) != old[2:]):
                raise Reject('rollback_or_identity_rebind')
            self.db.execute('INSERT INTO registry VALUES (?,?,?,?,?,?) ON CONFLICT(environment) DO UPDATE SET generation=excluded.generation,digest=excluded.digest,body=excluded.body',
                            (body['environment'], body['host_id'], body['agent_id'], body['generation'], digest(body), canonical(body).decode()))
            self.db.execute('COMMIT')
            return 'ENROLLED'
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def probe(self, raw, task_key, live_host_id, executor_sha256, evidence_key, now):
        """Fixed read-only result. No caller command/path/URL or executable callback.
        now is sampled by the trusted adapter per invocation, never supplied by Request.
        Identity/digest observations must be from the installed adapter, not the task.
        """
        from cryptography.hazmat.primitives import serialization
        clock = now if callable(now) else lambda fixed=now: fixed
        at = clock()
        task = verified(raw, task_key)
        fields(task, TASK_FIELDS)
        if type(task['version']) is not int or task['version'] != 1 or task['kind'] != 'runtime-host-task':
            raise Reject('version_or_kind')
        for key in ('task_id', 'nonce'):
            identifier(task[key])
        window(task, at, 300)
        if task['action'] != ACTION or task['parameters'] != {}:
            raise Reject('action_or_parameters')
        if type(task['generation']) is not int:
            raise Reject('generation')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            now = clock()
            window(task, now, 300)
            row = self.db.execute('SELECT body FROM registry WHERE environment=?', (task['environment'],)).fetchone()
            if not row:
                raise Reject('unregistered')
            reg = json.loads(row[0])
            window(reg, now, 86400)
            for key in ('environment', 'host_id', 'agent_id', 'generation'):
                if task[key] != reg[key]:
                    raise Reject('binding')
            pub = evidence_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            if (task['registration_sha256'] != digest(reg) or live_host_id != reg['host_id']
                or executor_sha256 != reg['executor_sha256']
                or hashlib.sha256(pub).hexdigest() != reg['evidence_key_sha256']):
                raise Reject('identity_or_artifact')
            self.db.execute('INSERT INTO tasks VALUES (?,?,?,\'CLAIMED\',NULL)',
                            (task['task_id'], task['nonce'], digest(task)))
            self.db.execute('COMMIT')
        except sqlite3.IntegrityError as exc:
            self.db.execute('ROLLBACK')
            raise Reject('replay') from exc
        except Exception:
            self.db.execute('ROLLBACK')
            raise
        result = {'version': 1, 'kind': 'runtime-host-evidence', 'task_sha256': digest(task),
                  'task_id': task['task_id'], 'registration_sha256': digest(reg),
                  'host_id': live_host_id, 'agent_id': reg['agent_id'], 'generation': reg['generation'],
                  'observed_at': now, 'status': 'PROBE_ONLY', 'runtime_acceptance': 'NOT_RUN',
                  'executor_sha256': executor_sha256}
        evidence = signed(result, evidence_key)
        self.db.execute("UPDATE tasks SET evidence=?,state='COMPLETE' WHERE id=? AND state='CLAIMED'",
                        (evidence, task['task_id']))
        return evidence

    def evidence(self, task_id):
        row = self.db.execute('SELECT state,evidence FROM tasks WHERE id=?', (task_id,)).fetchone()
        return row


def verify_evidence(raw, evidence_public_key, task, reg, now):
    """Control-center readback; successful transport alone is insufficient."""
    result = verified(raw, evidence_public_key)
    fields(result, 'version kind task_sha256 task_id registration_sha256 host_id agent_id generation observed_at status runtime_acceptance executor_sha256')
    from cryptography.hazmat.primitives import serialization
    pub = evidence_public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if hashlib.sha256(pub).hexdigest() != reg['evidence_key_sha256']:
        raise Reject('evidence_identity')
    expected = {'version': 1, 'kind': 'runtime-host-evidence', 'task_sha256': digest(task),
                'task_id': task['task_id'], 'registration_sha256': digest(reg),
                'host_id': reg['host_id'], 'agent_id': reg['agent_id'], 'generation': reg['generation'],
                'status': 'PROBE_ONLY', 'runtime_acceptance': 'NOT_RUN',
                'executor_sha256': reg['executor_sha256']}
    if any(type(result[k]) is not type(v) or result[k] != v for k,v in expected.items()):
        raise Reject('evidence_binding')
    if type(result['observed_at']) is not int or not task['issued_at'] <= result['observed_at'] < task['expires_at'] or not result['observed_at'] <= now <= result['observed_at'] + 300:
        raise Reject('evidence_time')
    return result
