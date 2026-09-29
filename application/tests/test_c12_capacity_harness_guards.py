"""The capacity driver must reject non-disposable databases before connecting."""
import importlib.util
from pathlib import Path
import pytest

pytestmark=pytest.mark.no_db
spec=importlib.util.spec_from_file_location('c12_capacity_driver',Path(__file__).resolve().parents[1]/'ci/next_depth/c12_transaction_capacity.py')
driver=importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


@pytest.mark.parametrize('url',[
    'postgresql+psycopg://go_ci:x@production.example:5432/go_c11_isolated',
    'postgresql+psycopg://go_ci:x@127.0.0.1:5432/business',
    'postgresql+psycopg://admin:x@127.0.0.1:5432/go_c11_isolated',
    'postgresql+psycopg://go_ci:x@127.0.0.1:5433/go_c11_isolated',
    'postgresql+psycopg://go_ci:x@127.0.0.1:5432/go_c11_isolated?options=-csearch_path=public',
    'postgresql+psycopg://go_ci:x@127.0.0.1:5432/go_c11_isolated?host=production.example',
    'sqlite:///production.db',
    'postgresql+psycopg://go_ci:x@127.0.0.1:5432/go_c11_isolated?service=production',
])
def test_rejects_non_disposable_or_overridden_database(url):
    with pytest.raises(ValueError,match='C12_DISPOSABLE_LOOPBACK_PG_REQUIRED'):
        driver.validate_url(url)


def test_only_explicit_loopback_service_is_accepted_without_connecting():
    url=driver.validate_url('postgresql+psycopg://go_ci:isolated_ci_only@127.0.0.1:5432/go_c11_isolated')
    assert url.database=='go_c11_isolated'


def test_egress_guard_refuses_external_connection():
    import socket
    from types import SimpleNamespace
    with pytest.raises(PermissionError,match='ISOLATED_EXTERNAL_EGRESS_FORBIDDEN'):
        driver.guard('socket.connect',(SimpleNamespace(family=socket.AF_INET),('8.8.8.8',443)))
