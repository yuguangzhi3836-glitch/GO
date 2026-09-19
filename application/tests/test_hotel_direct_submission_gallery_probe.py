"""Small synthetic gallery probe; timings are observations, not a capacity gate."""
import base64
import copy
import io
import json
import time
import pytest
from PIL import Image
from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup


@pytest.mark.parametrize("asset_count,textured", [(20, False), (100, True)])
def test_original_gallery_read_amplification(publishing, monkeypatch, asset_count, textured):
    pub, review, pid, original, factory, verifier, old = publishing
    manifest = copy.deepcopy(original)
    rights = {k:v for k,v in manifest['assets'][0]['rights'].items() if k != 'review_evidence_reference'}
    for index in range(asset_count - 2):
        image = io.BytesIO()
        picture = Image.effect_noise((1600,900), 70).convert('RGB') if textured else Image.new('RGB', (1600,900), (index*13,100,80))
        picture.save(image, format='JPEG', quality=85)
        picture.close()
        record = verifier.media.upload('one','owner',pid,{'content_base64':base64.b64encode(image.getvalue()).decode(),'role':'GALLERY','room_type_id':None,'rights':rights})
        verifier.media.cache.decide_rights(record['asset_id'],rights_state='HOTEL_SUBMITTED',actor='reviewer',rights_owner='Hotel',evidence_reference='review',rights_scope='DISTRIBUTE_ON_GO',expires_at=None)
        asset = copy.deepcopy(manifest['assets'][0])
        asset.update(asset_id=record['asset_id'],role='GALLERY',original_sha256=record['sha256'],byte_size=record['byte_size'])
        manifest['assets'].append(asset)
    row = review.submit('one','owner',pid,manifest)
    review.approve(row['review_id'],'admin',row['manifest_sha256'])
    started = time.perf_counter()
    pub.publish(row['review_id'],'one',pid,'admin')
    publish_ms = (time.perf_counter()-started)*1000
    reads = []
    original_reader = verifier.media._read_bytes
    def traced(record):
        reads.append(record['asset_id'])
        return original_reader(record)
    monkeypatch.setattr(verifier.media,'_read_bytes',traced)
    samples = []
    for kind in ['page','image','inspection']:
        for repetition in range(3):
            reads.clear(); started = time.perf_counter()
            if kind == 'page':
                result = hotel_autopage_factory_service.public_page('test')
                assert len(result['media']['gallery']) == asset_count - 2
            elif kind == 'image':
                raw, mime = pub.public_content(row['review_id'],manifest['assets'][0]['asset_id'])
                assert raw.startswith(b'\xff\xd8') and mime == 'image/jpeg'
            else:
                result = review.inspection(row['review_id'])
                assert result['publication']['publicly_available']
                assert result['facts_sha256'] and len(result['assets']) == asset_count
            samples.append({'operation':kind,'milliseconds':round((time.perf_counter()-started)*1000,3),'original_reads':len(reads),'distinct_assets_read':len(set(reads))})
    print('GALLERY_PROBE='+json.dumps({'synthetic_assets':asset_count,'total_original_bytes':sum(a['byte_size'] for a in manifest['assets']),'dimensions':[1600,900],'image_pattern':'98 noise-textured JPEGs plus two fixture originals' if textured else 'solid-color JPEG; not representative hotel filesize','publish_ms':round(publish_ms,3),'samples':samples},sort_keys=True))
    review.revoke(row['review_id'],'admin')
    import pytest
    with pytest.raises(ValueError):
        pub.public_content(row['review_id'],manifest['assets'][0]['asset_id'])
