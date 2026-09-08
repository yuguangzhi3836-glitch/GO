import base64,json
from go_hotel.services.hierarchical_chain_directory import _decode


def decode(cursor):
    raw=base64.urlsafe_b64decode(cursor.encode()+b"="*(-len(cursor)%4));return json.loads(raw)


def test_new_cursor_starts_discovery_without_emission():
    state=_decode(None,"https://example.com/root")
    assert state["phase"]=="DISCOVER"
    assert state["emitted"]==0
    assert state["frozen_inventory"] is None


def test_emit_cursor_requires_frozen_inventory_digest():
    state=_decode(None,"https://example.com/root")
    state["phase"]="EMIT";state["frontier"]=[];state["frozen_inventory"]=[];state["inventory_sha256"]="wrong"
    raw=base64.urlsafe_b64encode(json.dumps(state).encode()).decode().rstrip("=")
    try:_decode(raw,"https://example.com/root")
    except ValueError as exc:assert "FROZEN_INVENTORY_TAMPERED" in str(exc)
    else:raise AssertionError("tampered frozen inventory must fail closed")


def test_cursor_contract_contains_redirect_aliases():
    state=_decode(None,"https://example.com/root")
    assert "aliases" in state


def test_discovery_phase_never_has_frozen_inventory():
    state=_decode(None,"https://example.com/root")
    assert state["phase"]=="DISCOVER" and state["frozen_inventory"] is None
