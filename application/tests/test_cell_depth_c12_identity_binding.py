"""C12: external identities cannot auto-link by mutable username."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import event, func, select

from go_hotel.db.models import IdentityUserRow, AuthSessionRow, RefreshTokenRow
from go_hotel.db.session import SessionLocal, engine
from go_hotel.security.crypto import decode_jwt, encode_jwt, token_hash
from go_hotel.security.service import identity_service as svc


@pytest.mark.parametrize("actor,roles", [("GO_ADMIN", ["GO_GOVERNANCE"]),
                                         ("SUPPLIER_USER", ["SUPPLIER_OWNER"])])
def test_sso_username_collision_cannot_take_over_existing_password_account(actor, roles):
    uid = svc.create_user("local-owner", "local-password", actor, "supplier-a", roles)
    with pytest.raises(ValueError, match="SSO_ACCOUNT_LINK_REQUIRED"):
        svc.login_sso("corporate", "unrelated-external-subject", "local-owner")
    with SessionLocal() as session:
        user = session.get(IdentityUserRow, uid)
        assert user.sso_provider is None and user.sso_subject is None
        assert user.roles == roles
        assert session.scalar(select(func.count()).select_from(AuthSessionRow).where(AuthSessionRow.user_id == uid)) == 0
    assert svc.authenticate(svc.login("local-owner", "local-password")["access_token"]).user_id == uid


def test_sso_username_collision_cannot_replace_existing_external_subject():
    first = svc.login_sso("corporate", "subject-one", "linked-user")
    uid = svc.authenticate(first["access_token"]).user_id
    with pytest.raises(ValueError, match="SSO_ACCOUNT_LINK_REQUIRED"):
        svc.login_sso("corporate", "subject-two", "linked-user")
    with SessionLocal() as session:
        assert session.get(IdentityUserRow, uid).sso_subject == "subject-one"
    second = svc.login_sso("corporate", "subject-one", "renamed-upstream-display")
    assert svc.authenticate(second["access_token"]).user_id == uid


def test_bff_sso_callback_rejects_username_takeover_without_session_cookie(client, monkeypatch):
    from go_hotel.security.oidc import oidc_service

    # Stub an already verified provider response; no external identity service
    # is contacted or claimed as accepted by this isolated HTTP check.
    monkeypatch.setattr(oidc_service, "callback", lambda code, state: {
        "sub": "attacker-subject", "preferred_username": "go_admin"})
    response = client.get("/bff/auth/sso/callback?code=isolated&state=isolated", follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["detail"] == "SSO_ACCOUNT_LINK_REQUIRED"
    assert "set-cookie" not in response.headers
    with SessionLocal() as session:
        user = session.scalar(select(IdentityUserRow).where(IdentityUserRow.username == "go_admin"))
        assert user.sso_provider is None and user.sso_subject is None
        assert session.scalar(select(func.count()).select_from(AuthSessionRow).where(AuthSessionRow.user_id == user.user_id)) == 0


@pytest.mark.parametrize("provider,subject,username", [("", "subject", "name"),
    ("corporate", "", "name"), ("corporate", "subject", ""),
    (None, "subject", "name"), ("corporate", None, "name")])
def test_sso_rejects_incomplete_external_identity(provider, subject, username):
    with pytest.raises(ValueError, match="INVALID_SSO_IDENTITY"):
        svc.login_sso(provider, subject, username)


def test_access_token_session_must_belong_to_its_subject():
    admin = svc.login("go_admin", "change-me-admin")
    supplier = svc.login("supplier_owner", "change-me-supplier")
    claims = decode_jwt(admin["access_token"])
    claims["sid"] = decode_jwt(supplier["access_token"])["sid"]
    with pytest.raises(ValueError, match="SESSION_REVOKED"):
        svc.authenticate(encode_jwt(claims))


def test_refresh_token_session_must_belong_to_its_subject():
    admin = svc.login("go_admin", "change-me-admin")
    supplier = svc.login("supplier_owner", "change-me-supplier")
    supplier_sid = decode_jwt(supplier["access_token"])["sid"]
    with SessionLocal() as session:
        row = session.scalar(select(RefreshTokenRow).where(RefreshTokenRow.token_hash == token_hash(admin["refresh_token"])))
        row.session_id = supplier_sid
        session.commit()
    with pytest.raises(ValueError, match="SESSION_REVOKED"):
        svc.refresh(admin["refresh_token"])


def test_concurrent_refresh_consumes_once_and_leaves_one_usable_successor():
    tokens = svc.login("supplier_owner", "change-me-supplier")
    sid = decode_jwt(tokens["access_token"])["sid"]
    both_read = Barrier(2)

    def wait_for_both_reads(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT refresh_token.") and "token_hash =" in statement:
            both_read.wait(timeout=10)

    def rotate():
        try:
            return svc.refresh(tokens["refresh_token"])
        except ValueError as error:
            return str(error)

    event.listen(engine, "after_cursor_execute", wait_for_both_reads)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: rotate(), range(2)))
    finally:
        event.remove(engine, "after_cursor_execute", wait_for_both_reads)
    winners = [result for result in results if isinstance(result, dict)]
    successful_count = len(winners)
    assert successful_count == 1
    assert results.count("INVALID_REFRESH_TOKEN") == 1
    winner = winners[0]
    assert svc.authenticate(winner["access_token"]).session_id == sid
    assert svc.verify_csrf(sid, winner["csrf_token"])
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(RefreshTokenRow).where(
            RefreshTokenRow.session_id == sid, RefreshTokenRow.status == "ACTIVE")) == 1
    assert svc.refresh(winner["refresh_token"])["refresh_token"] != winner["refresh_token"]
