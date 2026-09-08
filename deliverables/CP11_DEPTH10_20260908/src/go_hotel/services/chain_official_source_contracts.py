"""Per-chain official source contracts for autonomous directory acquisition.

GO does not require a partner API. A source contract may be an official public page,
a browser-visible XHR/JSON/GraphQL response, or hydration data used by that page.
What matters is official-host provenance, deterministic property identity, complete
inventory evidence and reproducible snapshot semantics. Unverified chains fail closed.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .chain_hotel_registry import ChainCode
class DirectoryReadiness(str,Enum):
    VERIFIED_FULL_DIRECTORY="VERIFIED_FULL_DIRECTORY";VERIFIED_DIRECTORY_ENTRYPOINT="VERIFIED_DIRECTORY_ENTRYPOINT";FULL_DIRECTORY_NOT_YET_VERIFIED="FULL_DIRECTORY_NOT_YET_VERIFIED"
@dataclass(frozen=True)
class OfficialSourceContract:
    chain:ChainCode;directory_url:str;readiness:DirectoryReadiness;required_text_markers:tuple[str,...];property_identity_strategy:str;notes:str
CONTRACTS={
ChainCode.HYATT:OfficialSourceContract(ChainCode.HYATT,"https://www.hyatt.com/explore-hotels/map/hyatt-hotels/china",DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT,("Hyatt",),"HYATT_OFFICIAL_PROPERTY_CODE","Dedicated Hyatt adapter retains snapshot/cursor parser; full cohort truth is runtime-gated."),
ChainCode.MARRIOTT:OfficialSourceContract(ChainCode.MARRIOTT,"https://www.marriott.com/en-us/hotel-search.mi",DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT,("Property Directory","View All Hotels"),"MARRIOTT_PROPERTY_CODE_FROM_OFFICIAL_PROPERTY_URL","Official Property Directory entrypoint is verified; hierarchical traversal must prove complete property coverage before PASS."),
ChainCode.SHANGRI_LA:OfficialSourceContract(ChainCode.SHANGRI_LA,"https://www.shangri-la.com/cn/find-a-hotel/",DirectoryReadiness.VERIFIED_FULL_DIRECTORY,("中国内地","香格里拉"),"SHANGRILA_CITY_AND_PROPERTY_SLUG","Official Find a Hotel list exposes the verified regional property inventory under the approved host contract."),
ChainCode.HILTON:OfficialSourceContract(ChainCode.HILTON,"https://www.hilton.com/en/locations/",DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT,("Hotel Locations","Asia"),"HILTON_OFFICIAL_PROPERTY_SLUG_OR_CODE","Official locations tree is an entrypoint; hierarchical traversal/runtime evidence must prove full coverage."),
ChainCode.IHG:OfficialSourceContract(ChainCode.IHG,"https://www.ihg.com/hotels/cn/zh/reservation",DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT,("洲际酒店集团","酒店"),"IHG_OFFICIAL_HOTEL_CODE","Official destination entrypoint only; full inventory semantics remain runtime-gated."),
ChainCode.H_WORLD:OfficialSourceContract(ChainCode.H_WORLD,"https://www.hworld.com/",DirectoryReadiness.FULL_DIRECTORY_NOT_YET_VERIFIED,("华住","酒店"),"HWORLD_BROWSER_VISIBLE_OFFICIAL_HOTEL_ID_REQUIRED","hworld.com is verified official and publicly reports group scale, but the homepage is not a complete property inventory. GO must discover and freeze the public official booking/app page data contract itself; no partner API is required."),
ChainCode.ATOUR:OfficialSourceContract(ChainCode.ATOUR,"https://ir.yaduo.com/",DirectoryReadiness.FULL_DIRECTORY_NOT_YET_VERIFIED,("Atour",),"ATOUR_BROWSER_VISIBLE_OFFICIAL_HOTEL_ID_REQUIRED","Atour Lifestyle's verified corporate/IR web presence is under yaduo.com. atour.com is forbidden. A complete public hotel inventory page/runtime data contract is not yet verified, so hotel enumeration remains fail-closed while GO discovers it itself."),}
def contract_for(chain:ChainCode)->OfficialSourceContract:
    try:return CONTRACTS[chain]
    except KeyError as exc:raise ValueError("CHAIN_OFFICIAL_SOURCE_CONTRACT_MISSING") from exc
def assert_directory_production_ready(chain:ChainCode)->OfficialSourceContract:
    contract=contract_for(chain)
    if contract.readiness==DirectoryReadiness.FULL_DIRECTORY_NOT_YET_VERIFIED:raise ValueError(f"CHAIN_FULL_DIRECTORY_CONTRACT_HOLD:{chain.value}")
    return contract
def validate_contract_document(chain:ChainCode,*,final_url:str,text:str)->None:
    contract=assert_directory_production_ready(chain)
    if not final_url.startswith("https://"):raise ValueError("CHAIN_CONTRACT_HTTPS_REQUIRED")
    missing=[marker for marker in contract.required_text_markers if marker not in text]
    if missing:raise ValueError(f"CHAIN_CONTRACT_MARKER_MISSING:{chain.value}:{','.join(missing)}")
