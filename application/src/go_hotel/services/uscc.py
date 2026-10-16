"""Unified Social Credit Code (统一社会信用代码) validation — GB 32100-2015.

Only the *provable* rules are enforced as hard blockers:

1. canonicalisation: ``strip`` -> ``upper`` (lower-case input is accepted, never
   rejected — frozen decision CHANGE 4);
2. length == 18;
3. every character is in the 31-symbol code set (``0-9`` plus
   ``A B C D E F G H J K L M N P Q R T U W X Y``; ``I O S V Z`` are excluded);
4. the GB 32100-2015 check symbol matches.

Structural positions (registrar code, entity category, administrative division)
are deliberately **not** hard blockers: we cannot enumerate a complete,
provable set of legal values, and rejecting a legitimately issued code is worse
than accepting one whose structure we cannot verify. They may be surfaced as a
non-blocking hint only.
"""
from __future__ import annotations

from dataclasses import dataclass

CODE_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
CHAR_VALUES = {ch: index for index, ch in enumerate(CODE_CHARS)}
WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
LENGTH = 18


@dataclass(frozen=True)
class UsccResult:
    """Outcome of validating one candidate code."""

    value: str          # canonical (upper-cased) form
    ok: bool
    reason: str | None  # None when ok; otherwise a stable internal code below

    @property
    def error_code(self) -> str | None:
        return self.reason


# Stable internal reasons. They are NOT shown to humans directly: the frontend
# maps ``INVALID_UNIFIED_SOCIAL_CREDIT_CODE`` to human copy (see
# ``frontend/onboarding/onboarding.js``).
REASON_LENGTH = "INVALID_UNIFIED_SOCIAL_CREDIT_CODE_LENGTH"
REASON_CHARSET = "INVALID_UNIFIED_SOCIAL_CREDIT_CODE_CHARSET"
REASON_CHECKSUM = "INVALID_UNIFIED_SOCIAL_CREDIT_CODE_CHECKSUM"


def normalize_uscc(value: str | None) -> str:
    """Canonical form: NFC-safe strip + upper-case. Never raises."""
    return (value or "").strip().upper()


def check_symbol(first_seventeen: str) -> str:
    """Return the GB 32100-2015 check symbol for the first 17 characters."""
    total = sum(CHAR_VALUES[ch] * weight for ch, weight in zip(first_seventeen, WEIGHTS))
    return CODE_CHARS[(31 - total % 31) % 31]


def validate_uscc(value: str | None) -> UsccResult:
    """Validate a candidate code.

    ``ok`` is True only when length, character set and check symbol all pass.
    Lower-case input is accepted (it is canonicalised first).
    """
    canonical = normalize_uscc(value)
    if len(canonical) != LENGTH:
        return UsccResult(canonical, False, REASON_LENGTH)
    if any(ch not in CHAR_VALUES for ch in canonical):
        return UsccResult(canonical, False, REASON_CHARSET)
    if check_symbol(canonical[:17]) != canonical[17]:
        return UsccResult(canonical, False, REASON_CHECKSUM)
    return UsccResult(canonical, True, None)


def structural_hint(value: str | None) -> str | None:
    """Non-blocking hint about the structural positions.

    Returns ``None`` when nothing notable, otherwise a short internal token the
    UI may render as "请核对" advice. This is advisory only — it never blocks a
    submission.
    """
    canonical = normalize_uscc(value)
    if len(canonical) != LENGTH:
        return None
    # Position 1: registrar authority code (must be a digit per GB 32100-2015
    # in common practice); positions 3-8: administrative division.
    if not canonical[0].isdigit():
        return "USCC_STRUCTURE_REGISTRAR_NON_DIGIT"
    if not canonical[2:8].isdigit():
        return "USCC_STRUCTURE_DIVISION_NON_DIGIT"
    return None
