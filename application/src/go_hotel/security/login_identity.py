"""Single source of truth for turning a user-entered login identifier into its
canonical storage/lookup form.

Why this module exists
----------------------
An account has **three** login identifiers, all bound to the same account:
``username``, ``email`` and ``phone`` (owner decision, superseding the earlier
D-01/D-11 rule that email was the only identity). Registration and login used to
normalise differently: the register path did ``email.strip().lower()`` while
``IdentityService.login`` looked the identifier up verbatim. A user who
registered ``Foo@Example.COM `` could then fail to authenticate as
``foo@example.com`` with ``INVALID_CREDENTIALS`` — a purely self-inflicted defect
in a flow the owner must be able to complete.

The rule is therefore:

    normalise on every identity write boundary AND every identity read boundary.

Every identifier goes through this module both when it is written and when it is
looked up; ``login`` compares the normalised value against all three columns at
once, so the human never has to say *which* of the three they are using. Shape
*validation* is a separate concern owned by the caller
(``is_email_login_id`` / ``is_phone_login_id``).
"""
from __future__ import annotations

import re
import unicodedata

# Login identifiers are an email address, a mainland mobile number, or an
# internal bootstrap/SSO handle (e.g. ``go_admin``).
_EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE_SHAPE = re.compile(r"1[3-9]\d{9}")
_NON_DIGIT = re.compile(r"\D")

MAX_LOGIN_ID_LENGTH = 128


def normalize_login_id(value: str | None) -> str:
    """Return the canonical form of a textual (non-phone) login identifier.

    * ``None`` becomes ``""``.
    * Unicode is NFC-normalised so visually identical inputs compare equal.
    * Surrounding whitespace is stripped (users paste with a trailing space).
    * The value is lower-cased, because email local parts and our bootstrap
      handles are all treated case-insensitively by this platform.

    This function is intentionally total: it never raises. Shape validation
    (``is_email_login_id``) is a separate concern owned by the caller.
    """
    return unicodedata.normalize("NFC", (value or "").strip()).lower()


def normalize_phone(value: str | None) -> str:
    """Return the canonical (digits-only) form of a mainland mobile number.

    Humans type ``138 0013 8000``, ``138-0013-8000`` or ``+86 138 0013 8000``;
    the stored form is always the bare 11 digits, so a login attempt with any of
    those inputs finds the same account. A leading ``86`` country code is
    dropped. Never raises — the caller decides whether the result is usable
    (``is_phone_login_id``).
    """
    digits = _NON_DIGIT.sub("", unicodedata.normalize("NFC", value or ""))
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits


def is_email_login_id(value: str | None) -> bool:
    """True when the normalised identifier looks like an email address."""
    normalised = normalize_login_id(value)
    return bool(normalised) and len(normalised) <= MAX_LOGIN_ID_LENGTH and bool(
        _EMAIL_SHAPE.fullmatch(normalised)
    )


def is_phone_login_id(value: str | None) -> bool:
    """True when the value is a usable mainland mobile number."""
    return bool(_PHONE_SHAPE.fullmatch(normalize_phone(value)))


def normalize_login_identifier(value: str | None) -> str:
    """Canonicalise *any* of the three accepted login identifiers.

    The value is dispatched by shape, never by which column the caller hopes to
    match. A mobile number collapses to its 11 digits; everything else (an email
    address or a username) is NFC-normalised, stripped and lower-cased. Because
    the three stored columns hold exactly these canonical forms, ``login`` can
    compare the result against all three at once without caring which one the
    human meant.
    """
    text = normalize_login_id(value)
    if _EMAIL_SHAPE.fullmatch(text):
        return text
    phone = normalize_phone(value)
    if _PHONE_SHAPE.fullmatch(phone):
        return phone
    return text
