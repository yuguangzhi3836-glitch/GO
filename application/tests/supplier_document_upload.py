"""The one place that knows the applicant evidence upload transport.

``POST /bff/supplier/legal-entity/documents`` takes a raw octet-stream body: the
frozen runtime image ships no multipart parser, so multipart is not an option and
the metadata travels in the query string while the filename rides in a
percent-encoded header.  Every test that uploads private evidence has to agree on
those three things, so they are stated once here instead of once per call site.
"""
from __future__ import annotations

from urllib.parse import quote

PATH = "/bff/supplier/legal-entity/documents"


def upload_document(client, data, *, filename, mime, headers=None, **fields):
    """POST private evidence exactly as the browser sends it.

    ``fields`` become query parameters (``document_type``, ``scope``,
    ``expected_revision``); ``None`` values are omitted so a caller can pass an
    optional field through without branching.
    """
    params = {name: str(value) for name, value in fields.items() if value is not None}
    request_headers = dict(headers or {})
    request_headers["Content-Type"] = mime
    request_headers["X-Document-Filename"] = quote(filename, safe="")
    return client.post(PATH, headers=request_headers, params=params, content=data)
