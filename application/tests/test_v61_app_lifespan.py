from pathlib import Path

import pytest


@pytest.mark.no_db
def test_v61_app_declares_lifespan_without_deprecated_on_event_handlers():
    source = Path("src/go_hotel/main.py").read_text(encoding="utf-8")
    assert '@app.on_event("startup")' not in source
    assert '@app.on_event("shutdown")' not in source
    assert "@asynccontextmanager" in source
    assert "async def lifespan(app: FastAPI):" in source
    assert "lifespan=lifespan" in source
    assert "identity_service.bootstrap()" in source


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_v61_lifespan_preserves_legacy_startup_bootstrap_semantics(monkeypatch):
    """The FastAPI lifespan must preserve the old startup hook behavior exactly.

    V6.1 previously used::

        @app.on_event("startup")
        def sprint1r_bootstrap_identity():
            identity_service.bootstrap()

    The lifespan migration must still call bootstrap exactly once, before the app
    becomes available, and must not add a new shutdown-side bootstrap call.
    """
    from go_hotel import main

    calls: list[str] = []

    def fake_bootstrap() -> None:
        calls.append("bootstrap")

    monkeypatch.setattr(main.identity_service, "bootstrap", fake_bootstrap)

    assert calls == []
    async with main.app.router.lifespan_context(main.app):
        assert calls == ["bootstrap"]
    assert calls == ["bootstrap"]
