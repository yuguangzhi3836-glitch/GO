"""Canonical JSON / digest helpers.

The convention the rest of the control plane uses (``canonical`` / ``digest``):
sorted keys, no whitespace, no NaN, UTF-8. Kept here rather than re-invented so
C13/C14 roots stay comparable with the rest of the control plane.
"""
from __future__ import annotations

import hashlib
import json
import re

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def canonical(value) -> bytes:
    """Deterministic JSON bytes. Raises on NaN/Infinity (never silently emit them)."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value) -> str:
    """Lowercase SHA256 hex of the canonical form of ``value``."""
    return hashlib.sha256(canonical(value)).hexdigest()


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_json(raw):
    """Strict JSON parse: duplicate keys and NaN/Infinity are rejected, not ignored."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate_json_key")
            out[key] = value
        return out

    def constant(_):
        raise ValueError("invalid_json_constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def is_sha256(value) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def is_git_sha(value) -> bool:
    return isinstance(value, str) and bool(GIT_SHA_RE.fullmatch(value))
