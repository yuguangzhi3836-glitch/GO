"""Direct HTTP acceptance on synthetic fixtures; NOT browser acceptance.

PYTHONPATH=src python tests/manual/hotel_library_http_acceptance.py
"""
import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request

import uvicorn
import hotel_library_browser_harness as fixture

server = uvicorn.Server(uvicorn.Config(fixture.app, host="127.0.0.1", port=8765, log_level="warning"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
deadline = time.monotonic() + 10
while not server.started:
    if time.monotonic() > deadline:
        raise RuntimeError("Fixture HTTP server failed to start")
    time.sleep(0.05)

results = []


def request(path, body=None, expected=200):
    raw = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:8765" + path, data=raw, headers={"Content-Type": "application/json"})
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    data = response.read()
    assert response.status == expected, (path, response.status, data.decode(errors="replace"))
    return json.loads(data) if "json" in response.headers.get("Content-Type", "") else data


def passed(name):
    results.append(name)
    print("PASS " + name, flush=True)


try:
    page = request("/")
    code = request("/candidate-component.js")
    actual, digest = fixture.component_source()
    assert code.decode() == actual and digest.encode() in page
    passed("candidate component bytes and full-source SHA are served unchanged")

    properties = request("/v1/supplier/properties")["data"]
    assert len(properties) == 2
    first, second = properties
    a = "/v1/supplier/properties/" + first["property_id"]
    b = "/v1/supplier/properties/" + second["property_id"]
    graph_a = request(a + "/product-graph")["data"]
    graph_b = request(b + "/product-graph")["data"]
    assert len(graph_a["room_types"]) == len(graph_b["room_types"]) == 2
    passed("two selected hotel endpoints return their distinct room sets")

    room_id = graph_a["room_types"][0]["room_type_id"]
    package = {"provider": "CTRIP", "method": "DATA_EXPORT", "selected_fields": ["hotel.contacts", "room_types"],
               "hotel_package": {"hotel": {"contacts": {"phone": "000-UPDATED-TEST"}},
                                 "room_types": [{"source_room_id": "synthetic-ctrip-room-1", "name_zh": "已映射的测试房型", "physical_room_count": 5, "occupancy": {"max_occupancy": 2, "max_adults": 2, "max_children": 0}}]},
               "room_mappings": [{"source_room_id": "synthetic-ctrip-room-1", "target_room_type_id": room_id, "confirmed": True}]}
    imported = request(a + "/one-click-import", package)["data"]
    assert imported["status"] == "IMPORTED"
    request(a + "/one-click-import", package)
    after_a = request(a + "/product-graph")["data"]
    assert len(after_a["room_types"]) == 2
    assert request(b + "/product-graph")["data"] == graph_b
    passed("selected-field mapped room import and repeat preserve room count and other hotel")

    raw = request("/fixture-image.jpg")
    upload = request(a + "/media-uploads", {"content_base64": base64.b64encode(raw).decode(), "role": "GALLERY",
                     "rights": {"rights_holder": "SYNTHETIC HOTEL", "evidence_reference": "GENERATED TEST IMAGE", "usage_scope": ["DISTRIBUTE_ON_GO"]}}, 201)["data"]
    assert upload["width"] == 1600 and upload["height"] == 900 and upload["publishable"] is False
    assert hashlib.sha256(request(upload["original_url"])).digest() == hashlib.sha256(raw).digest()
    passed("decoded high-resolution upload and exact original bytes round trip")

    binding_url = a + "/media-uploads/" + upload["asset_id"] + "/binding"
    request(binding_url, {"expected_revision": upload["revision"], "role": "ROOM", "room_type_id": graph_b["room_types"][0]["room_type_id"]}, 404)
    bound = request(binding_url, {"expected_revision": upload["revision"], "role": "ROOM", "room_type_id": room_id})["data"]
    assert bound["room_type_id"] == room_id and bound["publishable"] is False
    passed("cross-hotel room binding rejected and selected room binding remains nonpublic")

    body = {"asset_ids": [bound["asset_id"]], "confirmed": True}
    publication = request(a + "/media-publication-requests", body)["data"]
    assert publication["publication_state"] == "PUBLISH_REQUESTED" and publication["published"] is False
    assert request(a + "/product-graph")["data"]["property"]["publication_state"] == "DRAFT"
    assert len(request(b + "/media-uploads")["data"]) == 0
    passed("publication request does not publish hotel or leak media to other hotel")

    print(json.dumps({"status": "PASS", "passed": len(results), "tests": results,
                      "app_js_sha256": digest, "browser_acceptance": "BLOCKED_ERR_BLOCKED_BY_CLIENT",
                      "authentication": "SYNTHETIC_TEST_DEPENDENCY_OVERRIDE"}, indent=2), flush=True)
finally:
    server.should_exit = True
    thread.join(timeout=10)
