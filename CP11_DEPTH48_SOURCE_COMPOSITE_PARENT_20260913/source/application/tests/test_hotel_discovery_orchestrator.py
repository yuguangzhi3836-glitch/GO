from pathlib import Path
import pytest

pytestmark=pytest.mark.no_db


def test_discovery_slice1_contract_is_present_and_bounded():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/hotel_discovery_orchestrator.py').read_text(encoding='utf-8')
    routes=(root/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text(encoding='utf-8')
    for symbol in [
        'HotelDiscoveryOrchestratorService','def register_seed','def run_job','def retry_job','def run_batch',
        'def job_status','def job_snapshots','DISCOVERY_SOURCE_MAP','DEFAULT_RIGHTS','DISCOVERY_SOURCE_SNAPSHOTTED',
    ]:
        assert symbol in service
    for route in [
        "/internal/v1/hotel-discovery/seeds",
        "/internal/v1/hotel-discovery/jobs/{job_id}/run",
        "/internal/v1/hotel-discovery/jobs/{job_id}/retry",
        "/internal/v1/hotel-discovery/jobs/{job_id}/snapshots",
        "/internal/v1/hotel-discovery/batches/run",
    ]:
        assert route in routes
    assert 'media_candidates' in service
    assert 'RIGHTS_UNKNOWN' in service
    assert 'media_harvester_service.harvest' not in service
    assert 'payment' not in service.lower()


def test_discovery_parser_prefers_structured_facts_and_does_not_copy_body_prose():
    from go_hotel.services.hotel_discovery_orchestrator import _extract_payload
    html='''<html><head><title>Example Hotel</title><meta property="og:image" content="/hero.jpg"></head>
    <body><script type="application/ld+json">{
      "@context":"https://schema.org","@type":"Hotel","name":"Example Hotel",
      "address":{"@type":"PostalAddress","streetAddress":"1 Main St","addressLocality":"Harbin","addressCountry":"CN"},
      "telephone":"+86 451 12345678","email":"book@example.test",
      "geo":{"@type":"GeoCoordinates","latitude":45.8,"longitude":126.5},
      "checkinTime":"14:00","checkoutTime":"12:00","image":["/room.jpg"]
    }</script><p>This copyrighted marketing paragraph must not become the description.</p></body></html>'''
    p=_extract_payload(html,'https://hotel.example/rooms',{'name':'Seed Hotel'})
    assert p['name']=='Example Hotel'
    assert p['address']['city']=='Harbin'
    assert p['latitude']==45.8 and p['longitude']==126.5
    assert any(x['channel']=='EMAIL' for x in p['contacts'])
    assert any(x['source_url']=='https://hotel.example/hero.jpg' for x in p['media_candidates'])
    assert 'description' not in p
