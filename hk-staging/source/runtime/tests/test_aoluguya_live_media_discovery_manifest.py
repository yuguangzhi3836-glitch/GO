from go_hotel.services.media_harvester import classify_scene

# Live external discovery labels observed from official Hyatt AOLUGUYA pages on 2026-09-04.
# This is a discovery-stage QA manifest, not a publication-rights assertion.
LIVE_LABELS = [
    ('AOLUGUYA Hotel Exterior Sunglow','EXTERIOR'),
    ('AOLUGUYA Exterior View','EXTERIOR'),
    ('AOLUGUYA Lobby Concierge Lounge','LOBBY'),
    ('AOLUGUYA Lobby Concierge Lounge Table','LOBBY'),
    ('AOLUGUYA Lobby Night View','LOBBY'),
    ('AOLUGUYA Executive Lounge Night View','LOBBY'),
    ('AOLUGUYA Lobby Bar','DINING'),
    ('AOLUGUYA All Day Dining Reception Desk','DINING'),
    ('AOLUGUYA All Day Dining Hot Dishes','DINING'),
    ('AOLUGUYA All Day Dining River View','DINING'),
    ('AOLUGUYA All Day Dining Private Dining Room','DINING'),
    ('AOLUGUYA Steak House River View','DINING'),
    ('AOLUGUYA Chinese Restaurant Lobby','DINING'),
    ('AOLUGUYA Chinese Restaurant Lobby Table','DINING'),
    ('AOLUGUYA Chinese Restaurant Private Dining Room','DINING'),
    ('AOLUGUYA Pool','WELLNESS'),
    ('AOLUGUYA Health Club','WELLNESS'),
    ('AOLUGUYA Maria Suo Suite Spa Area','WELLNESS'),
    ('AOLUGUYA Meeting Room','SIGNATURE_SPACE'),
    ('AOLUGUYA Function Room Vip Area','SIGNATURE_SPACE'),
    ('AOLUGUYA Banquet Hall Front View','SIGNATURE_SPACE'),
    ('AOLUGUYA Dreamweaver Room One Bed Window View','ROOM'),
    ('AOLUGUYA Dreamweaver Room One Bed','ROOM'),
    ('AOLUGUYA Dreamweaver Room Twin Bed Window View','ROOM'),
    ('AOLUGUYA Dreamweaver Room Twin Bed','ROOM'),
    ('AOLUGUYA Dreamweaver Room Twin Bed Bathroom','ROOM'),
    ('AOLUGUYA Cloudspire Haven Deluxe King Bed Living Room','ROOM'),
    ('AOLUGUYA Cloudspire Haven Deluxe King Bed','ROOM'),
    ('AOLUGUYA Cloudspire Haven Deluxe Twin Bed','ROOM'),
    ('AOLUGUYA Cloudspire Haven Deluxe Twin Bed Bathroom','ROOM'),
    ('AOLUGUYA Sunset Perch Deluxe Twin Bed','ROOM'),
    ('AOLUGUYA Sunset Perch Deluxe Twin Bed Bathroom','ROOM'),
    ('AOLUGUYA Stardust Suite Living Area','ROOM'),
    ('AOLUGUYA Stardust Suite Bed','ROOM'),
    ('AOLUGUYA Stardust Suite Bathroom','ROOM'),
    ('AOLUGUYA Luar Ebrace Suite Twin Bed Living Area','ROOM'),
    ('AOLUGUYA Luar Ebrace Suite Twin Bed','ROOM'),
    ('AOLUGUYA Luar Ebrace Suite Twin Bed Bathroom','ROOM'),
    ('AOLUGUYA Maria Suo Suite Living Area','ROOM'),
    ('AOLUGUYA Maria Suo Suite Dining Area','ROOM'),
    ('AOLUGUYA Maria Suo Suite Bed','ROOM'),
]

def test_live_discovery_manifest_has_30_plus_unique_candidates_and_six_scenes():
    labels=[x[0] for x in LIVE_LABELS]
    assert len(labels) >= 30
    assert len(set(labels)) == len(labels)
    scenes={classify_scene(title=label) for label,_ in LIVE_LABELS}
    assert {'EXTERIOR','LOBBY','ROOM','DINING','WELLNESS','SIGNATURE_SPACE'} <= scenes


def test_live_labels_classify_as_expected():
    mismatches=[]
    for label,expected in LIVE_LABELS:
        got=classify_scene(title=label)
        if got != expected:
            mismatches.append((label,expected,got))
    assert mismatches == []
