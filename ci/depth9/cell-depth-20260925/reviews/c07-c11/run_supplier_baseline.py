"""Run current regression against the exact PR #246 supplier service in memory."""
import importlib.util
from pathlib import Path
import pytest
import sys
sys.path.insert(0, str(Path.cwd()))


class OriginalService:
    def pytest_collection_modifyitems(self, items):
        path = Path(__file__).with_name('original_order_supplier_fulfillment.py')
        spec = importlib.util.spec_from_file_location('original_fulfillment_baseline', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for item in items:
            item.module.svc = module.order_supplier_fulfillment_service


raise SystemExit(pytest.main([
    'tests/test_c10_supplier_money_projection.py',
    '--junitxml=/workspace/scratch/cdb63add4518/reviews/c07-c11/supplier-money-baseline.xml',
], plugins=[OriginalService()]))
