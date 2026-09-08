"""Per-chain official source contracts for autonomous directory acquisition.

A chain adapter is not considered production-ready merely because a regex matches.
Each contract names the approved official directory entrypoint, the expected page
semantics and the durable property identity strategy. Contracts that do not yet
have a verified full-property directory stay HOLD rather than pretending that the
homepage is a complete inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .chain_hotel_registry import ChainCode


class DirectoryReadiness(str, Enum):
    VERIFIED_FULL_DIRECTORY = "VERIFIED_FULL_DIRECTORY"
    VERIFIED_DIRECTORY_ENTRYPOINT = "VERIFIED_DIRECTORY_ENTRYPOINT"
    FULL_DIRECTORY_NOT_YET_VERIFIED = "FULL_DIRECTORY_NOT_YET_VERIFIED"


@dataclass(frozen=True)
class OfficialSourceContract:
    chain: ChainCode
    directory_url: str
    readiness: DirectoryReadiness
    required_text_markers: tuple[str, ...]
    property_identity_strategy: str
    notes: str


CONTRACTS = {
    ChainCode.HYATT: OfficialSourceContract(
        chain=ChainCode.HYATT,
        directory_url="https://www.hyatt.com/explore-hotels/map/hyatt-hotels/china",
        readiness=DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT,
        required_text_markers=("Hyatt",),
        property_identity_strategy="HYATT_OFFICIAL_PROPERTY_CODE",
        notes="Dedicated Hyatt adapter retains its own snapshot/cursor parser and official-property-code contract.",
    ),
    ChainCode.MARRIOTT: OfficialSourceContract(
        chain=ChainCode.MARRIOTT,
        directory_url="https://www.marriott.com/en-us/hotel-search.mi",
        readiness=DirectoryReadiness.VERIFIED_FULL_DIRECTORY,
        required_text_markers=("Property Directory", "View All Hotels"),
        property_identity_strategy="MARRIOTT_PROPERTY_CODE_FROM_OFFICIAL_PROPERTY_URL",
        notes="Official Marriott Property Directory; property identity must come from the official URL code, never display text.",
    ),
    ChainCode.SHANGRI_LA: OfficialSourceContract(
        chain=ChainCode.SHANGRI_LA,
        directory_url="https://www.shangri-la.com/cn/find-a-hotel/",
        readiness=DirectoryReadiness.VERIFIED_FULL_DIRECTORY,
        required_text_markers=("中国内地", "香格里拉"),
        property_identity_strategy="SHANGRILA_CITY_AND_PROPERTY_SLUG",
        notes="Official Find a Hotel list exposes full regional inventory and brand variants under shangri-la.com.",
    ),
    ChainCode.HILTON: OfficialSourceContract(
        chain=ChainCode.HILTON,
        directory_url="https://www.hilton.com/en/locations/",
        readiness=DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT,
        required_text_markers=("Hotel Locations", "Asia"),
        property_identity_strategy="HILTON_OFFICIAL_PROPERTY_SLUG_OR_CODE",
        notes="Official locations tree is authoritative discovery entrypoint; dynamic hotel hydration must be captured from official responses.",
    ),
    ChainCode.IHG: OfficialSourceContract(
        chain=ChainCode.IHG,
        directory_url="https://www.ihg.com/hotels/cn/zh/reservation",
        readiness=DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT,
        required_text_markers=("洲际酒店集团", "酒店"),
        property_identity_strategy="IHG_OFFICIAL_HOTEL_CODE",
        notes="Official IHG directory/destination entrypoint. Individual hotel code is authoritative identity.",
    ),
    ChainCode.H_WORLD: OfficialSourceContract(
        chain=ChainCode.H_WORLD,
        directory_url="https://www.hworld.com/",
        readiness=DirectoryReadiness.FULL_DIRECTORY_NOT_YET_VERIFIED,
        required_text_markers=("华住旗下", "酒店"),
        property_identity_strategy="HWORLD_OFFICIAL_HOTEL_ID_REQUIRED",
        notes="Official group homepage is verified but is not itself proven to expose all 13k+ properties. Production enumeration remains HOLD until the official booking/app directory contract is captured.",
    ),
    ChainCode.ATOUR: OfficialSourceContract(
        chain=ChainCode.ATOUR,
        directory_url="https://www.atour.com/",
        readiness=DirectoryReadiness.FULL_DIRECTORY_NOT_YET_VERIFIED,
        required_text_markers=(),
        property_identity_strategy="ATOUR_OFFICIAL_HOTEL_ID_REQUIRED",
        notes="Do not substitute third-party Atour listing sites. Production enumeration remains HOLD until an atour.com official inventory endpoint/page is captured and frozen.",
    ),
}


def contract_for(chain: ChainCode) -> OfficialSourceContract:
    try:
        return CONTRACTS[chain]
    except KeyError as exc:
        raise ValueError("CHAIN_OFFICIAL_SOURCE_CONTRACT_MISSING") from exc


def assert_directory_production_ready(chain: ChainCode) -> OfficialSourceContract:
    contract = contract_for(chain)
    if contract.readiness == DirectoryReadiness.FULL_DIRECTORY_NOT_YET_VERIFIED:
        raise ValueError(f"CHAIN_FULL_DIRECTORY_CONTRACT_HOLD:{chain.value}")
    return contract


def validate_contract_document(chain: ChainCode, *, final_url: str, text: str) -> None:
    contract = assert_directory_production_ready(chain)
    if not final_url.startswith("https://"):
        raise ValueError("CHAIN_CONTRACT_HTTPS_REQUIRED")
    missing = [marker for marker in contract.required_text_markers if marker not in text]
    if missing:
        raise ValueError(f"CHAIN_CONTRACT_MARKER_MISSING:{chain.value}:{','.join(missing)}")
