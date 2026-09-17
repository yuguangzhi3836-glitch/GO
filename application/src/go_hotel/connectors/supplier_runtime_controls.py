"""Durable provider-neutral controls. Constructors never create database tables.

Provision metadata explicitly in an isolated controls database. Runtime users
need only the corresponding DML privileges. Raw evidence is encrypted before SQL.
No network request is performed by this module.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import BigInteger, Column, LargeBinary, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


metadata = MetaData()
replay_claims = Table(
    "supplier_runtime_replay", metadata,
    Column("scope", String(128), primary_key=True),
    Column("replay_key", String(64), primary_key=True),
    Column("expires_us", BigInteger, nullable=False),
)
raw_evidence = Table(
    "supplier_runtime_evidence", metadata,
    Column("scope", String(128), primary_key=True),
    Column("evidence_id", String(32), primary_key=True),
    Column("key_id", String(64), nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("ciphertext", LargeBinary, nullable=False),
)
mutations = Table(
    "supplier_runtime_mutation", metadata,
    Column("scope", String(128), primary_key=True),
    Column("operation_key", String(64), primary_key=True),
    Column("request_hash", String(64), nullable=False),
    Column("state", String(16), nullable=False),
    Column("result_json", String, nullable=True),
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _instant(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AWARE_CLOCK_REQUIRED")
    delta = value.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("SHA256_KEY_REQUIRED")
    return value


class _DatabaseControl:
    def __init__(self, engine, *, scope):
        if not isinstance(scope, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", scope):
            raise ValueError("EXPLICIT_PROVIDER_ACCOUNT_SCOPE_REQUIRED")
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("CONTROLS_DATABASE_UNSUPPORTED")
        if engine.dialect.name == "sqlite" and (
            not engine.url.database or engine.url.database == ":memory:"
            or engine.url.query.get("mode") == "memory"
        ):
            raise ValueError("DURABLE_CONTROLS_DATABASE_REQUIRED")
        self.engine, self.scope = engine, scope
        self._insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert


class SQLWebhookReplayStore(_DatabaseControl):
    def __init__(self, engine, *, scope, clock=None):
        super().__init__(engine, scope=scope)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def claim(self, replay_key, *, expires_at):
        _digest(replay_key)
        now, expiry = _instant(self.clock()), _instant(expires_at)
        if expiry <= now:
            return False
        statement = self._insert(replay_claims).values(
            scope=self.scope, replay_key=replay_key, expires_us=expiry,
        ).on_conflict_do_update(
            index_elements=["scope", "replay_key"],
            set_={"expires_us": expiry},
            where=replay_claims.c.expires_us <= now,
        ).returning(replay_claims.c.replay_key)
        # Commit is completed before returning success. No HTTP under this lock.
        with self.engine.begin() as connection:
            claimed = connection.execute(statement).scalar_one_or_none() is not None
        return claimed


class EncryptedSQLEvidenceSink(_DatabaseControl):
    def __init__(self, engine, *, scope, keys, active_key_id):
        super().__init__(engine, scope=scope)
        if not keys or active_key_id not in keys:
            raise ValueError("EVIDENCE_ENCRYPTION_KEY_REQUIRED")
        for key_id, key in keys.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", key_id):
                raise ValueError("EVIDENCE_KEY_ID_INVALID")
            if not isinstance(key, bytes) or len(key) != 32:
                raise ValueError("EVIDENCE_AES256_KEY_REQUIRED")
        self._keys, self.active_key_id = dict(keys), active_key_id

    def _aad(self, evidence_id, key_id):
        return _json({"schema": "supplier.raw.v1", "scope": self.scope,
                      "evidence_id": evidence_id, "key_id": key_id})

    def seal_attempt(self, *, operation, attempt, method, url, request_body,
                     response_status, response_headers, response_body, transport_error):
        if not isinstance(request_body, bytes) or not isinstance(response_body, bytes):
            raise ValueError("RAW_EVIDENCE_BYTES_REQUIRED")
        # All URL/header/body data are inside the encrypted envelope. The raw
        # endpoint may contain PII; never include it in the public reference.
        document = {
            "operation": operation, "attempt": attempt, "method": method, "url": url,
            "request_body_b64": base64.b64encode(request_body).decode(),
            "response_status": response_status, "response_headers": response_headers,
            "response_body_b64": base64.b64encode(response_body).decode(),
            "transport_error": transport_error,
            "request_sha256": _hash(request_body), "response_sha256": _hash(response_body),
        }
        evidence_id, key_id = uuid4().hex, self.active_key_id
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._keys[key_id]).encrypt(
            nonce, _json(document), self._aad(evidence_id, key_id),
        )
        with self.engine.begin() as connection:
            connection.execute(raw_evidence.insert().values(
                scope=self.scope, evidence_id=evidence_id, key_id=key_id,
                nonce=nonce, ciphertext=ciphertext,
            ))
        return f"evidence+sql://{evidence_id}"

    def read_raw(self, reference):
        """Restricted verifier boundary; never use in ordinary logs/exports."""
        prefix = "evidence+sql://"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise ValueError("EVIDENCE_REFERENCE_INVALID")
        evidence_id = reference[len(prefix):]
        if not re.fullmatch("[0-9a-f]{32}", evidence_id):
            raise ValueError("EVIDENCE_REFERENCE_INVALID")
        with self.engine.connect() as connection:
            row = connection.execute(select(raw_evidence).where(
                raw_evidence.c.scope == self.scope,
                raw_evidence.c.evidence_id == evidence_id,
            )).mappings().one_or_none()
        if row is None:
            raise ValueError("EVIDENCE_NOT_FOUND")
        key = self._keys.get(row["key_id"])
        if key is None:
            raise ValueError("EVIDENCE_KEY_UNAVAILABLE")
        try:
            data = AESGCM(key).decrypt(
                row["nonce"], row["ciphertext"], self._aad(evidence_id, row["key_id"]),
            )
        except InvalidTag:
            raise ValueError("EVIDENCE_AUTHENTICATION_FAILED") from None
        return json.loads(data)


class SQLMutationJournal(_DatabaseControl):
    """No automatic expiry/reclaim: a crashed owner has an UNKNOWN outcome."""

    def begin(self, operation_key, request_hash):
        _digest(operation_key)
        _digest(request_hash)
        statement = self._insert(mutations).values(
            scope=self.scope, operation_key=operation_key,
            request_hash=request_hash, state="PENDING",
        ).on_conflict_do_nothing(
            index_elements=["scope", "operation_key"],
        ).returning(mutations.c.operation_key)
        with self.engine.begin() as connection:
            claimed = connection.execute(statement).scalar_one_or_none() is not None
            if claimed:
                return {"claimed": True, "result": None}
            row = connection.execute(select(mutations).where(
                mutations.c.scope == self.scope,
                mutations.c.operation_key == operation_key,
            )).mappings().one()
            if row["request_hash"] != request_hash:
                raise ValueError("SUPPLIER_IDEMPOTENCY_CONFLICT")
            return {"claimed": False,
                    "result": json.loads(row["result_json"]) if row["state"] == "COMPLETE" else None}

    def complete(self, operation_key, request_hash, result):
        # The caller passes only safe runtime metadata, never raw provider data.
        value = _json(result).decode()
        with self.engine.begin() as connection:
            count = connection.execute(mutations.update().where(
                mutations.c.scope == self.scope,
                mutations.c.operation_key == _digest(operation_key),
                mutations.c.request_hash == _digest(request_hash),
                mutations.c.state == "PENDING",
            ).values(state="COMPLETE", result_json=value)).rowcount
            if count != 1:
                raise ValueError("SUPPLIER_MUTATION_NOT_OWNED")


@dataclass(frozen=True)
class VerifiedProviderResponse:
    supplier_reference: str | None


class ContractResponseValidator:
    """Explicit source-backed field rules; no assumed supplier success schema."""

    _TYPES = {"string": str, "boolean": bool, "integer": int, "object": dict, "array": list}

    def validate_contract(self, operation, operation_contract):
        rules = operation_contract.get("response_validation")
        if not isinstance(rules, dict) or not rules.get("required_fields") or not rules.get("success_equals"):
            raise ValueError("SUPPLIER_RESPONSE_RULES_REQUIRED")
        for name, expected_type in rules["required_fields"].items():
            if not isinstance(name, str) or not name or expected_type not in self._TYPES:
                raise ValueError("SUPPLIER_RESPONSE_RULES_INVALID")
        for name, expected in rules["success_equals"].items():
            if name not in rules["required_fields"] or type(expected) not in {str, bool, int}:
                raise ValueError("SUPPLIER_SUCCESS_RULES_INVALID")
            if type(expected) is not self._TYPES[rules["required_fields"][name]]:
                raise ValueError("SUPPLIER_SUCCESS_RULES_INVALID")
        reference_field = rules.get("reference_field")
        if operation in {"BOOK", "QUERY", "CANCEL"} and (
            reference_field not in rules["required_fields"]
            or rules["required_fields"][reference_field] != "string"
        ):
            raise ValueError("SUPPLIER_REFERENCE_RULE_REQUIRED")

    def validate(self, operation, operation_contract, body):
        self.validate_contract(operation, operation_contract)
        rules = operation_contract["response_validation"]
        if not isinstance(body, dict):
            raise ValueError("SUPPLIER_RESPONSE_OBJECT_REQUIRED")
        for name, expected_type in rules["required_fields"].items():
            if name not in body or type(body[name]) is not self._TYPES[expected_type]:
                raise ValueError("SUPPLIER_RESPONSE_SCHEMA_MISMATCH")
        if any(type(body.get(name)) is not type(expected) or body[name] != expected
               for name, expected in rules["success_equals"].items()):
            raise ValueError("SUPPLIER_BUSINESS_RESULT_NOT_SUCCESS")
        reference = body.get(rules.get("reference_field"))
        if rules.get("reference_field") and (not isinstance(reference, str) or not reference.strip()):
            raise ValueError("SUPPLIER_REFERENCE_INVALID")
        return VerifiedProviderResponse(reference)

