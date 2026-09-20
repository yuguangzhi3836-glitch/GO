"""WSGI entrypoint. Cloud Run IAM is the sole caller-authentication boundary."""
from __future__ import annotations

import json
import os
from typing import Callable

from c14_signer import Rejected, configured_backend, sign_receipt


def application(environ: dict, start_response: Callable):
    if environ.get("REQUEST_METHOD") != "POST" or environ.get("PATH_INFO") != "/v1/c14/receipts":
        start_response("404 Not Found", [("Content-Type", "application/json")])
        return [b'{"error":"NOT_FOUND"}']
    if environ.get("CONTENT_TYPE", "").split(";", 1)[0] != "application/json":
        start_response("415 Unsupported Media Type", [("Content-Type", "application/json")])
        return [b'{"error":"JSON_REQUIRED"}']
    try:
        length = int(environ.get("CONTENT_LENGTH", "0"))
        if length < 1 or length > 4096:
            raise Rejected("INVALID_BODY_LENGTH")
        request = json.loads(environ["wsgi.input"].read(length))
        issuer = os.environ.get("C14_SIGNER_ISSUER", "")
        response = sign_receipt(request, configured_backend(), issuer=issuer)
        body, code = json.dumps(response, sort_keys=True, separators=(",", ":")).encode(), "200 OK"
    except (ValueError, json.JSONDecodeError, Rejected) as exc:
        body, code = json.dumps({"error": str(exc)}).encode(), "400 Bad Request"
    except Exception:
        body, code = b'{"error":"SIGNER_UNAVAILABLE"}', "503 Service Unavailable"
    start_response(code, [("Content-Type", "application/json"), ("Cache-Control", "no-store")])
    return [body]
