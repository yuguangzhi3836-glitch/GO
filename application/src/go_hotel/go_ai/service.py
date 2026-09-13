from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Any

from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.models import GoAIInvocationRow, GoAIRequestRow
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import now_utc
from go_hotel.judgment.service import judgment_service

from .complexity import GOAIComplexityClassifier
from .models import GOAIRequest, ProviderAttempt
from .planner import GOAITaskPlanner
from .providers import GOAIProviderError
from .registry import GOAIProviderRegistry, registry_from_settings
from .router import GOAIModelRouter
from .verification import GOAIVerificationGate

log = logging.getLogger("go.ai")

_TRANSACTION_AUTHORITY_SCOPES = {
    "ORDER_MUTATION",
    "PAYMENT_MUTATION",
    "REFUND_MUTATION",
    "SUPPLIER_MUTATION",
    "GO_JUDGMENT_FINAL_DECISION",
    "GO_RECOMMENDATION_FINAL_DECISION",
}


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class GOAIService:
    """GO-owned multi-model orchestration.

    The product name is always GO AI. External models are replaceable compute.
    This layer is not a source of truth for GO Judgment, orders, money, supplier
    facts, price, inventory, authorization, refund or payment state.
    """

    def __init__(self, registry: GOAIProviderRegistry | None = None):
        self.registry = registry if registry is not None else registry_from_settings()
        self.router = GOAIModelRouter(self.registry)
        self.complexity_classifier = GOAIComplexityClassifier()
        self.task_planner = GOAITaskPlanner()
        self.verification_gate = GOAIVerificationGate()

    def reload_registry(self) -> None:
        self.registry = registry_from_settings()
        self.router = GOAIModelRouter(self.registry)

    @staticmethod
    def _validate_request(message: str, task_type: str, decision_scope: str | None) -> None:
        if not message or not message.strip():
            raise ValueError("GO_AI_MESSAGE_REQUIRED")
        if len(message) > settings.go_ai_max_input_chars:
            raise ValueError("GO_AI_INPUT_TOO_LARGE")
        if decision_scope and decision_scope.upper() in _TRANSACTION_AUTHORITY_SCOPES:
            raise ValueError("GO_AI_DETERMINISTIC_AUTHORITY_REQUIRED")
        if task_type.upper() in {"GO_RECOMMENDATION_FINAL_DECISION", "GO_SCORE_FINAL_DECISION"}:
            raise ValueError("GO_AI_JUDGMENT_RULE_ENGINE_REQUIRED")

    def _create_request_audit(self, request: GOAIRequest, account_id: str | None) -> None:
        now = now_utc()
        request_hash = _hash_json({
            "task_type": request.task_type,
            "region": request.region,
            "language": request.language,
            "message": request.message,
            "context": request.context,
        })
        with SessionLocal.begin() as s:
            s.add(GoAIRequestRow(
                go_ai_request_id=request.request_id,
                account_id=account_id or "ANONYMOUS_INTERNAL",
                task=request.task_type,
                region=request.region,
                locale=request.language or "und",
                state="ROUTING",
                request_hash=request_hash,
                selected_provider=None,
                selected_model=None,
                response_hash=None,
                failure_code=None,
                created_at=now,
                updated_at=now,
            ))

    def _record_attempt(self, request_id: str, attempt_no: int, provider, status: str, latency_ms: int, *, result=None, error_code: str | None = None) -> None:
        with SessionLocal.begin() as s:
            s.add(GoAIInvocationRow(
                go_ai_invocation_id=f"goaiinv_{uuid.uuid4().hex}",
                go_ai_request_id=request_id,
                provider_key=provider.config.provider_id,
                model_name=provider.config.model,
                attempt_no=attempt_no,
                state=status,
                latency_ms=latency_ms,
                input_tokens=getattr(result, "input_tokens", None),
                output_tokens=getattr(result, "output_tokens", None),
                provider_request_id=(getattr(result, "raw_metadata", {}) or {}).get("request_id") if result else None,
                response_hash=_hash_json({"text": result.text, "provider": result.provider_id, "model": result.model}) if result else None,
                error_code=error_code,
                created_at=now_utc(),
            ))

    def _complete_request(self, request_id: str, *, provider_id: str | None = None, model: str | None = None, result=None, failure_code: str | None = None) -> None:
        with SessionLocal.begin() as s:
            row = s.get(GoAIRequestRow, request_id)
            if not row:
                return
            row.state = "FAILED" if failure_code else "COMPLETED"
            row.selected_provider = provider_id
            row.selected_model = model
            row.response_hash = _hash_json({"text": result.text, "provider": result.provider_id, "model": result.model}) if result else None
            row.failure_code = failure_code
            row.updated_at = now_utc()


    @staticmethod
    def _max_cost_tier_for_complexity(tier: str) -> int | None:
        return {
            "TIER_1_FAST": 1,
            "TIER_2_STANDARD": 2,
            "TIER_3_DEEP_REASONING": 3,
            "TIER_4_MULTI_AGENT": None,
            "TIER_5_HIGH_ASSURANCE": None,
        }.get(tier)

    def _execute_compute_task(
        self,
        *,
        parent_request: GOAIRequest,
        task_id: str,
        task_type: str,
        instruction: str,
        attempt_base: int,
        max_cost_tier: int | None,
        exclude_provider_ids: set[str] | None = None,
    ) -> tuple[str, str, str]:
        child = GOAIRequest(
            request_id=parent_request.request_id,
            message=instruction,
            task_type=task_type,
            region=parent_request.region,
            language=parent_request.language,
            context=parent_request.context,
            max_output_tokens=parent_request.max_output_tokens,
            temperature=parent_request.temperature,
        )
        candidates = self.router.candidates(child, max_cost_tier=max_cost_tier, exclude_provider_ids=exclude_provider_ids)
        if not candidates:
            raise ValueError("GO_AI_NO_ELIGIBLE_MODEL_PROVIDER")
        last_code = "GO_AI_ALL_ELIGIBLE_PROVIDERS_FAILED"
        for offset, provider in enumerate(candidates[: settings.go_ai_max_provider_attempts], start=1):
            started = time.monotonic()
            attempt_no = attempt_base + offset
            try:
                result = provider.generate(child)
                latency_ms = round((time.monotonic() - started) * 1000)
                self._record_attempt(parent_request.request_id, attempt_no, provider, "SUCCEEDED", latency_ms, result=result)
                return result.text, provider.config.provider_id, provider.config.model
            except GOAIProviderError as exc:
                last_code = exc.code
                latency_ms = round((time.monotonic() - started) * 1000)
                self._record_attempt(parent_request.request_id, attempt_no, provider, "FAILED", latency_ms, error_code=exc.code)
        raise ValueError(last_code)

    def orchestrate(
        self,
        *,
        message: str,
        region: str = "GLOBAL",
        language: str | None = None,
        context: dict[str, Any] | None = None,
        account_id: str | None = None,
        max_output_tokens: int = 1600,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """GO AI full-model aggregation and intelligent orchestration entrypoint.

        Complexity classification, task planning, provider routing, parallel execution,
        synthesis and verification are GO-owned. External model/provider identity remains
        replaceable infrastructure and is hidden from the consumer response.
        """
        self._validate_request(message, "GENERAL", None)
        request = GOAIRequest(
            request_id=f"goai_{uuid.uuid4().hex}",
            message=message.strip(),
            task_type="ORCHESTRATION",
            region=region.upper(),
            language=language,
            context=context or {},
            max_output_tokens=min(max(1, int(max_output_tokens)), settings.go_ai_max_output_tokens),
            temperature=min(max(float(temperature), 0.0), 1.0),
        )
        self._create_request_audit(request, account_id)
        assessment = self.complexity_classifier.classify(request.message, context=request.context)
        if assessment.tier == "TIER_0_DETERMINISTIC":
            self._complete_request(request.request_id, failure_code="GO_AI_DETERMINISTIC_SYSTEM_REQUIRED")
            raise ValueError("GO_AI_DETERMINISTIC_SYSTEM_REQUIRED")

        plan = self.task_planner.plan(request.message, assessment)
        if not plan:
            self._complete_request(request.request_id, failure_code="GO_AI_TASK_PLAN_EMPTY")
            raise ValueError("GO_AI_TASK_PLAN_EMPTY")

        max_cost_tier = self._max_cost_tier_for_complexity(assessment.tier)
        task_results: dict[str, dict[str, str]] = {}
        max_workers = min(len(plan), max(1, assessment.max_parallel_tasks), 6)
        try:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="go-ai") as pool:
                futures = {
                    pool.submit(
                        self._execute_compute_task,
                        parent_request=request,
                        task_id=task.task_id,
                        task_type=task.task_type,
                        instruction=task.instruction,
                        attempt_base=(idx + 1) * 100,
                        max_cost_tier=max_cost_tier,
                    ): task
                    for idx, task in enumerate(plan)
                }
                for future in as_completed(futures):
                    task = futures[future]
                    text, provider_id, model = future.result()
                    task_results[task.task_id] = {
                        "task_type": task.task_type,
                        "text": text,
                        "provider_id": provider_id,
                        "model": model,
                    }
        except Exception as exc:
            self._complete_request(request.request_id, failure_code="GO_AI_ORCHESTRATION_TASK_FAILED")
            if isinstance(exc, ValueError):
                raise
            raise ValueError("GO_AI_ORCHESTRATION_TASK_FAILED") from exc

        synthesis_input = "\n\n".join(
            f"[{task_id}] {payload['text']}" for task_id, payload in sorted(task_results.items())
        )
        synthesis_instruction = (
            "Act as the synthesis compute behind GO AI. Produce one coherent answer to the original user request. "
            "Reconcile conflicts, preserve uncertainty, do not invent supplier/payment facts, and do not expose provider/model identities.\n\n"
            f"Original request:\n{request.message}\n\nSubtask outputs:\n{synthesis_input}"
        )
        try:
            synthesis_text, synthesis_provider, synthesis_model = self._execute_compute_task(
                parent_request=request,
                task_id="task_synthesis",
                task_type="SYNTHESIS",
                instruction=synthesis_instruction,
                attempt_base=9000,
                max_cost_tier=None if assessment.tier in {"TIER_3_DEEP_REASONING", "TIER_4_MULTI_AGENT", "TIER_5_HIGH_ASSURANCE"} else max_cost_tier,
            )
        except Exception as exc:
            # Synthesis is also an orchestration task: finalize its failure just
            # like a subtask failure instead of leaving the request ROUTING.
            self._complete_request(request.request_id, failure_code="GO_AI_ORCHESTRATION_TASK_FAILED")
            if isinstance(exc, ValueError):
                raise
            raise ValueError("GO_AI_ORCHESTRATION_TASK_FAILED") from exc

        model_check_completed = False
        if assessment.requires_model_verification:
            verify_instruction = (
                "Independently check the candidate answer for contradictions, unsupported certainty, missing constraints, "
                "or invented external facts. This is advisory verification only; do not alter GO transaction truth.\n\n"
                f"Original request:\n{request.message}\n\nCandidate answer:\n{synthesis_text}"
            )
            try:
                self._execute_compute_task(
                    parent_request=request,
                    task_id="task_verification",
                    task_type="VERIFICATION",
                    instruction=verify_instruction,
                    attempt_base=9500,
                    max_cost_tier=None,
                    exclude_provider_ids={synthesis_provider},
                )
                model_check_completed = True
            except ValueError:
                # Verification provider diversity is desirable but must not fabricate availability.
                model_check_completed = False

        verification = self.verification_gate.verify(
            answer=synthesis_text, assessment=assessment, model_check_completed=model_check_completed
        )
        if not verification.deterministic_checks_passed:
            self._complete_request(request.request_id, failure_code="GO_AI_VERIFICATION_BLOCKED")
            raise ValueError("GO_AI_VERIFICATION_BLOCKED")

        # Provider/model are persisted internally for audit, but remain hidden from consumer payload.
        class _SyntheticResult:
            text = synthesis_text
            provider_id = synthesis_provider
            model = synthesis_model
        self._complete_request(request.request_id, provider_id=synthesis_provider, model=synthesis_model, result=_SyntheticResult())
        return {
            "request_id": request.request_id,
            "assistant": "GO AI",
            "answer": synthesis_text,
            "orchestration": {
                "platform": "GO_AI_FULL_MODEL_AGGREGATION_AND_ORCHESTRATION",
                "complexity_tier": assessment.tier,
                "complexity_score": assessment.score,
                "reason_codes": list(assessment.reasons),
                "planned_task_count": len(plan),
                "parallel_execution": max_workers > 1,
                "synthesis": "GO_OWNED_ORCHESTRATION",
                "verification": verification.status,
                "model_verification": verification.model_check_status,
                "external_models_are_replaceable_compute": True,
                "provider_identity_exposed_to_consumer": False,
            },
            "decision_boundary": {
                "advisory_only": True,
                "execution_allowed": verification.execution_allowed,
                "order_truth": "DETERMINISTIC_SYSTEM_ONLY",
                "payment_truth": "DETERMINISTIC_SYSTEM_ONLY",
                "supplier_fact": "SUPPLIER_EVIDENCE_ONLY",
                "go_judgment": "GO_JUDGMENT_RULES_AND_EVIDENCE_ONLY",
            },
        }

    def respond(
        self,
        *,
        message: str,
        task_type: str = "GENERAL",
        region: str = "GLOBAL",
        language: str | None = None,
        context: dict[str, Any] | None = None,
        decision_scope: str | None = None,
        max_output_tokens: int = 1200,
        temperature: float = 0.2,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_request(message, task_type, decision_scope)
        request = GOAIRequest(
            request_id=f"goai_{uuid.uuid4().hex}",
            message=message.strip(),
            task_type=task_type.upper(),
            region=region.upper(),
            language=language,
            context=context or {},
            max_output_tokens=min(max(1, int(max_output_tokens)), settings.go_ai_max_output_tokens),
            temperature=min(max(float(temperature), 0.0), 1.0),
        )
        self._create_request_audit(request, account_id)
        candidates = self.router.candidates(request)
        if not candidates:
            self._complete_request(request.request_id, failure_code="GO_AI_NO_ELIGIBLE_MODEL_PROVIDER")
            raise ValueError("GO_AI_NO_ELIGIBLE_MODEL_PROVIDER")
        attempts: list[ProviderAttempt] = []
        for attempt_no, provider in enumerate(candidates[: settings.go_ai_max_provider_attempts], start=1):
            started = time.monotonic()
            try:
                result = provider.generate(request)
                latency_ms = round((time.monotonic() - started) * 1000)
                attempts.append(ProviderAttempt(provider.config.provider_id, "SUCCESS", latency_ms))
                self._record_attempt(request.request_id, attempt_no, provider, "SUCCEEDED", latency_ms, result=result)
                self._complete_request(request.request_id, provider_id=provider.config.provider_id, model=provider.config.model, result=result)
                log.info("go_ai_request_completed", extra={
                    "go_ai_request_id": request.request_id,
                    "task_type": request.task_type,
                    "region": request.region,
                    "provider_id": provider.config.provider_id,
                    "model": provider.config.model,
                    "attempts": len(attempts),
                    "latency_ms": latency_ms,
                })
                # Consumer-facing payload deliberately hides provider/model identity.
                return {
                    "request_id": request.request_id,
                    "assistant": "GO AI",
                    "answer": result.text,
                    "task_type": request.task_type,
                    "decision_boundary": {
                        "advisory_only": True,
                        "order_truth": "DETERMINISTIC_SYSTEM_ONLY",
                        "payment_truth": "DETERMINISTIC_SYSTEM_ONLY",
                        "supplier_fact": "SUPPLIER_EVIDENCE_ONLY",
                        "go_judgment": "GO_JUDGMENT_RULES_AND_EVIDENCE_ONLY",
                    },
                }
            except GOAIProviderError as exc:
                latency_ms = round((time.monotonic() - started) * 1000)
                attempts.append(ProviderAttempt(provider.config.provider_id, "FAILED", latency_ms, exc.code))
                self._record_attempt(request.request_id, attempt_no, provider, "FAILED", latency_ms, error_code=exc.code)
                log.warning("go_ai_provider_failed", extra={
                    "go_ai_request_id": request.request_id,
                    "task_type": request.task_type,
                    "region": request.region,
                    "provider_id": provider.config.provider_id,
                    "error_code": exc.code,
                    "latency_ms": latency_ms,
                })
                continue
        self._complete_request(request.request_id, failure_code="GO_AI_ALL_ELIGIBLE_PROVIDERS_FAILED")
        log.error("go_ai_all_providers_failed", extra={"go_ai_request_id": request.request_id, "attempts": [asdict(x) for x in attempts]})
        raise ValueError("GO_AI_ALL_ELIGIBLE_PROVIDERS_FAILED")

    def recommend_hotels(self, *, hotel_ids: list[str], limit: int = 10) -> dict[str, Any]:
        """GO-standard recommendation only; never asks an external model to decide."""
        recommended: list[dict[str, Any]] = []
        other: list[dict[str, Any]] = []
        for hotel_id in list(dict.fromkeys(hotel_ids)):
            try:
                judgment = judgment_service.get_latest(hotel_id)
            except Exception:
                other.append({"hotel_id": hotel_id, "recommendation_status": "NOT_YET_RATED_OR_MISSING"})
                continue
            recommendation = judgment.get("recommendation") or {}
            item = {
                "hotel_id": hotel_id,
                "judgment_id": judgment.get("judgment_id"),
                "recommendation_status": recommendation.get("status"),
                "reason_codes": recommendation.get("reason_codes") or [],
                "go_score": judgment.get("public_go_score"),
                "confidence_bps": judgment.get("confidence_bps"),
                "explanation": judgment.get("explanation"),
                "evidence_package_id": (judgment.get("evidence_package") or {}).get("package_id"),
            }
            if item["recommendation_status"] == "GO_RECOMMENDED":
                recommended.append(item)
            else:
                other.append(item)
        recommended.sort(key=lambda x: ((x.get("go_score") or 0), (x.get("confidence_bps") or 0)), reverse=True)
        return {
            "assistant": "GO AI",
            "authority": "GO_JUDGMENT",
            "decision_model": "DETERMINISTIC_GO_STANDARD",
            "external_models_are_compute_only": True,
            "recommended": recommended[: max(1, min(int(limit), 50))],
            "other_statuses": other,
        }

    def request_audit(self, request_id: str) -> dict[str, Any]:
        with SessionLocal() as s:
            row = s.get(GoAIRequestRow, request_id)
            if not row:
                raise ValueError("GO_AI_REQUEST_NOT_FOUND")
            invocations = s.scalars(select(GoAIInvocationRow).where(GoAIInvocationRow.go_ai_request_id == request_id).order_by(GoAIInvocationRow.attempt_no)).all()
            return {
                "request_id": row.go_ai_request_id,
                "account_id": row.account_id,
                "task_type": row.task,
                "region": row.region,
                "language": row.locale,
                "state": row.state,
                "selected_provider": row.selected_provider,
                "selected_model": row.selected_model,
                "request_hash": row.request_hash,
                "response_hash": row.response_hash,
                "failure_code": row.failure_code,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "invocations": [{
                    "invocation_id": x.go_ai_invocation_id,
                    "provider_id": x.provider_key,
                    "model": x.model_name,
                    "attempt_no": x.attempt_no,
                    "state": x.state,
                    "latency_ms": x.latency_ms,
                    "input_tokens": x.input_tokens,
                    "output_tokens": x.output_tokens,
                    "response_hash": x.response_hash,
                    "error_code": x.error_code,
                } for x in invocations],
                "prompt_or_answer_body_persisted": False,
            }

    def provider_status(self) -> dict[str, Any]:
        return {
            "product_name": "GO AI",
            "provider_count": len(self.registry.all()),
            "providers": self.registry.public_status(),
            "secrets_stored_in_database": False,
            "provider_secrets_returned_by_api": False,
            "final_go_judgment_authority": "GO_JUDGMENT_RULES_AND_EVIDENCE_ONLY",
            "transaction_authority": "DETERMINISTIC_SYSTEM_ONLY",
            "china_overseas_silent_fallback": False,
        }


go_ai_service = GOAIService()
