import pytest

from go_hotel.services import production_bindings as bindings


def test_production_authorities_are_durable(monkeypatch):
    monkeypatch.delenv("GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER", raising=False)
    state = bindings.production_authorities()
    assert state["regional_queue"] == "POSTGRES_DURABLE_LEASE_ACK"
    assert state["legacy_redis_default"] is False
    assert state["media_metadata"] == "POSTGRES_DURABLE_MEDIA_LEDGER"
    assert state["media_local_json_authority"] is False
    assert state["chain_task_authority"] == "POSTGRES_DURABLE_LEASE_ACK"
    assert state["release_safe"] is True


def test_media_binding_is_durable_service():
    assert bindings.media_harvester.__class__.__name__ == "DurableMediaHarvesterService"


def test_break_glass_makes_release_unsafe(monkeypatch):
    monkeypatch.setenv("GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER", "true")
    assert bindings.production_authorities()["release_safe"] is False
