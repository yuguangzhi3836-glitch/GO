from pathlib import Path
p=Path('scripts/staging_aoluguya_hosted_direct_bootstrap.py').read_text(encoding='utf-8')
for x in [
    "REFUSED_NON_STAGING_ENV",
    "REFUSED_EXISTING_NON_BOOTSTRAP_HOTEL",
    "REFUSED_UNEXPECTED_BOOTSTRAP_GRAPH",
    "REFUSED_UNLABELLED_BOOTSTRAP_OFFERS",
    "PUBLISHED_REQUEST_ONLY",
    "STAGING_TEST_QUOTE_NOT_OFFICIAL",
    "payment_available':False",
    "REFUSED_ROLLBACK_RESERVATIONS_EXIST",
    "o.state='ACTIVE'",
]:
    assert x in p,x
assert 'stamp' not in p.lower()
print('R8.2_AOLUGUYA_STAGING_BOOTSTRAP_GATE: PASS')
