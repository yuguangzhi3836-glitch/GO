"""Real quote visibility does not establish same-product equivalence."""
import pytest
from test_member_comparison_quote_validity import SEARCH, NOW, USER_ID, verified_quote
from go_hotel.services.consumer_ota_comparison import consumer_ota_comparison_service as comparison


def quote(provider='CTRIP', amount=88000):
    return verified_quote() | {'provider': provider, 'total_amount_minor': amount,
        'product_terms': {'canonical_room_type_id': 'go-room-1', 'room_mapping_source': 'GO_CANONICAL_VERIFIED',
            'payment_timing': 'PREPAY', 'confirmation_mode': 'INSTANT_CONFIRMED', 'included_benefits': [],
            'provider_room_id': provider+'-room', 'provider_rate_plan_id': provider+'-rate',
            'meal': {'code': 'BREAKFAST', 'breakfast_per_room': 2},
            'cancellation': {'policy_complete': True, 'policy_type': 'FREE_UNTIL',
                'free_until': '2026-09-30T18:00:00+08:00',
                'penalty_after': {'type': 'FULL_STAY', 'value': 1}}}}


def results(*quotes):
    return comparison.options(USER_ID, SEARCH, list(quotes), NOW)


def item(response, provider='CTRIP'):
    return next(x for x in response['providers'] if x['provider'] == provider)


def test_unknown_terms_preserve_verified_price_but_never_rank():
    r = item(results(verified_quote(), quote('MEITUAN')))
    assert r['verified_member_price']['total_amount_minor'] == 88000
    assert r['member_price_status'] == 'VERIFIED_PERSONAL_MEMBER_PRICE'
    assert r['eligible_for_price_comparison'] is False
    assert r['product_comparability']['state'] == 'UNKNOWN'
    assert r['price_rank_within_group'] is None
    assert r['savings_against_group_highest_minor'] is None


def test_canonical_mapping_allows_distinct_provider_ids_to_share_group():
    response = results(quote(), quote('MEITUAN', 99000))
    assert len(response['comparison_groups']) == 1
    assert item(response)['price_rank_within_group'] == 1
    assert item(response)['savings_against_group_highest_minor'] == 11000
    assert item(response, 'MEITUAN')['price_rank_within_group'] == 2


@pytest.mark.parametrize('change', ['room', 'meal', 'deadline', 'penalty', 'nonrefundable', 'payment', 'confirmation', 'benefit'])
def test_different_product_terms_never_rank_against_each_other(change):
    second = quote('MEITUAN', 99000)
    terms = second['product_terms']
    if change == 'payment': terms['payment_timing'] = 'PAY_AT_PROPERTY'
    if change == 'confirmation': terms['confirmation_mode'] = 'ON_REQUEST'
    if change == 'benefit': terms['included_benefits'] = ['AIRPORT_TRANSFER']
    if change == 'room': terms['canonical_room_type_id'] = 'go-room-2'
    if change == 'meal': terms['meal']['breakfast_per_room'] = 1
    if change == 'deadline': terms['cancellation']['free_until'] = '2026-09-30T19:00:00+08:00'
    if change == 'penalty': terms['cancellation']['penalty_after'] = {'type': 'PERCENT', 'value': 50}
    if change == 'nonrefundable': terms['cancellation'] = {'policy_complete': True, 'policy_type': 'NON_REFUNDABLE'}
    response = results(quote(), second)
    assert len(response['comparison_groups']) == (1 if change == 'benefit' else 2)
    assert all(x['price_rank_within_group'] is None for x in response['providers'])
    assert all(x['savings_against_group_highest_minor'] is None for x in response['providers'])


@pytest.mark.parametrize('change', ['missingroom', 'opaqueroom', 'missingrate', 'unknownmeal', 'localtime', 'unknownpolicy', 'extra_condition', 'incomplete', 'malformedmeal', 'malformedpenalty'])
def test_incomplete_or_unsupported_terms_are_visible_not_comparable(change):
    q = quote()
    t = q['product_terms']
    if change == 'malformedmeal': t['meal']['code'] = []
    if change == 'malformedpenalty': t['cancellation']['penalty_after']['type'] = []
    if change == 'missingroom': t.pop('canonical_room_type_id')
    if change == 'opaqueroom': t['room_mapping_source'] = 'PROVIDER_ROOM_ID'
    if change == 'missingrate': t['provider_rate_plan_id'] = ''
    if change == 'unknownmeal': t['meal'] = {}
    if change == 'localtime': t['cancellation']['free_until'] = '2026-09-30T18:00:00'
    if change == 'unknownpolicy': t['cancellation'] = {'policy_complete': True, 'policy_type': '30_MINUTES'}
    if change == 'extra_condition': t['included_transfer'] = True
    if change == 'incomplete': t['cancellation']['policy_complete'] = False
    r = item(results(q))
    assert r['verified_member_price'] is not None
    assert not r['eligible_for_price_comparison']


def test_equivalent_deadline_offsets_share_group():
    second = quote('MEITUAN')
    second['product_terms']['cancellation']['free_until'] = '2026-09-30T10:00:00Z'
    assert len(results(quote(), second)['comparison_groups']) == 1


def test_other_users_quote_cannot_enter_comparison_or_expose_terms():
    q = quote('MEITUAN') | {'verified_for_user_id': 'other-user'}
    r = item(results(quote(), q), 'MEITUAN')
    assert r['verified_member_price'] is None
    assert r['product_comparability']['terms'] is None
    assert not r['eligible_for_price_comparison']


def test_multiple_same_provider_variants_are_not_silently_discarded():
    with pytest.raises(ValueError, match='MULTIPLE_PROVIDER_QUOTE_VARIANTS_REQUIRE_EXPLICIT_SELECTION'):
        results(quote(), quote(amount=77000))


@pytest.mark.parametrize('meal', ['HALF_BOARD', 'FULL_BOARD', 'ALL_INCLUSIVE'])
def test_richer_meals_need_full_coverage_contract_before_equivalence(meal):
    q = quote()
    q['product_terms']['meal']['code'] = meal
    assert not item(results(q))['eligible_for_price_comparison']
