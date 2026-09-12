from pathlib import Path
import pytest
pytestmark=pytest.mark.no_db

def test_rc179_regional_build_contract():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/regional_hotel_build.py').read_text('utf-8')
    routes=(root/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text('utf-8')
    ui=(root/'frontend/admin/hotel-page-factory.js').read_text('utf-8')
    worker=(root/'src/go_hotel/workers/regional_hotel_build_worker.py').read_text('utf-8')
    for token in ['NATIONAL','REGION','REGIONAL_BUILD_CITY_ENQUEUED','REGIONAL_BUILD_CITY_FINISHED','retry_failures','Canonical','province_summary']:
        assert token in service
    for route in ['/internal/v1/hotel-infrastructure/build-runs','/internal/v1/hotel-infrastructure/exceptions','/retry']:
        assert route in routes
    for label in ['全国酒店数字基础设施控制台','一键全国分层建库','指定区域建库','异常中心摘要','页面产量','province-coverage-grid']:
        assert label in ui
    assert 'hotel-regional-build' in service and 'regional_hotel_build_service.process_message' in worker
    assert 'frontend' not in service.lower()

def test_admin_no_longer_requires_single_hotel_seed_as_primary_entry():
    root=Path(__file__).resolve().parents[1]
    ui=(root/'frontend/admin/hotel-page-factory.js').read_text('utf-8')
    render=ui[ui.index('async function render'):ui.index('async function openHotel')]
    assert 'factoryCreate' not in render
    assert 'nationalBuild' in render and 'regionBuild' in render
    # Manual single-hotel helper may remain in source for compatibility but is not an Admin primary action.
    assert '一次只建立一家酒店' not in render


def test_supplier_manual_add_is_retained_as_secondary_flow():
    root=Path(__file__).resolve().parents[1]
    app=(root/'frontend/shared/app.js').read_text('utf-8')
    assert '添加我的酒店' in app
    assert 'GO 会自动建立全国酒店库' in app
