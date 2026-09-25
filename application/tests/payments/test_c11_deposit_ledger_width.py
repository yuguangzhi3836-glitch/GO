"""Exercise the real account-code column limit absent from ordinary SQLite VARCHAR."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from go_hotel.db.models import OmnichannelLedgerEntryRow as Ledger
from go_hotel.db.session import SessionLocal, engine
from go_hotel.services.unified_money_movement import business_ledger_account_code
from go_hotel.services import rental_deposit_money as service
from tests.payments.test_c11_rental_deposit_money import obligation, args, decide, settle, OWNER, CHECKER


@pytest.fixture
def enforced_account_width():
    # PostgreSQL enforces VARCHAR itself. SQLite needs an equivalent DB trigger,
    # not a Python assertion that would let an oversized INSERT pass unnoticed.
    if engine.dialect.name == 'sqlite':
        with engine.begin() as connection:
            for action in ('INSERT', 'UPDATE'):
                connection.execute(text(f'''CREATE TRIGGER ledger_account_width_{action}
                    BEFORE {action} ON omnichannel_ledger_entry
                    WHEN length(NEW.account_code) > 64
                    BEGIN SELECT RAISE(ABORT, 'account_code exceeds VARCHAR(64)'); END'''))
    yield
    if engine.dialect.name == 'sqlite':
        with engine.begin() as connection:
            for action in ('INSERT', 'UPDATE'):
                connection.execute(text(f'DROP TRIGGER IF EXISTS ledger_account_width_{action}'))


def test_deposit_capture_release_passes_database_column_constraint(obligation, enforced_account_width):
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    result = settle(obligation, decision)
    assert result['state'] == 'SETTLED' and result['captured_minor'] == 4000
    assert result['released_minor'] == 196000
    with SessionLocal() as session:
        entries = list(session.scalars(select(Ledger)))
        credit = next(entry for entry in entries if entry.direction == 'CREDIT')
        assert credit.account_code == 'RD:' + obligation['obligation_id']
        assert len(credit.account_code) <= Ledger.__table__.c.account_code.type.length == 64
        assert credit.account_code[3:] == obligation['obligation_id']
        assert sum(entry.amount_minor for entry in entries if entry.direction == 'DEBIT') == 4000
        assert sum(entry.amount_minor for entry in entries if entry.direction == 'CREDIT') == 4000
    # Prove the test database actually rejects a too-long SQL write.
    with pytest.raises(DBAPIError) as rejected:
        with engine.begin() as connection:
            connection.execute(text('UPDATE omnichannel_ledger_entry SET account_code = :code'), {'code': 'x' * 65})
    assert '64' in str(rejected.value) or 'too long' in str(rejected.value)
    assert settle(obligation, decision) == result


def test_complete_identity_preserved_for_equal_long_prefixes_and_limit():
    first = 'rent_dep_' + 'a' * 39 + '1'
    second = 'rent_dep_' + 'a' * 39 + '2'
    assert business_ledger_account_code('RENTAL_DEPOSIT', first) != business_ledger_account_code('RENTAL_DEPOSIT', second)
    assert business_ledger_account_code('RENTAL_DEPOSIT', 'a' * 61) == 'RD:' + 'a' * 61
    with pytest.raises(ValueError, match='ACCOUNT_TOO_LONG'):
        business_ledger_account_code('RENTAL_DEPOSIT', 'a' * 62)
    assert business_ledger_account_code('RENTAL_ORDER', first) == 'BUSINESS:RENTAL_ORDER:' + first


def test_oversized_deposit_identity_fails_before_either_ledger_entry():
    from types import SimpleNamespace
    from go_hotel.services.unified_money_movement import unified_money_movement_service
    intent = SimpleNamespace(business_type='RENTAL_DEPOSIT', business_id='a' * 62, selected_channel='LOCAL_MARKET')
    movement = SimpleNamespace(money_movement_id='capture', movement_type='CAPTURE')
    with SessionLocal() as session:
        with pytest.raises(ValueError, match='ACCOUNT_TOO_LONG'):
            unified_money_movement_service._post(session, intent, movement)
        assert not session.new


@pytest.mark.parametrize('corrupt', [False, True])
def test_legacy_account_is_exact_read_only_compatibility(obligation, corrupt):
    if engine.dialect.name != 'sqlite':
        pytest.skip('Legacy oversized rows could only exist in SQLite; PostgreSQL rejected them')
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    result = settle(obligation, decision)
    legacy = 'BUSINESS:RENTAL_DEPOSIT:' + obligation['obligation_id']
    with SessionLocal.begin() as session:
        credit = session.scalar(select(Ledger).where(Ledger.direction == 'CREDIT'))
        credit.account_code = legacy[:-1] if corrupt else legacy
    if corrupt:
        assert service.status(OWNER, *args(obligation))['state'] == 'RECONCILIATION_REQUIRED'
        with pytest.raises(ValueError, match='LEDGER_INVALID'): settle(obligation, decision)
    else:
        assert service.status(OWNER, *args(obligation)) == result
        assert settle(obligation, decision) == result
        with SessionLocal() as session:
            assert session.scalar(select(Ledger.account_code).where(Ledger.direction == 'CREDIT')) == legacy
