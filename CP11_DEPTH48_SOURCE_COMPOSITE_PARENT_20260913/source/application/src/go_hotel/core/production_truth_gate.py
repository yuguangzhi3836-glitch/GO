from __future__ import annotations

from go_hotel.core.config import settings

_PRODUCTION_ENVS = {"prod", "production"}


def production_truth_required(vertical: str, action: str) -> None:
    """Fail closed when an engineering/synthetic supplier path reaches production.

    This gate deliberately does not attempt provider selection or add any business
    capability. It only prevents local engineering fixtures from being represented
    as external supplier truth in production.
    """
    if settings.app_env.strip().lower() in _PRODUCTION_ENVS:
        raise ValueError(f"{vertical.upper()}_PROVIDER_TRUTH_REQUIRED:{action.upper()}")
