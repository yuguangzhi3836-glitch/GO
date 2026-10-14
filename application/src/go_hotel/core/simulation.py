from go_hotel.core.config import settings


def consumer_simulated_checkout_enabled(vertical: str | None = None) -> bool:
    environment = settings.app_env.strip().lower()
    if environment in {"local", "test", "demo"}:
        return True
    return False
