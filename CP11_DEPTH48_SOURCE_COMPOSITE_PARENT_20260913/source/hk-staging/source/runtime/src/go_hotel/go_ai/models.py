from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GOAITaskType = Literal[
    "GENERAL",
    "TRAVEL_INTENT",
    "TRIP_PLANNING",
    "EXTRACTION",
    "SUMMARIZATION",
    "EXPLANATION",
    "HOTEL_JUDGMENT_SUPPORT",
    "SYNTHESIS",
    "VERIFICATION",
]


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    adapter: str
    model: str
    base_url: str
    api_key_env: str
    enabled: bool = True
    priority: int = 100
    timeout_seconds: float = 20.0
    regions: tuple[str, ...] = ("GLOBAL",)
    task_types: tuple[str, ...] = ("*",)
    cost_tier: int = 2
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GOAIRequest:
    request_id: str
    message: str
    task_type: str = "GENERAL"
    region: str = "GLOBAL"
    language: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    max_output_tokens: int = 1200
    temperature: float = 0.2


@dataclass(frozen=True)
class ProviderResult:
    text: str
    provider_id: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderAttempt:
    provider_id: str
    status: str
    latency_ms: int
    error_code: str | None = None
