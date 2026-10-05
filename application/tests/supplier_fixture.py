"""Explicit admitted trading fixture; never autouse and never used by registration tests."""
from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.db.models import SupplierOnboardingRow
from go_hotel.db.session import SessionLocal


def admit_trading_supplier(supplier_id, owner_user_id):
    with SessionLocal.begin() as session:
        if session.scalar(select(SupplierOnboardingRow).where(
                SupplierOnboardingRow.supplier_id == supplier_id)):
            return
        now = datetime.now(timezone.utc)
        session.add(SupplierOnboardingRow(onboarding_id='fixture-' + supplier_id,
            supplier_id=supplier_id, owner_user_id=owner_user_id, state='CONTRACT_ACTIVE',
            profile_json={}, contract_json={}, created_at=now, updated_at=now))
