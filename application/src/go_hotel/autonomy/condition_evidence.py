"""Server-resolved condition evidence, bound to this exact governed action and policy."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from collections.abc import Mapping

from .types import AIActionEnvelope


def _primitive(value):
    if is_dataclass(value):
        return {f.name: _primitive(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {k: _primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(v) for v in value]
    return value


def action_fingerprint(action: AIActionEnvelope) -> str:
    raw = json.dumps(_primitive(action), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class ConditionEvidence:
    policy_rule_id: str
    condition_id: str
    action_sha256: str
    evidence_ref: str
    observed_at: datetime
    valid_until: datetime
    satisfied: bool

    def valid_for(self, *, action: AIActionEnvelope, policy_rule_id: str, condition_id: str, at: datetime) -> bool:
        dates = (self.observed_at, self.valid_until, at)
        return (
            self.satisfied is True
            and self.policy_rule_id == policy_rule_id
            and self.condition_id == condition_id
            and self.action_sha256 == action_fingerprint(action)
            and isinstance(self.evidence_ref, str) and bool(self.evidence_ref.strip())
            and all(isinstance(d, datetime) and d.tzinfo is not None and d.utcoffset() is not None for d in dates)
            and self.observed_at <= at < self.valid_until
        )
