from __future__ import annotations

from .models import GOAIRequest
from .providers import BaseGOAIProvider
from .registry import GOAIProviderRegistry


class GOAIModelRouter:
    def __init__(self, registry: GOAIProviderRegistry):
        self.registry = registry

    @staticmethod
    def _supports(provider: BaseGOAIProvider, request: GOAIRequest) -> bool:
        cfg = provider.config
        if not cfg.enabled or not provider.is_configured():
            return False
        regions = {x.upper() for x in cfg.regions}
        if "*" not in regions and request.region.upper() not in regions:
            return False
        tasks = {x.upper() for x in cfg.task_types}
        if "*" not in tasks and request.task_type.upper() not in tasks:
            return False
        return True

    def candidates(
        self,
        request: GOAIRequest,
        *,
        max_cost_tier: int | None = None,
        exclude_provider_ids: set[str] | None = None,
    ) -> list[BaseGOAIProvider]:
        excluded = exclude_provider_ids or set()
        providers = [p for p in self.registry.all() if self._supports(p, request) and p.config.provider_id not in excluded]
        if max_cost_tier is not None:
            bounded = [p for p in providers if p.config.cost_tier <= max_cost_tier]
            # Cost ceilings are a preference, not a silent outage trigger.
            if bounded:
                providers = bounded
        # Lower priority wins. Within the same priority, lower cost tier wins.
        return sorted(providers, key=lambda p: (p.config.priority, p.config.cost_tier, p.config.provider_id))
