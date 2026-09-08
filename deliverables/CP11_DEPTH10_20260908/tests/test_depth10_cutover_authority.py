import pytest

from go_hotel.services import regional_build_cutover


def test_authority_defaults_to_postgres(monkeypatch):
    monkeypatch.delenv("GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER", raising=False)
    status = regional_build_cutover.authority()
    assert status["queue_authority"] == "POSTGRES_DURABLE_LEASE_ACK"
    assert status["legacy_redis_default"] is False
    assert status["legacy_redis_break_glass_enabled"] is False


def test_legacy_redis_is_disabled_without_break_glass(monkeypatch):
    monkeypatch.delenv("GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER", raising=False)
    with pytest.raises(ValueError, match="LEGACY_REDIS_REGIONAL_WORKER_DISABLED"):
        regional_build_cutover.legacy_redis_enqueue({"city": "Harbin"})
