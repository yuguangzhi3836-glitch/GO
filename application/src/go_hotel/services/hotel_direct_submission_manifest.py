"""Preparatory evidence contract; validation grants no rights or publication authority.

All references and declarations remain unverified. The future authorized adapter
must resolve ownership, association, original bytes and current rights independently.
No official-site provenance URL is required or synthesized by this contract.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

SCHEMA = "HOTEL_DIRECT_SUBMISSION_V1"
ROLES = frozenset({"HERO", "GALLERY", "ROOM", "DINING", "FACILITY", "MEETING",
                   "POI", "EXTERIOR", "LOBBY", "WELLNESS", "SIGNATURE_SPACE"})
_SECRET_KEYS = frozenset({"password", "passwd", "pwd", "token", "accesstoken",
                         "refreshtoken", "authorization", "cookie", "cookies",
                         "otp", "verificationcode", "验证码", "密码", "secret",
                         "apikey", "credential", "credentials"})
_SECRET_TEXT = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~-]+|(?:password|passwd|access_token|refresh_token|"
    r"api[_-]?key|authorization|cookie|验证码|密码)\s*[:=]|"
    r"https?://[^\s/@:]+:[^\s/@]+@)")


def _fail(path, reason):
    # Do not include user-provided values, which could contain sensitive data.
    raise ValueError(f"DIRECT_SUBMISSION_INVALID:{path}:{reason}")


def _scan(value, depth=0):
    if depth > 16:
        _fail("manifest", "nesting")
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                _fail("manifest", "key_type")
            if re.sub(r"[^\w]", "", key).replace("_", "").lower() in _SECRET_KEYS:
                _fail("manifest", "credentials")
            _scan(child, depth + 1)
    elif type(value) is list:
        if len(value) > 10000:
            _fail("manifest", "list_size")
        for child in value:
            _scan(child, depth + 1)
    elif type(value) is str:
        if len(value) > 4096 or _SECRET_TEXT.search(value):
            _fail("manifest", "sensitive_or_oversize_text")
    elif value is not None and type(value) not in (bool, int):
        _fail("manifest", "json_type")


def _object(value, keys, path):
    if type(value) is not dict or set(value) != set(keys.split()):
        _fail(path, "fields")


def _text(value, path):
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        _fail(path, "text")
    if any(ord(c) < 32 for c in value):
        _fail(path, "control_character")
    return value


def _ids(value, path):
    if type(value) is not list or not value:
        _fail(path, "nonempty_inventory_required")
    result = [_text(v, path) for v in value]
    if len(set(result)) != len(result):
        _fail(path, "duplicate_identity")
    return set(result)


def _integer(value, minimum, maximum, path):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(path, "integer_range")


def _timestamp(value, path):
    _text(value, path)
    # Require explicit seconds and timezone, excluding date-only or naive values.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        _fail(path, "timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _fail(path, "timestamp")


def validate_direct_submission_manifest(manifest, *, expected_sha256=None):
    """Return detached normalized manifest and hash, or ValueError.

    V1 requires one-to-one *physical* room mappings and complete image coverage.
    Combination-sale room entries must be resolved before producing this manifest.
    Inventory completeness is a declaration, not an independently proven fact.
    Hashes bind evidence references, not their external contents or approval status.
    """
    _scan(manifest)
    _object(manifest, "schema identity inventory room_mappings assets", "manifest")
    if manifest["schema"] != SCHEMA:
        _fail("schema", "unsupported")
    identity = manifest["identity"]
    _object(identity, "supplier_id property_id registration_id canonical_hotel_id association_evidence_reference", "identity")
    for key, value in identity.items():
        _text(value, "identity." + key)

    inventory = manifest["inventory"]
    _object(inventory, "partner_room_ids canonical_room_ids complete_confirmed confirmed_by confirmed_at evidence_reference", "inventory")
    if inventory["complete_confirmed"] is not True:
        _fail("inventory", "confirmation_required")
    for key in ("confirmed_by", "evidence_reference"):
        _text(inventory[key], "inventory." + key)
    confirmed_at = _timestamp(inventory["confirmed_at"], "inventory.confirmed_at")
    partner_ids = _ids(inventory["partner_room_ids"], "inventory.partner_room_ids")
    canonical_ids = _ids(inventory["canonical_room_ids"], "inventory.canonical_room_ids")
    mappings = manifest["room_mappings"]
    if type(mappings) is not list or not mappings:
        _fail("room_mappings", "required")
    mapping = {}
    targets = set()
    for row in mappings:
        _object(row, "partner_room_id canonical_room_id confirmed evidence_reference", "room_mappings")
        source = _text(row["partner_room_id"], "room_mappings.partner_room_id")
        target = _text(row["canonical_room_id"], "room_mappings.canonical_room_id")
        _text(row["evidence_reference"], "room_mappings.evidence_reference")
        if row["confirmed"] is not True or source in mapping or target in targets:
            _fail("room_mappings", "unconfirmed_or_duplicate")
        mapping[source] = target
        targets.add(target)
    if set(mapping) != partner_ids or targets != canonical_ids:
        _fail("room_mappings", "inventory_mismatch")

    assets = manifest["assets"]
    if type(assets) is not list or not assets:
        _fail("assets", "required")
    asset_ids, usages, covered = set(), set(), set()
    has_hero = False
    for asset in assets:
        _object(asset, "asset_id supplier_id property_id canonical_hotel_id partner_room_id canonical_room_id role original_sha256 width height byte_size mime_type rights", "assets")
        aid = _text(asset["asset_id"], "assets.asset_id")
        if aid in asset_ids:
            _fail("assets", "duplicate_identity")
        asset_ids.add(aid)
        for key in ("supplier_id", "property_id", "canonical_hotel_id"):
            if asset[key] != identity[key]:
                _fail("assets", "identity_mismatch")
        role = _text(asset["role"], "assets.role")
        if role not in ROLES:
            _fail("assets.role", "unsupported")
        source, target = asset["partner_room_id"], asset["canonical_room_id"]
        if role == "ROOM":
            _text(source, "assets.partner_room_id")
            _text(target, "assets.canonical_room_id")
            if source not in mapping or mapping[source] != target:
                _fail("assets", "room_mismatch")
            covered.add(source)
        elif source is not None or target is not None:
            _fail("assets", "nonroom_binding")
        has_hero |= role == "HERO"
        digest = asset["original_sha256"]
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            _fail("assets.original_sha256", "sha256")
        usage = (digest, role, source, target)
        if usage in usages:
            _fail("assets", "duplicate_usage")
        usages.add(usage)
        for key in ("width", "height"):
            _integer(asset[key], 720, 40000000, "assets." + key)
        if max(asset["width"], asset["height"]) < 1280 or asset["width"] * asset["height"] > 40000000:
            _fail("assets", "resolution")
        _integer(asset["byte_size"], 1, 15 * 1024 * 1024, "assets.byte_size")
        if asset["mime_type"] not in ("image/jpeg", "image/png", "image/webp"):
            _fail("assets.mime_type", "unsupported")
        rights = asset["rights"]
        _object(rights, "rights_holder evidence_reference review_evidence_reference usage_scope expires_at", "assets.rights")
        for key in ("rights_holder", "evidence_reference", "review_evidence_reference"):
            _text(rights[key], "assets.rights." + key)
        if rights["usage_scope"] != ["DISTRIBUTE_ON_GO"]:
            _fail("assets.rights", "scope")
        if rights["expires_at"] is not None:
            expiry = _timestamp(rights["expires_at"], "assets.rights.expires_at")
            if expiry <= confirmed_at:
                _fail("assets.rights", "expired_at_confirmation")
    if covered != partner_ids or not has_hero:
        _fail("assets", "incomplete_coverage")

    normalized = json.loads(json.dumps(manifest, ensure_ascii=False, allow_nan=False))
    normalized["inventory"]["partner_room_ids"] = sorted(partner_ids)
    normalized["inventory"]["canonical_room_ids"] = sorted(canonical_ids)
    normalized["room_mappings"].sort(key=lambda v: v["partner_room_id"])
    normalized["assets"].sort(key=lambda v: v["asset_id"])
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if expected_sha256 is not None:
        if type(expected_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or expected_sha256 != digest:
            _fail("manifest", "hash_mismatch")
    return {"schema": SCHEMA, "manifest": normalized, "manifest_sha256": digest,
            "validation_state": "STRUCTURE_VALID_EVIDENCE_UNVERIFIED",
            "rights_granted": False, "publishable": False, "published": False}
