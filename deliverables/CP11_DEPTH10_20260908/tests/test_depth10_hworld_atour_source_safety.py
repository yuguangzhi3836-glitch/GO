from pathlib import Path
ROOT=Path(__file__).parents[1]
SRC=ROOT/"src/go_hotel/services"
def t(name):return (SRC/name).read_text()

def test_atour_com_is_never_an_approved_atour_source():
    registry=t("chain_hotel_registry.py")
    atour=registry[registry.index("ChainCode.ATOUR:ChainPolicy"):]
    assert '"atour.com"' not in atour.split("},",1)[0]
    assert '"yaduo.com"' in atour

def test_unverified_hworld_and_atour_still_fail_closed():
    source=t("chain_official_source_contracts.py")
    assert 'ChainCode.H_WORLD:OfficialSourceContract' in source
    assert 'ChainCode.ATOUR:OfficialSourceContract' in source
    assert source.count("FULL_DIRECTORY_NOT_YET_VERIFIED")>=3

def test_runtime_inventory_requires_explicit_ids_and_official_urls():
    source=t("public_runtime_inventory_contract.py")
    assert "CHAIN_RUNTIME_SOURCE_NOT_OFFICIAL" in source
    assert "CHAIN_RUNTIME_EXPLICIT_PROPERTY_INVENTORY_NOT_FOUND" in source
    assert "CHAIN_RUNTIME_PROPERTY_ID_CONFLICT" in source

def test_runtime_inventory_requires_independent_stable_captures():
    source=t("public_runtime_inventory_contract.py")
    assert "minimum_independent_captures:int=2" in source
    assert "CHAIN_RUNTIME_INVENTORY_DRIFT" in source

def test_partner_api_is_not_a_contract_requirement():
    source=t("chain_official_source_contracts.py")
    assert "GO does not require a partner API" in source
    assert "browser-visible XHR/JSON/GraphQL" in source
