import json

from go_hotel.services import regional_hotel_build as m


def test_osm_bootstrap_provider_summary(monkeypatch):
    monkeypatch.setenv("GO_HOTEL_REGION_DISCOVERY_PROVIDERS_JSON", "")
    monkeypatch.setenv("GO_HOTEL_REGION_DISCOVERY_BOOTSTRAP_OSM", "true")
    s=m._provider_summary()
    assert s["configured"] is True
    assert s["harbin_bootstrap_ready"] is True
    assert s["national_ready"] is False
    assert s["bootstrap_provider_count"] == 1


def test_osm_overpass_parse_is_public_fact_only(monkeypatch):
    body=json.dumps({"elements":[{
        "type":"node","id":123,"lat":45.80,"lon":126.53,
        "tags":{
            "tourism":"hotel","name":"测试酒店","name:en":"Test Hotel",
            "addr:city":"哈尔滨市","addr:district":"松北区","addr:street":"测试路","addr:housenumber":"1号",
            "stars":"4","rooms":"88","website":"https://hotel.example"
        }
    }]}, ensure_ascii=False)
    monkeypatch.setattr(m.discovery,"_fetch_html",lambda *a,**k:("https://overpass-api.de/api/interpreter",body,len(body.encode()),{}))
    items=m._osm_overpass_items({"key":"osm","endpoint":"https://overpass-api.de/api/interpreter"},city="哈尔滨市")
    assert len(items)==1
    x=items[0]
    assert x["external_hotel_id"]=="osm:node/123"
    assert x["rights_status"]=="PUBLIC_BUSINESS_FACT"
    assert x["source_hints"][0]["kind"]=="MAP_DIRECTORY"
    assert x["source_hints"][0]["payload"]["rooms"]=="88"
    assert "哈尔滨市" in x["address"]


def test_osm_bootstrap_rejects_non_harbin(monkeypatch):
    monkeypatch.setattr(m.discovery,"_fetch_html",lambda *a,**k:(_ for _ in ()).throw(AssertionError("network should not be reached")))
    try:
        m._osm_overpass_items({"key":"osm","endpoint":"https://overpass-api.de/api/interpreter"},city="北京市")
    except ValueError as exc:
        assert str(exc)=="OSM_BOOTSTRAP_CITY_NOT_ALLOWED"
    else:
        raise AssertionError("expected fail closed")
