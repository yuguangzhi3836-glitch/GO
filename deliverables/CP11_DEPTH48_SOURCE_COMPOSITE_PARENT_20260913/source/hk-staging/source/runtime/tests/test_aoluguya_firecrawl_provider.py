import httpx
import pytest
from go_hotel.services import regional_hotel_build as m
pytestmark=pytest.mark.no_db

def test_firecrawl_requires_secret(monkeypatch):
    monkeypatch.delenv("GO_FIRECRAWL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="FIRECRAWL_API_KEY_REQUIRED"):
        m._firecrawl_search_items({"key":"firecrawl","type":"FIRECRAWL_SEARCH"}, country="CN", province="黑龙江省", city="哈尔滨市", target_name="敖麓谷雅")

def test_firecrawl_builds_single_target_candidate(monkeypatch):
    monkeypatch.setenv("GO_FIRECRAWL_API_KEY","test-secret")
    body={"success":True,"data":{"web":[{"url":"https://www.hyatt.com/example/aoluguya","description":"official"},{"url":"https://hotels.ctrip.com/example","description":"ota"}],"images":[{"imageUrl":"https://img.example/a.jpg"}]}}
    class DummyClient:
        def __init__(self,*a,**k): pass
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def post(self,*a,**k): return httpx.Response(200,json=body)
    monkeypatch.setattr(m.httpx,"Client",DummyClient)
    items=m._firecrawl_search_items({"key":"firecrawl","type":"FIRECRAWL_SEARCH","requested_tier":5}, country="CN", province="黑龙江省", city="哈尔滨市", target_name="敖麓谷雅")
    assert len(items)==1
    c=items[0]
    assert c["name"]=="敖麓谷雅"
    assert len(c["source_hints"])==2
    assert c["source_hints"][0]["kind"]=="GROUP_OFFICIAL"
    assert c["source_hints"][1]["kind"]=="OTA_DISCOVERY"
    assert c["source_hints"][0]["payload"]["media_candidates"][0]["source_url"].endswith("a.jpg")
