from __future__ import annotations
from dataclasses import dataclass
import json, os
from go_hotel.connectors.mapping import CanonicalOfferMapping, BookingMapping, PrebookMapping

@dataclass(frozen=True)
class SiteMinderEndpointConfig:
    search_path: str
    prebook_path: str
    book_path: str
    status_path: str
    cancel_path: str

@dataclass(frozen=True)
class SiteMinderConfig:
    base_url: str
    bearer_token: str
    endpoints: SiteMinderEndpointConfig
    offer_mapping: CanonicalOfferMapping
    booking_mapping: BookingMapping
    prebook_mapping: PrebookMapping
    timeout_seconds: float = 4.0

    @classmethod
    def from_env(cls) -> "SiteMinderConfig":
        """Load only explicit contracted configuration.

        Endpoint paths and response field mappings are intentionally environment supplied;
        GO must populate them from the current SiteMinder partner/sandbox specification.
        """
        required = [
            "SITEMINDER_BASE_URL","SITEMINDER_BEARER_TOKEN","SITEMINDER_SEARCH_PATH",
            "SITEMINDER_PREBOOK_PATH","SITEMINDER_BOOK_PATH","SITEMINDER_STATUS_PATH",
            "SITEMINDER_CANCEL_PATH","SITEMINDER_OFFER_MAPPING_JSON",
            "SITEMINDER_BOOKING_MAPPING_JSON","SITEMINDER_PREBOOK_MAPPING_JSON",
        ]
        missing=[k for k in required if not os.getenv(k)]
        if missing:
            raise RuntimeError("Missing SiteMinder sandbox configuration: " + ", ".join(missing))
        return cls(
            base_url=os.environ["SITEMINDER_BASE_URL"], bearer_token=os.environ["SITEMINDER_BEARER_TOKEN"],
            endpoints=SiteMinderEndpointConfig(
                search_path=os.environ["SITEMINDER_SEARCH_PATH"], prebook_path=os.environ["SITEMINDER_PREBOOK_PATH"],
                book_path=os.environ["SITEMINDER_BOOK_PATH"], status_path=os.environ["SITEMINDER_STATUS_PATH"],
                cancel_path=os.environ["SITEMINDER_CANCEL_PATH"],
            ),
            offer_mapping=CanonicalOfferMapping(**json.loads(os.environ["SITEMINDER_OFFER_MAPPING_JSON"])),
            booking_mapping=BookingMapping(**json.loads(os.environ["SITEMINDER_BOOKING_MAPPING_JSON"])),
            prebook_mapping=PrebookMapping(**json.loads(os.environ["SITEMINDER_PREBOOK_MAPPING_JSON"])),
            timeout_seconds=float(os.getenv("SITEMINDER_TIMEOUT_SECONDS","4")),
        )
