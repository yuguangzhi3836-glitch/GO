from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .models import GOAIRequest, ProviderConfig, ProviderResult


class GOAIProviderError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(code if not message else f"{code}: {message}")
        self.code = code


class BaseGOAIProvider(ABC):
    def __init__(self, config: ProviderConfig):
        self.config = config

    def is_configured(self) -> bool:
        return bool(self.config.base_url and self.config.model and os.getenv(self.config.api_key_env))

    def _api_key(self) -> str:
        key = os.getenv(self.config.api_key_env)
        if not key:
            raise GOAIProviderError("GO_AI_PROVIDER_KEY_NOT_CONFIGURED")
        return key

    @abstractmethod
    def generate(self, request: GOAIRequest) -> ProviderResult:
        raise NotImplementedError


class OpenAICompatibleProvider(BaseGOAIProvider):
    """Provider adapter for OpenAI-compatible chat-completions APIs.

    This adapter is deliberately vendor-neutral. GO owns routing and passes a
    provider-specific base URL/model through GO-owned configuration.
    """

    def generate(self, request: GOAIRequest) -> ProviderResult:
        key = self._api_key()
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        headers.update(self.config.extra_headers)
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a compute provider behind GO AI. Follow the supplied task and facts. "
                        "Do not claim authority to change GO orders, payments, supplier facts, or GO Judgment."
                    ),
                },
                {"role": "user", "content": request.message},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.context:
            body["messages"].insert(1, {"role": "system", "content": f"GO context: {request.context}"})
        body.update(self.config.extra_body)
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_TRANSPORT_ERROR") from exc
        if response.status_code == 429:
            raise GOAIProviderError("GO_AI_PROVIDER_RATE_LIMITED")
        if response.status_code >= 500:
            raise GOAIProviderError("GO_AI_PROVIDER_UPSTREAM_ERROR")
        if response.status_code >= 400:
            raise GOAIProviderError("GO_AI_PROVIDER_REQUEST_REJECTED")
        try:
            payload = response.json()
            choice = payload["choices"][0]
            text = choice["message"]["content"]
            usage = payload.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_INVALID_RESPONSE") from exc
        return ProviderResult(
            text=str(text),
            provider_id=self.config.provider_id,
            model=self.config.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
            raw_metadata={"http_status": response.status_code},
        )


class GeminiProvider(BaseGOAIProvider):
    """Adapter for Gemini generateContent-compatible endpoints.

    The base URL is GO-owned configuration; credentials are read only from the
    named environment variable at request time and are never persisted.
    """

    def generate(self, request: GOAIRequest) -> ProviderResult:
        key = self._api_key()
        url = self.config.base_url.rstrip("/") + f"/models/{self.config.model}:generateContent"
        params = {"key": key}
        prompt = request.message
        if request.context:
            prompt = f"GO context: {request.context}\n\nUser request: {request.message}"
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        body.update(self.config.extra_body)
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(url, params=params, headers=self.config.extra_headers, json=body)
        except httpx.TimeoutException as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_TRANSPORT_ERROR") from exc
        if response.status_code == 429:
            raise GOAIProviderError("GO_AI_PROVIDER_RATE_LIMITED")
        if response.status_code >= 500:
            raise GOAIProviderError("GO_AI_PROVIDER_UPSTREAM_ERROR")
        if response.status_code >= 400:
            raise GOAIProviderError("GO_AI_PROVIDER_REQUEST_REJECTED")
        try:
            payload = response.json()
            candidate = payload["candidates"][0]
            parts = candidate["content"]["parts"]
            text = "".join(str(part.get("text", "")) for part in parts)
            usage = payload.get("usageMetadata") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_INVALID_RESPONSE") from exc
        return ProviderResult(
            text=text,
            provider_id=self.config.provider_id,
            model=self.config.model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            finish_reason=candidate.get("finishReason"),
            raw_metadata={"http_status": response.status_code},
        )


class AnthropicProvider(BaseGOAIProvider):
    def generate(self, request: GOAIRequest) -> ProviderResult:
        key = self._api_key()
        url = self.config.base_url.rstrip("/") + "/messages"
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        headers.update(self.config.extra_headers)
        user_text = request.message
        if request.context:
            user_text = f"GO context: {request.context}\n\nUser request: {request.message}"
        body: dict[str, Any] = {
            "model": self.config.model,
            "system": (
                "You are a compute provider behind GO AI. Do not claim authority over GO Judgment, "
                "orders, payments, refunds, inventory, supplier authorization, or transaction truth."
            ),
            "messages": [{"role": "user", "content": user_text}],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        body.update(self.config.extra_body)
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_TRANSPORT_ERROR") from exc
        if response.status_code == 429:
            raise GOAIProviderError("GO_AI_PROVIDER_RATE_LIMITED")
        if response.status_code >= 500:
            raise GOAIProviderError("GO_AI_PROVIDER_UPSTREAM_ERROR")
        if response.status_code >= 400:
            raise GOAIProviderError("GO_AI_PROVIDER_REQUEST_REJECTED")
        try:
            payload = response.json()
            text = "".join(str(x.get("text", "")) for x in payload.get("content", []) if x.get("type") == "text")
            usage = payload.get("usage") or {}
        except (ValueError, KeyError, TypeError) as exc:
            raise GOAIProviderError("GO_AI_PROVIDER_INVALID_RESPONSE") from exc
        if not text.strip():
            raise GOAIProviderError("GO_AI_PROVIDER_INVALID_RESPONSE")
        return ProviderResult(
            text=text,
            provider_id=self.config.provider_id,
            model=self.config.model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            finish_reason=payload.get("stop_reason"),
            raw_metadata={"http_status": response.status_code},
        )


class DeterministicTestProvider(BaseGOAIProvider):
    """Non-production provider used only for deterministic unit tests."""

    def __init__(self, config: ProviderConfig, text: str = "GO AI test response", fail_code: str | None = None):
        super().__init__(config)
        self._text = text
        self._fail_code = fail_code

    def is_configured(self) -> bool:
        return True

    def generate(self, request: GOAIRequest) -> ProviderResult:
        if self._fail_code:
            raise GOAIProviderError(self._fail_code)
        time.sleep(0)
        return ProviderResult(text=self._text, provider_id=self.config.provider_id, model=self.config.model)


def build_provider(config: ProviderConfig) -> BaseGOAIProvider:
    adapter = config.adapter.strip().lower()
    if adapter in {"openai_compatible", "openai-compatible", "chat_completions"}:
        return OpenAICompatibleProvider(config)
    if adapter in {"gemini", "google_gemini"}:
        return GeminiProvider(config)
    if adapter in {"anthropic", "claude"}:
        return AnthropicProvider(config)
    raise ValueError(f"GO_AI_UNKNOWN_PROVIDER_ADAPTER:{config.adapter}")
