from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone

UTC = timezone.utc


def now():
    return datetime.now(UTC)


def parse_args():
    parser = argparse.ArgumentParser(description="Create or reset a GO Staging admin without storing credentials in source or shell history.")
    parser.add_argument("--username", required=True, help="Admin username/email. Do not put passwords on the command line.")
    parser.add_argument("--reset-mfa", action="store_true", help="Explicitly clear existing MFA binding so the next login must enroll again.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Lazy imports keep --help usable even outside the full deployment runtime.
    from sqlalchemy import select
    from go_hotel.core.config import settings
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import IdentityUserRow, AuthSessionRow, RefreshTokenRow
    from go_hotel.security.crypto import hash_password
    from go_hotel.security.service import uid

    if settings.app_env.lower() != "staging":
        print(f"REFUSED: APP_ENV must be staging, got {settings.app_env!r}", file=sys.stderr)
        return 2

    pw1 = getpass.getpass("One-time initial password: ")
    pw2 = getpass.getpass("Confirm one-time initial password: ")
    if not pw1 or pw1 != pw2:
        print("REFUSED: passwords are empty or do not match", file=sys.stderr)
        return 2
    if len(pw1) < 12:
        print("REFUSED: password must be at least 12 characters", file=sys.stderr)
        return 2

    with SessionLocal() as s:
        row = s.scalar(select(IdentityUserRow).where(IdentityUserRow.username == args.username))
        created = row is None
        if row is None:
            t = now()
            row = IdentityUserRow(
                user_id=uid("usr"),
                username=args.username,
                password_hash=hash_password(pw1),
                actor_type="GO_ADMIN",
                supplier_id=None,
                roles=["GO_GOVERNANCE"],
                status="ACTIVE",
                token_version=1,
                created_at=t,
                updated_at=t,
            )
            s.add(row)
            s.flush()
        else:
            if row.actor_type != "GO_ADMIN":
                print("REFUSED: existing username belongs to a non-admin actor", file=sys.stderr)
                return 3
            row.password_hash = hash_password(pw1)
            row.status = "ACTIVE"
            row.updated_at = now()
            row.token_version = int(row.token_version or 0) + 1
            if args.reset_mfa:
                row.mfa_secret_ciphertext = None
                row.mfa_enabled_at = None

            sessions = s.scalars(select(AuthSessionRow).where(AuthSessionRow.user_id == row.user_id)).all()
            for ses in sessions:
                if ses.status == "ACTIVE":
                    ses.status = "REVOKED"
                    ses.revoked_at = now()
            refreshes = s.scalars(select(RefreshTokenRow).where(RefreshTokenRow.user_id == row.user_id)).all()
            for rt in refreshes:
                if rt.status == "ACTIVE":
                    rt.status = "REVOKED"
                    rt.revoked_at = now()

        s.commit()

    action = "CREATED" if created else "RESET"
    mfa_state = "MFA_RESET_FOR_REENROLLMENT" if args.reset_mfa else "MFA_PRESERVED_OR_UNBOUND"
    print(f"STAGING_ADMIN_ACCOUNT_{action}: PASS")
    print(f"username={args.username}")
    print(f"mfa_state={mfa_state}")
    print("password_output=NEVER_PRINTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
