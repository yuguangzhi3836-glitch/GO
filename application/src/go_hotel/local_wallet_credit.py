"""Explicit, auditable wallet funding for local development only.

Run inside the local API container with:
    python -m go_hotel.local_wallet_credit --user-id <consumer-id> \
        --amount-cny 200.00 --reference hotel-flow-1
"""
from __future__ import annotations

import argparse
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.models import ConsumerWalletLedgerRow, ConsumerWalletRow
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import new_id, now_utc


def credit(user_id: str, amount_text: str, reference: str) -> tuple[int, bool]:
    if settings.app_env.strip().lower() not in {"local", "test", "demo"}:
        raise SystemExit("Refusing wallet credit: APP_ENV must be local, test, or demo.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        raise SystemExit("Invalid consumer user ID.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", reference):
        raise SystemExit("Reference must contain 1-64 letters, numbers, '-' or '_'.")
    try:
        amount = Decimal(amount_text)
    except InvalidOperation as exc:
        raise SystemExit("Amount must be a positive CNY value with at most two decimals.") from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise SystemExit("Amount must be a positive CNY value with at most two decimals.")
    amount_minor = int(amount * 100)
    if amount_minor > 5_000_000:
        raise SystemExit("Local credit is capped at CNY 50,000 per operation.")

    key = f"local-development-credit:{user_id}:{reference}"
    with SessionLocal.begin() as session:
        prior = session.scalar(select(ConsumerWalletLedgerRow).where(
            ConsumerWalletLedgerRow.idempotency_key == key))
        if prior:
            if (prior.user_id != user_id or prior.amount_minor != amount_minor
                    or prior.entry_type != "LOCAL_DEVELOPMENT_CREDIT"):
                raise SystemExit("Reference was already used for a different wallet credit.")
            return prior.balance_after_minor, True

        wallet = session.scalar(select(ConsumerWalletRow).where(
            ConsumerWalletRow.user_id == user_id).with_for_update())
        if not wallet or wallet.status != "ACTIVE":
            raise SystemExit("Active consumer wallet not found for this user ID.")
        wallet.cash_balance_minor += amount_minor
        wallet.updated_at = now_utc()
        session.add(ConsumerWalletLedgerRow(
            wallet_ledger_id=new_id("wle"), wallet_id=wallet.wallet_id,
            user_id=user_id, order_id=None, entry_type="LOCAL_DEVELOPMENT_CREDIT",
            amount_minor=amount_minor, balance_after_minor=wallet.cash_balance_minor,
            currency="CNY", idempotency_key=key, created_at=now_utc()))
        return wallet.cash_balance_minor, False


def main() -> None:
    parser = argparse.ArgumentParser(description="Credit test cash to a local GO consumer wallet.")
    parser.add_argument("--user-id", required=True, help="Consumer ID returned by /v1/consumer/me")
    parser.add_argument("--amount-cny", required=True, help="Positive amount, up to CNY 50,000")
    parser.add_argument("--reference", required=True, help="Unique local test reference for idempotency")
    args = parser.parse_args()
    balance, replay = credit(args.user_id, args.amount_cny, args.reference)
    verb = "already applied" if replay else "credited"
    print(f"{verb}; wallet cash balance is CNY {balance / 100:.2f} (local development only).")


if __name__ == "__main__":
    main()
