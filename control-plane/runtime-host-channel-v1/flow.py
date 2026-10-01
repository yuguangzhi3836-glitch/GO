"""Candidate orchestration. Transport and pinned signers supplied by trusted service.
No real transport is enabled here; wire only after a reviewed installed revision.
"""
import hashlib
import secrets
import sqlite3
from adapter import derive_probe
from channel import Reject, canonical, decode, digest, signed, verified, registration, window, verify_evidence

class Outbox:
    def __init__(self, path):
        self.db=sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS outbox (request_id TEXT PRIMARY KEY, request_digest TEXT, task_id TEXT UNIQUE, raw BLOB, state TEXT)')

    def prepare(self, request_raw, registration_raw, authority_public, authenticated_author,
                allowed_authors, task_signer, clock):
        # Authenticated author must come from a verified immutable PR adapter, not JSON.
        request=decode(request_raw)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            at=clock(); reg=registration(registration_raw,authority_public,at)
            context=digest({'request':request,'author':authenticated_author,'registration':reg})
            # Validate even on retry; changed approval/registry/author may not reuse task.
            task=derive_probe(request_raw,reg,authenticated_author,allowed_authors,at,
                              'rh-'+secrets.token_hex(16),secrets.token_hex(24))
            old=self.db.execute('SELECT request_digest,raw FROM outbox WHERE request_id=?',(request['request_id'],)).fetchone()
            if old:
                if old[0]!=context: raise Reject('request_rebound')
                self.db.execute('COMMIT'); return old[1]
            raw=signed(task,task_signer)
            self.db.execute('INSERT INTO outbox VALUES (?,?,?,?,?)',(request['request_id'],context,task['task_id'],raw,'PREPARED'))
            self.db.execute('COMMIT'); return raw
        except Exception:
            self.db.execute('ROLLBACK'); raise

    def publish(self, request_id, transport, task_public, clock):
        # Reserve publish attempt DURABLY before I/O. Ambiguous writes are read-only
        # reconciled, never retried or newly signed by this function.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT task_id,raw,state FROM outbox WHERE request_id=?',(request_id,)).fetchone()
            if not row: raise Reject('unknown_request')
            task_id, raw, state=row
            task=verified(raw,task_public)
            if state=='PREPARED':
                window(task,clock(),300)
                self.db.execute("UPDATE outbox SET state='ATTEMPTED' WHERE request_id=?",(request_id,))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK'); raise
        key='tasks/'+task_id+'.json'
        if state=='PREPARED':
            # If this raises after remote acceptance, next tick only reads key.
            window(task,clock(),300)
            transport.create(key,raw)
        remote=transport.read(key)
        if remote is None: raise Reject('publication_unresolved_no_retry')
        if remote!=raw: raise Reject('publication_conflict')
        self.db.execute("UPDATE outbox SET state='PUBLISHED' WHERE request_id=?",(request_id,))
        return task_id


def initialize(registry, registration_raw, authority_public, evidence_signer,
               live_host_id, executor_sha256, clock):
    """First registration only after local identity/artifact/key match.
    Provisioning the pinned keys and cloud identity adapter is outside this function.
    No credential generation/copy, systemd install, shell or Runtime start.
    """
    from cryptography.hazmat.primitives import serialization
    reg=registration(registration_raw,authority_public,clock())
    pub=evidence_signer.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    if (live_host_id!=reg['host_id'] or executor_sha256!=reg['executor_sha256']
        or hashlib.sha256(pub).hexdigest()!=reg['evidence_key_sha256']):
        raise Reject('bootstrap_identity_or_artifact')
    registry.enroll(registration_raw,authority_public,clock)
    return reg


def poll_once(registry, registration_raw, authority_public, task_public, evidence_signer,
              live_host_id, executor_sha256, tasks, evidence, clock):
    """One polling pass. Replays only publish the original stored receipt bytes.
    Transports are separate stores; IDs supplied by transport are never paths to shell.
    Unknown/crashed task claims remain uncertain. Caller schedules next poll.
    """
    reg=initialize(registry,registration_raw,authority_public,evidence_signer,live_host_id,executor_sha256,clock)
    results=[]
    for key in tasks.keys():
        raw=tasks.read(key)
        task=verified(raw,task_public)
        if task.get('environment')!=reg['environment']: continue
        from channel import identifier
        identifier(task.get('task_id'))
        if key!='tasks/'+task['task_id']+'.json': raise Reject('task_path_binding')
        stored=registry.db.execute('SELECT task_digest,state,evidence FROM tasks WHERE id=?',(task['task_id'],)).fetchone()
        if stored:
            if stored[0]!=digest(task): raise Reject('task_id_rebound')
            if stored[1]!='COMPLETE':
                results.append((task['task_id'],'UNCERTAIN')); continue
            receipt=stored[2]
        else:
            receipt=registry.probe(raw,task_public,live_host_id,executor_sha256,evidence_signer,clock)
        dest='evidence/'+task['task_id']+'.json'
        found=evidence.read(dest)
        if found is None: evidence.create(dest,receipt)
        elif found!=receipt: raise Reject('evidence_publication_conflict')
        if evidence.read(dest)!=receipt: raise Reject('evidence_readback')
        results.append((task['task_id'],'EVIDENCE_PUBLISHED'))
    return results


def collect(task_raw, registration_raw, authority_public, task_public, evidence_public, transport, clock):
    reg=registration(registration_raw,authority_public,clock())
    task=verified(task_raw,task_public)
    if task['registration_sha256']!=digest(reg): raise Reject('registration_changed')
    raw=transport.read('evidence/'+task['task_id']+'.json')
    if raw is None: raise Reject('evidence_pending')
    return verify_evidence(raw,evidence_public,task,reg,clock())
