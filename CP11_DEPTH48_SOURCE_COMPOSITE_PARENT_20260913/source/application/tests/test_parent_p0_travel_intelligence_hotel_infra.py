from go_hotel.services.hotel_infrastructure_p0 import admission
from go_hotel.services import regional_hotel_build as rb


def test_tier5_admission_five_star_or_five_diamond_only():
    a=admission({'rating_class':'五钻'}); assert a['build_tier']==5 and a['official_star_truth'] is False
    b=admission({'stars':'5'}); assert b['build_tier']==5
    c=admission({'hotel_class':'luxury'}); assert c['build_tier']==0
    d=admission({'rating_class':'四钻'}); assert d['build_tier']==4


def test_regional_star_tier_uses_evidence_rule():
    assert rb._star_tier({'category':'五星级'})==5
    assert rb._star_tier({'category':'五钻'})==5
    assert rb._star_tier({'segment':'luxury'})==0


def test_national_tier_sequence_starts_5_then_4():
    assert rb.NATIONAL_TIER_SEQUENCE[:2]==[5,4]
