from pathlib import Path
import pytest

pytestmark=pytest.mark.no_db


def test_rc19_regional_throughput_contract():
    root=Path(__file__).resolve().parents[1]
    regional=(root/'src/go_hotel/services/regional_hotel_build.py').read_text('utf-8')
    discovery=(root/'src/go_hotel/services/hotel_discovery_orchestrator.py').read_text('utf-8')
    worker=(root/'src/go_hotel/workers/regional_hotel_build_worker.py').read_text('utf-8')
    compose=(root/'docker-compose.staging.yml').read_text('utf-8')
    ui=(root/'frontend/admin/hotel-page-factory.js').read_text('utf-8')
    assert 'OSM_FALLBACK_ENDPOINT' in regional
    assert 'REGIONAL_PROVIDER_MAX_ATTEMPTS' in regional
    assert "task':'HOTEL'" in regional or '"task":"HOTEL"' in regional
    assert 'duplicates_removed' in regional
    assert 'read_timeout=min(max(requested,12.0),90.0)' in discovery
    assert "GO_HOTEL_REGION_WORKER_CONCURRENCY','6'" in worker
    assert 'GO_HOTEL_REGION_WORKER_CONCURRENCY' in compose
    assert '异常中心摘要' in ui and '系统自动运行' in ui
    assert '当前批次发现' in ui and '已发布页面' in ui
    assert 'Number(overview.published_pages||0)' in ui
    assert 'Number(overview.total_pages||0)' not in ui


def test_rc19_full_ecosystem_completeness_contract():
    root=Path(__file__).resolve().parents[1]
    routes=(root/'src/go_hotel/api/routes/operations_console.py').read_text('utf-8')
    ui=(root/'frontend/shared/app.js').read_text('utf-8')
    for vertical in ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']:
        assert vertical in routes
    for stage in ['SUPPLY','OFFER','AVAILABILITY','ORDER','PAYMENT','FULFILLMENT','CHANGE_CANCEL_REFUND','SETTLEMENT_EVIDENCE','EXCEPTION_RECOVERY']:
        assert stage in routes
    assert "/product-completeness" in routes
    assert 'RC20 模块深度验收' in ui
    assert '正式外部供给按 Provider 上线状态单独验收' in ui


def test_rc19_cache_buster_on_both_operational_entrypoints():
    root=Path(__file__).resolve().parents[1]
    for rel in ['frontend/admin/index.html','frontend/supplier/index.html']:
        text=(root/rel).read_text('utf-8')
        assert '20260825-rc20' in text
        assert '20260825-rc19' not in text
