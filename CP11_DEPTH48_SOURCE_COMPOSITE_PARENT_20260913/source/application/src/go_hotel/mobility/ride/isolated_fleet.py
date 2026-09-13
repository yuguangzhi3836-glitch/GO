"""Explicit disk-backed fleet simulator. No network or real provider side effects."""
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from go_hotel.autonomy.durable import canonical, digest
from go_hotel.services.travel_operational_facts import environment_allowed


class IsolatedFleetAdapter:
    adapter_id = 'isolated-fleet-v1'
    external_live = False

    def __init__(self, path):
        environment_allowed('ENGINEERING')
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as c:
            c.execute('CREATE TABLE IF NOT EXISTS requests (intent TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=30)
        try:
            c.execute('PRAGMA synchronous=FULL')
            with c:
                yield c
        finally:
            c.close()

    def execute(self, request, request_hash):
        environment_allowed('ENGINEERING')
        if not request or digest(request) != request_hash:
            raise ValueError('ISOLATED_FLEET_REQUEST_INVALID')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT request_hash,receipt FROM requests WHERE intent=?', (request['adjustment_id'],)).fetchone()
            if old:
                if old[0] != request_hash: raise ValueError('ISOLATED_FLEET_REQUEST_CONFLICT')
                return json.loads(old[1])
            result = {'status': 'CONFIRMED', 'request_hash': request_hash,
                'provider_reference': 'isolated-fleet:'+request['adjustment_id'],
                'pickup_at': request['proposed_pickup_at'], 'external_live': False}
            c.execute('INSERT INTO requests VALUES (?,?,?)', (request['adjustment_id'], request_hash, canonical(result)))
            return result

    def query(self, adjustment_id, request_hash):
        environment_allowed('ENGINEERING')
        with self.connection() as c:
            row = c.execute('SELECT request_hash,receipt FROM requests WHERE intent=?', (adjustment_id,)).fetchone()
            if row and row[0] == request_hash: return json.loads(row[1])
            return {'status': 'UNKNOWN', 'request_hash': request_hash, 'external_live': False}
