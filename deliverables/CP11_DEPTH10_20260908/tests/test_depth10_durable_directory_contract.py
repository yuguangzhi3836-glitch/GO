from go_hotel.services.durable_hierarchical_chain_directory import _encode_cursor,_decode_cursor
from go_hotel.services.chain_autonomous_build import DURABLE_HIERARCHICAL
from go_hotel.services.chain_hotel_registry import ChainCode

def test_external_cursor_is_tiny_reference_not_inventory():
    cursor=_encode_cursor(chain="MARRIOTT",snapshot_id="dirsnap_abc",revision=7)
    assert len(cursor)<256
    decoded=_decode_cursor(cursor)
    assert set(decoded)=={"v","chain","snapshot_id","revision"}
    assert "frontier" not in decoded and "properties" not in decoded and "frozen_inventory" not in decoded

def test_stale_or_cross_chain_cursor_contract_is_bound():
    token=_decode_cursor(_encode_cursor(chain="HILTON",snapshot_id="dirsnap_x",revision=2))
    assert token["chain"]=="HILTON" and token["revision"]==2

def test_three_hierarchical_chains_use_pg_authority():
    assert DURABLE_HIERARCHICAL=={ChainCode.MARRIOTT,ChainCode.HILTON,ChainCode.IHG}
