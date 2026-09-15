from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from go_hotel.services.media_harvester import MediaHarvesterService


def _jpeg_bytes(size=(320, 240), rgb=(90, 120, 150)) -> bytes:
    bio = BytesIO()
    Image.new("RGB", size, rgb).save(bio, format="JPEG", quality=88)
    return bio.getvalue()


def _transport() -> httpx.MockTransport:
    image = _jpeg_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/ok.jpg":
            return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=image, request=request)
        if p == "/not-image":
            return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"not an image", request=request)
        if p == "/forbidden":
            return httpx.Response(403, content=b"", request=request)
        if p == "/redirect-ok":
            return httpx.Response(302, headers={"Location": "https://media.test/ok.jpg"}, request=request)
        return httpx.Response(404, request=request)

    return httpx.MockTransport(handler)


def _svc(tmp_path: Path) -> MediaHarvesterService:
    return MediaHarvesterService(tmp_path / "cache", transport=_transport())


def test_download_cache_room_binding_and_rights_gate(tmp_path: Path):
    svc = _svc(tmp_path)
    rec = svc.harvest(
        source_url="https://media.test/ok.jpg",
        hotel_id="hotel_aoluguya",
        role="ROOM",
        room_type_id="room_dreamweaver_king",
        source_type="GROUP_OFFICIAL",
        allow_private=True,
    )
    assert rec["cache_state"] == "VALIDATED"
    assert rec["rights_state"] == "RIGHTS_UNKNOWN"
    assert rec["publishable"] is False
    assert rec["room_type_id"] == "room_dreamweaver_king"
    assert (rec["width"], rec["height"]) == (320, 240)
    assert svc.content_path(rec["asset_id"], require_publishable=False).is_file()
    with pytest.raises(ValueError, match="MEDIA_ASSET_NOT_PUBLISHABLE"):
        svc.content_path(rec["asset_id"], require_publishable=True)

    approved = svc.decide_rights(
        rec["asset_id"], rights_state="AUTHORIZED", actor="admin_media",
        rights_owner="Hyatt Hotels Corporation",
        evidence_reference="contract://media-license/aoluguya/2026-08",
    )
    assert approved["publishable"] is True
    assert approved["rights_history"][-1]["to"]["rights_state"] == "AUTHORIZED"
    grouped = svc.page_media("hotel_aoluguya")
    assert len(grouped["rooms"]["room_dreamweaver_king"]) == 1
    assert grouped["rooms"]["room_dreamweaver_king"][0]["url"].startswith("/v1/hotel-media/media_")

    revoked = svc.decide_rights(rec["asset_id"], rights_state="REJECTED", actor="admin_media")
    assert revoked["publishable"] is False
    assert len(revoked["rights_history"]) == 2


def test_fail_closed_download_rights_ssrf_dedup_and_integrity(tmp_path: Path):
    svc = _svc(tmp_path)
    with pytest.raises(ValueError, match="MEDIA_ROOM_TYPE_ID_REQUIRED"):
        svc.harvest(source_url="https://media.test/ok.jpg", hotel_id="h1", role="ROOM", allow_private=True)
    with pytest.raises(ValueError, match="MEDIA_DOWNLOAD_HTTP_403"):
        svc.harvest(source_url="https://media.test/forbidden", hotel_id="h1", role="HERO", allow_private=True)
    with pytest.raises(ValueError, match="MEDIA_CONTENT_NOT_VALID_IMAGE"):
        svc.harvest(source_url="https://media.test/not-image", hotel_id="h1", role="HERO", allow_private=True)
    with pytest.raises(ValueError, match="MEDIA_SOURCE_PRIVATE_OR_UNRESOLVABLE_BLOCKED"):
        svc.harvest(source_url="http://127.0.0.1:1/secret.jpg", hotel_id="h1", role="HERO")

    a = svc.harvest(source_url="https://media.test/ok.jpg", hotel_id="h1", role="HERO", allow_private=True)
    b = svc.harvest(source_url="https://media.test/ok.jpg", hotel_id="h1", role="GALLERY", allow_private=True)
    assert a["sha256"] == b["sha256"] and a["cache_file"] == b["cache_file"]
    assert len(list((tmp_path / "cache" / "files").iterdir())) == 1
    with pytest.raises(ValueError, match="MEDIA_PUBLISHABLE_RIGHTS_EVIDENCE_REQUIRED"):
        svc.decide_rights(a["asset_id"], rights_state="LICENSED", actor="admin")

    redirected = svc.harvest(source_url="https://media.test/redirect-ok", hotel_id="h1", role="GALLERY", allow_private=True)
    assert redirected["resolved_url"].endswith("/ok.jpg")
    path = svc.content_path(redirected["asset_id"], require_publishable=False)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="MEDIA_CACHE_INTEGRITY_FAILED"):
        svc.content_path(redirected["asset_id"], require_publishable=False)


def test_rights_expiry_and_scope_fail_closed(tmp_path: Path):
    svc = _svc(tmp_path)
    rec = svc.harvest(
        source_url="https://media.test/ok.jpg",
        hotel_id="hotel_aoluguya",
        role="GALLERY",
        source_type="GROUP_OFFICIAL",
        allow_private=True,
    )
    approved = svc.decide_rights(
        rec["asset_id"],
        rights_state="LICENSED",
        actor="admin_media",
        rights_owner="Example Rights Owner",
        evidence_reference="contract://media/2026",
        expires_at="2099-01-01T00:00:00+00:00",
        rights_scope="GO_CONSUMER_HOTEL_PAGE",
        rights_regions=["CN"],
    )
    assert approved["publishable"] is True
    assert approved["rights_scope"] == "GO_CONSUMER_HOTEL_PAGE"
    assert approved["rights_regions"] == ["CN"]
    assert svc.content_path(rec["asset_id"], require_publishable=True).is_file()

    expired = svc.decide_rights(
        rec["asset_id"],
        rights_state="LICENSED",
        actor="admin_media",
        rights_owner="Example Rights Owner",
        evidence_reference="contract://media/expired",
        expires_at="2000-01-01T00:00:00+00:00",
        rights_scope="GO_CONSUMER_HOTEL_PAGE",
        rights_regions=["CN"],
    )
    assert expired["publishable"] is False
    assert svc.list_assets(hotel_id="hotel_aoluguya", publishable_only=True) == []
    with pytest.raises(ValueError, match="MEDIA_ASSET_NOT_PUBLISHABLE"):
        svc.content_path(rec["asset_id"], require_publishable=True)
