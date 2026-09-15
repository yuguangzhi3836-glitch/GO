import pytest
from go_hotel.connectors.siteminder.config import SiteMinderConfig

def test_siteminder_requires_contracted_config(monkeypatch):
    for k in ["SITEMINDER_BASE_URL","SITEMINDER_BEARER_TOKEN","SITEMINDER_SEARCH_PATH","SITEMINDER_PREBOOK_PATH","SITEMINDER_BOOK_PATH","SITEMINDER_STATUS_PATH","SITEMINDER_CANCEL_PATH","SITEMINDER_OFFER_MAPPING_JSON","SITEMINDER_BOOKING_MAPPING_JSON","SITEMINDER_PREBOOK_MAPPING_JSON"]:
        monkeypatch.delenv(k,raising=False)
    with pytest.raises(RuntimeError): SiteMinderConfig.from_env()
