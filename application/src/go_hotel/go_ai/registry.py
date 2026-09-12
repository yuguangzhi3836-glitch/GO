from __future__ import annotations

import json
from typing import Iterable

from go_hotel.core.config import settings
from .models import ProviderConfig
from .providers import BaseGOAIProvider, build_provider


class GOAIProviderRegistry:
    def __init__(self, providers: Iterable[BaseGOAIProvider] | None = None):
        self._providers: dict[str, BaseGOAIProvider] = {}
        if providers:
            for provider in providers:
                self.register(provider)

    def register(self, provider: BaseGOAIProvider) -> None:
        self._providers[provider.config.provider_id] = provider

    def all(self) -> list[BaseGOAIProvider]:
        return list(self._providers.values())

    def get(self, provider_id: str) -> BaseGOAIProvider | None:
        return self._providers.get(provider_id)

    def public_status(self) -> list[dict]:
        rows = []
        for provider in sorted(self._providers.values(), key=lambda p: (p.config.priority, p.config.cost_tier, p.config.provider_id)):
            c = provider.config
            rows.append({
                "provider_id": c.provider_id,
                "adapter": c.adapter,
                "model": c.model,
                "enabled": c.enabled,
                "configured": provider.is_configured(),
                "priority": c.priority,
                "regions": list(c.regions),
                "task_types": list(c.task_types),
                "cost_tier": c.cost_tier,
                "api_key_env": c.api_key_env,
                "secret_value_exposed": False,
            })
        return rows


def _parse_provider_config(raw: dict) -> ProviderConfig:
    required = ("provider_id", "adapter", "model", "base_url", "api_key_env")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError("GO_AI_PROVIDER_CONFIG_MISSING:" + ",".join(missing))
    return ProviderConfig(
        provider_id=str(raw["provider_id"]),
        adapter=str(raw["adapter"]),
        model=str(raw["model"]),
        base_url=str(raw["base_url"]),
        api_key_env=str(raw["api_key_env"]),
        enabled=bool(raw.get("enabled", True)),
        priority=int(raw.get("priority", 100)),
        timeout_seconds=float(raw.get("timeout_seconds", settings.go_ai_timeout_seconds)),
        regions=tuple(str(x).upper() for x in raw.get("regions", ["GLOBAL"])),
        task_types=tuple(str(x).upper() for x in raw.get("task_types", ["*"])),
        cost_tier=int(raw.get("cost_tier", 2)),
        extra_headers=dict(raw.get("extra_headers") or {}),
        extra_body=dict(raw.get("extra_body") or {}),
    )


def registry_from_settings() -> GOAIProviderRegistry:
    registry = GOAIProviderRegistry()
    raw = (settings.go_ai_providers_json or "").strip()
    if not raw:
        return registry
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("GO_AI_PROVIDERS_JSON_INVALID") from exc
    if not isinstance(payload, list):
        raise ValueError("GO_AI_PROVIDERS_JSON_MUST_BE_LIST")
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("GO_AI_PROVIDER_CONFIG_MUST_BE_OBJECT")
        registry.register(build_provider(_parse_provider_config(row)))
    return registry
