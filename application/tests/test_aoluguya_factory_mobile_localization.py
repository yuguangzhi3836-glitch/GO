from pathlib import Path
import re

import pytest

pytestmark = pytest.mark.no_db


def _frontend():
    root = Path(__file__).resolve().parents[1]
    return (
        (root / "frontend/admin/hotel-page-factory.js").read_text("utf-8"),
        (root / "frontend/shared/styles.css").read_text("utf-8"),
    )


def test_hotel_factory_translates_known_catalog_anomalies():
    ui, _ = _frontend()
    expected = {
        "ADDRESS_MISSING": "酒店地址待完善",
        "ROOMS_MISSING": "房型资料缺失",
        "POLICIES_MISSING": "酒店政策缺失",
        "FACILITIES_MISSING": "酒店设施缺失",
        "CATALOG_MANIFEST_MISSING": "房型目录清单缺失",
        "MEDIA_CANDIDATES_MISSING": "媒体候选资料缺失",
        "DECLARED_ROOM_IDENTITIES_REQUIRED": "房型唯一身份待确认",
        "ROOM_IDENTITIES_NOT_UNIQUE": "房型唯一身份存在重复",
        "DECLARED_ROOM_PARITY_INCOMPLETE": "已声明房型尚未全部匹配",
        "FULL_ROOM_TYPE_INVENTORY_NOT_VERIFIED": "全部房型目录尚未核验",
        "INVENTORY_REVIEW_DOCUMENT_MISMATCH": "房型核验文件不一致",
        "VERIFIED_OFFICIAL_HERO_MISSING": "官方主图未核验",
        "ROOM_OFFICIAL_PHOTO_PARITY_INCOMPLETE": "房型官方图片绑定不完整",
    }
    for code, label in expected.items():
        assert f"{code}:'{label}'" in ui
    assert "esc(anomalyLabel(x))" in ui
    assert "esc(x.label)" not in ui


def test_hotel_factory_unknown_internal_code_is_not_exposed():
    ui, _ = _frontend()
    assert "/^[A-Z][A-Z0-9_]+$/" in ui
    assert "return '资料项待人工确认'" in ui


def test_hotel_factory_anomaly_rows_wrap_on_mobile():
    ui, css = _frontend()
    assert 'business-fact factory-anomaly-row' in ui
    assert ".factory-anomaly-row" in css
    assert "minmax(0,1fr)" in css
    assert "overflow-wrap:anywhere" in css
    assert re.search(r"@media\(max-width:620px\).*?\.factory-anomaly-row", css, re.S)
