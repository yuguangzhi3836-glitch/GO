"""A newer projection is not authority to reassign an order's supplier."""
import pytest

from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc


def fact(supplier='supplier-a', at='2026-09-25T10:00:00Z', account='owner'):
    return dict(account_id=account, supplier_id=supplier, vertical='HOTEL',
                order_id='immutable-order', title='Owned hotel order',
                lifecycle_state='CONFIRMED', payment_state='PAID',
                refund_state='NOT_REQUESTED', evidence_reference='hotel://original',
                source_updated_at=at, facts={'confirmation': 'original'})


@pytest.mark.parametrize('supplier', ['supplier-b', None, ''])
@pytest.mark.parametrize('at', ['2026-09-25T09:00:00Z', '2026-09-25T11:00:00Z'])
def test_supplier_replacement_or_erasure_rejected_without_mutation(supplier, at):
    original = svc.project(fact())
    before = svc.detail('owner', original['consumer_unified_lifecycle_id'])
    changed = fact(supplier, at)
    changed.update(lifecycle_state='CANCELLED', refund_state='REFUND_COMPLETED',
                   evidence_reference='hotel://wrong-supplier', facts={'confirmation': 'wrong'})
    with pytest.raises(ValueError, match='UNIFIED_LIFECYCLE_SUPPLIER_IMMUTABLE'):
        svc.project(changed)
    detail = svc.detail('owner', original['consumer_unified_lifecycle_id'])
    assert detail == before
    assert len(detail['events']) == 1


def test_unknown_supplier_cannot_be_bound_by_ordinary_projection():
    original = svc.project(fact(None))
    with pytest.raises(ValueError, match='UNIFIED_LIFECYCLE_SUPPLIER_IMMUTABLE'):
        svc.project(fact('supplier-b', '2026-09-25T11:00:00Z'))
    assert svc.detail('owner', original['consumer_unified_lifecycle_id'])['item']['supplier_id'] is None


@pytest.mark.parametrize('supplier', ['supplier-a', None])
def test_same_supplier_updates_and_stale_replays_remain_supported(supplier):
    original = svc.project(fact(supplier))
    changed = fact(supplier, '2026-09-25T11:00:00Z')
    changed.update(lifecycle_state='IN_PROGRESS', evidence_reference='hotel://next')
    updated = svc.project(changed)
    assert updated['lifecycle_state'] == 'IN_PROGRESS'
    assert updated['supplier_id'] == supplier
    assert svc.project(fact(supplier))['stale_ignored'] is True
    assert len(svc.detail('owner', original['consumer_unified_lifecycle_id'])['events']) == 2


def test_cross_account_cannot_reassign_supplier_or_obtain_detail():
    original = svc.project(fact())
    with pytest.raises(ValueError, match='UNIFIED_LIFECYCLE_ACCOUNT_IMMUTABLE'):
        svc.project(fact('supplier-b', '2026-09-25T11:00:00Z', account='other-owner'))
    with pytest.raises(ValueError, match='UNIFIED_LIFECYCLE_NOT_FOUND'):
        svc.detail('other-owner', original['consumer_unified_lifecycle_id'])


def test_idempotent_shortcut_cannot_hide_supplier_mismatch():
    from go_hotel.db.session import SessionLocal
    svc.project(fact())
    with SessionLocal() as session:
        with pytest.raises(ValueError, match='UNIFIED_LIFECYCLE_SUPPLIER_IMMUTABLE'):
            svc.project_in_session(session, fact('supplier-b'), idempotent_if_exists=True)
