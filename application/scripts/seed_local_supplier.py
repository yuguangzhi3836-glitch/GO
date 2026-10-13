#!/usr/bin/env python3
"""Create a local supplier test account through the registration API.

This script targets loopback only. It does not write to the database directly,
bypass onboarding, or approve the supplier.
"""

from __future__ import annotations

import getpass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8000"
DEFAULT_EMAIL = "local-supplier@example.test"
TERMS_PATH = "/bff/auth/supplier/registration-terms"
REGISTER_PATH = "/bff/auth/supplier/register"


def ensure_loopback(url: str) -> None:
    host = (urlsplit(url).hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Safety check failed: only loopback URLs are allowed.")


def request_json(path: str, *, payload: dict | None = None) -> tuple[int, dict]:
    ensure_loopback(BASE_URL)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        BASE_URL + path,
        data=body,
        headers=headers,
        method="GET" if body is None else "POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read()
            return response.status, json.loads(raw or b"{}")
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read() or b"{}").get("detail", "")
        except (ValueError, AttributeError):
            detail = ""
        return exc.code, {"detail": detail}
    except (URLError, TimeoutError, ConnectionError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        raise RuntimeError(f"Cannot reach local backend at {BASE_URL}: {reason}") from exc


def main() -> int:
    print(f"Local supplier test-account creator (target: {BASE_URL})")
    email = input(f"Email [{DEFAULT_EMAIL}]: ").strip() or DEFAULT_EMAIL
    if "@" not in email or "\n" in email:
        print("Invalid email address.", file=sys.stderr)
        return 2

    password = getpass.getpass("Password (minimum 10 characters; not saved): ")
    if len(password) < 10:
        print("Password must contain at least 10 characters.", file=sys.stderr)
        return 2
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 2

    try:
        status, terms_response = request_json(TERMS_PATH)
        if status != 200:
            print(
                f"Could not read registration terms (HTTP {status}): "
                f"{terms_response.get('detail', 'no detail returned')}",
                file=sys.stderr,
            )
            return 1
        terms = terms_response.get("data", {})
        versions = terms.get("versions")
        if not isinstance(versions, dict) or not versions:
            print("The backend returned no valid registration-term versions.", file=sys.stderr)
            return 1

        payload = {
            "email": email,
            "password": password,
            "accepted_terms": True,
            "term_versions": versions,
        }
        status, result = request_json(REGISTER_PATH, payload=payload)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        password = ""

    if status == 409 and result.get("detail") == "EMAIL_ALREADY_REGISTERED":
        print("That email is already registered; no account was changed.", file=sys.stderr)
        return 1
    if status != 201:
        print(
            f"Registration failed (HTTP {status}): "
            f"{result.get('detail', 'no detail returned')}",
            file=sys.stderr,
        )
        return 1

    data = result.get("data", {})
    print("Supplier account created.")
    print(f"supplier_id: {data.get('supplier_id', '(not returned)')}")
    print(f"registration_state: {data.get('registration_state', '(not returned)')}")
    print(f"next_step: {data.get('next_step', '(not returned)')}")
    print("Profile completion and review are still required before business access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
