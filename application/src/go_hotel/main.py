from go_hotel.api.routes.autonomy_execution import router as autonomy_execution_router
from fastapi import FastAPI
from go_hotel.agent_gateway.runtime import install_agent_gateway
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
from go_hotel.api.routes.health import router as health_router
from go_hotel.api.routes.consumer_checkout import router as consumer_checkout_router
from go_hotel.api.routes.hotel import router as hotel_router
from go_hotel.api.routes.booking import router as booking_router
from go_hotel.api.routes.outbox import router as outbox_router
from go_hotel.api.routes.webhooks import router as webhook_router
from go_hotel.api.routes.ops import router as ops_router
from go_hotel.api.routes.connectors import router as connectors_router
from go_hotel.api.routes.onboarding import router as onboarding_router
from go_hotel.api.routes.routing import router as routing_router
from go_hotel.api.routes.merge import router as merge_router
from go_hotel.api.routes.fare import router as fare_router
from go_hotel.api.routes.catalog_fare import router as catalog_fare_router
from go_hotel.api.routes.compensation import router as compensation_router
from go_hotel.api.routes.truth import router as truth_router
from go_hotel.api.routes.judgment import router as judgment_router
from go_hotel.api.routes.dashboard import router as dashboard_router
from go_hotel.api.routes.auth import router as auth_router
from go_hotel.api.routes.interactive import router as interactive_router
from go_hotel.api.routes.bff import router as bff_router
from go_hotel.api.routes.registration_terms import router as registration_terms_router
from go_hotel.api.routes.observability import router as observability_router
from go_hotel.api.routes.consumer import router as consumer_router
from go_hotel.api.routes.consumer_identity import router as consumer_identity_router
from go_hotel.api.routes.mobile import router as mobile_router
from go_hotel.api.routes.flight import router as flight_router
from go_hotel.api.routes.rail import router as rail_router
from go_hotel.api.routes.mobility import router as mobility_router
from go_hotel.api.routes.rental_damage import router as rental_damage_router
from go_hotel.api.routes.rental_deposit import router as rental_deposit_router
from go_hotel.api.routes.rental_deposit_money import router as rental_deposit_money_router
from go_hotel.api.routes.rental_operations import router as rental_operations_router
from go_hotel.api.routes.ride_policy_operations import router as ride_policy_operations_router
from go_hotel.api.routes.attractions import router as attractions_router
from go_hotel.api.routes.journey import router as journey_router
from go_hotel.api.routes.journey_intelligence import router as journey_intelligence_router
from go_hotel.api.routes.journey_recovery import router as journey_recovery_router
from go_hotel.api.routes.journey_recovery_execution import router as journey_recovery_execution_router
from go_hotel.api.routes.recovery_reconciliation import router as recovery_reconciliation_router
from go_hotel.api.routes.recovery_control_plane import router as recovery_control_plane_router
from go_hotel.api.routes.recovery_reliability import router as recovery_reliability_router
from go_hotel.api.routes.recovery_strategy_governance import router as recovery_strategy_governance_router
from go_hotel.api.routes.recovery_experimentation import router as recovery_experimentation_router
from go_hotel.api.routes.recovery_learning_registry import router as recovery_learning_registry_router
from go_hotel.api.routes.recovery_data_governance import router as recovery_data_governance_router
from go_hotel.api.routes.recovery_learning_incident import router as recovery_learning_incident_router
from go_hotel.api.routes.recovery_release_governance import router as recovery_release_governance_router
from go_hotel.api.routes.recovery_runtime_verification import router as recovery_runtime_verification_router
from go_hotel.api.routes.recovery_runtime_observability import router as recovery_runtime_observability_router
from go_hotel.api.routes.recovery_runtime_telemetry_governance import router as recovery_runtime_telemetry_governance_router
from go_hotel.api.routes.recovery_runtime_telemetry_trust import router as recovery_runtime_telemetry_trust_router
from go_hotel.api.routes.recovery_runtime_identity_lifecycle import router as recovery_runtime_identity_lifecycle_router
from go_hotel.api.routes.recovery_runtime_identity_reissuance import router as recovery_runtime_identity_reissuance_router
from go_hotel.api.routes.recovery_credential_authority import router as recovery_credential_authority_router
from go_hotel.api.routes.recovery_federated_trust import router as recovery_federated_trust_router
from go_hotel.api.routes.recovery_external_trust_witness import router as recovery_external_trust_witness_router
from go_hotel.api.routes.recovery_transparency_gossip import router as recovery_transparency_gossip_router
from go_hotel.api.routes.recovery_trust_plane_dr import router as recovery_trust_plane_dr_router
from go_hotel.api.routes.recovery_trust_plane_chaos import router as recovery_trust_plane_chaos_router
from go_hotel.api.routes.recovery_continuous_chaos import router as recovery_continuous_chaos_router
from go_hotel.api.routes.recovery_waiver_exposure_governance import router as recovery_waiver_exposure_governance_router
from go_hotel.api.routes.recovery_exception_debt_burndown import router as recovery_exception_debt_burndown_router
from go_hotel.api.routes.recovery_enterprise_risk_portfolio import router as recovery_enterprise_risk_portfolio_router
from go_hotel.api.routes.recovery_enterprise_risk_appetite import router as recovery_enterprise_risk_appetite_router
from go_hotel.api.routes.recovery_enterprise_risk_forecast import router as recovery_enterprise_risk_forecast_router
from go_hotel.api.routes.recovery_risk_forecast_calibration import router as recovery_risk_forecast_calibration_router
from go_hotel.api.routes.recovery_forecast_model_promotion import router as recovery_forecast_model_promotion_router
from go_hotel.api.routes.recovery_forecast_statistical_promotion import router as recovery_forecast_statistical_promotion_router
from go_hotel.api.routes.recovery_forecast_drift_governance import router as recovery_forecast_drift_governance_router
from go_hotel.api.routes.recovery_forecast_training_governance import router as recovery_forecast_training_governance_router
from go_hotel.api.routes.recovery_forecast_artifact_governance import router as recovery_forecast_artifact_governance_router
from go_hotel.api.routes.recovery_forecast_serving_governance import router as recovery_forecast_serving_governance_router
from go_hotel.api.routes.recovery_forecast_traffic_governance import router as recovery_forecast_traffic_governance_router
from go_hotel.api.routes.recovery_forecast_online_feedback import router as recovery_forecast_online_feedback_router
from go_hotel.api.routes.recovery_forecast_online_segment_governance import router as recovery_forecast_online_segment_governance_router
from go_hotel.api.routes.recovery_forecast_segment_remediation import router as recovery_forecast_segment_remediation_router
from go_hotel.api.routes.recovery_forecast_generalization import router as recovery_forecast_generalization_router
from go_hotel.api.routes.recovery_forecast_portfolio_governance import router as recovery_forecast_portfolio_governance_router
from go_hotel.api.routes.recovery_forecast_champion_governance import router as recovery_forecast_champion_governance_router
from go_hotel.api.routes.hotel_partner_core import router as hotel_partner_core_router
from go_hotel.api.routes.commercial_constitution import router as commercial_constitution_router,supplier_router as supplier_commercial_router
from go_hotel.api.routes.good_hotel_standard import router as good_hotel_standard_router
from go_hotel.api.routes.production_connectors import router as production_connectors_router
from go_hotel.api.routes.production_connector_runtime import router as production_connector_runtime_router
from go_hotel.api.routes.connector_activation_readiness import router as connector_activation_readiness_router
from go_hotel.api.routes.paired_connector_pilot import router as paired_connector_pilot_router
from go_hotel.api.routes.external_sandbox_certification import router as external_sandbox_certification_router
from go_hotel.api.routes.named_supplier_external_execution import router as named_supplier_external_execution_router
from go_hotel.api.routes.hotel_supply_sandbox import router as hotel_supply_sandbox_router
from go_hotel.api.routes.aoluguya_supply_truth import router as aoluguya_supply_truth_router
from go_hotel.api.routes.real_external_execution import router as real_external_execution_router
from go_hotel.api.routes.hosted_direct_booking import router as hosted_direct_booking_router
from go_hotel.api.routes.mother_plan_p0 import router as mother_plan_p0_router
from go_hotel.api.routes.go_identity_entitlements import router as go_identity_entitlements_router
from go_hotel.api.routes.omnichannel_payment import router as omnichannel_payment_router
from go_hotel.api.routes.payment_sandbox_runtime import router as payment_sandbox_runtime_router
from go_hotel.api.routes.unified_money_movement import router as unified_money_movement_router
from go_hotel.api.routes.phase1_closure import router as phase1_closure_router
from go_hotel.api.routes.supplier_multivertical import router as supplier_multivertical_router
from go_hotel.api.routes.consumer_unified_lifecycle import router as consumer_unified_lifecycle_router
from go_hotel.api.routes.vertical_source_runtime import router as vertical_source_runtime_router
from go_hotel.api.routes.order_supplier_fulfillment import router as order_supplier_fulfillment_router
from go_hotel.api.routes.p0_final_closure import router as p0_final_closure_router
from go_hotel.api.routes.p0_design_code_freeze import router as p0_design_code_freeze_router
from go_hotel.api.routes.go_ai import router as go_ai_router
from go_hotel.api.routes.travel_intelligence import router as travel_intelligence_router
from go_hotel.api.routes.hotel_autopage_factory import router as hotel_autopage_factory_router
from go_hotel.api.routes.personal_travel_vault import router as personal_travel_vault_router
from go_hotel.api.routes.consumer_growth_direct_value import router as consumer_growth_direct_value_router
from go_hotel.api.routes.ai_travel_infrastructure import router as ai_travel_infrastructure_router
from go_hotel.api.routes.operations_console import router as operations_console_router
from go_hotel.api.routes.rc20_module_depth import router as rc20_module_depth_router
from go_hotel.api.routes.supplier_operations import router as supplier_operations_router
from go_hotel.api.routes.r8_release import router as r8_release_router
from go_hotel.api.routes.staging_execution_evidence import router as staging_execution_evidence_router
from go_hotel.security.service import identity_service, audit_service
from go_hotel.core.config import settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool
from go_hotel.observability.metrics import metrics, now_monotonic
from go_hotel.observability.logging import configure_json_logging
from go_hotel.incident.service import incident_service
import uuid, logging

configure_json_logging()
obs_logger=logging.getLogger("go.runtime")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup/shutdown resources using FastAPI lifespan."""
    identity_service.bootstrap()
    import asyncio
    tasks=[]
    if settings.hosted_reservation_expiry_worker_enabled:
        from go_hotel.workers.hosted_expiry_worker import run
        tasks.append(asyncio.create_task(run()))
    if settings.vertical_reservation_expiry_worker_enabled:
        from go_hotel.workers.vertical_expiry_worker import run
        tasks.append(asyncio.create_task(run()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:await task
            except asyncio.CancelledError:pass



app = FastAPI(
    title="GO Hotel Platform",
    version="9.1.0",
    description="GO P0 Final Closure: design/code frozen; runtime certification remains evidence-gated.",
    lifespan=lifespan,
)
from go_hotel.services.booking_data_release import BookingDataReleaseError

@app.exception_handler(BookingDataReleaseError)
async def booking_data_release_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':str(exc)},status_code=409,headers={'Cache-Control':'no-store, private'})

for r in [registration_terms_router, health_router, observability_router, bff_router, auth_router, hotel_router, consumer_router, consumer_identity_router, mobile_router, flight_router, rail_router, mobility_router, attractions_router, journey_router, journey_intelligence_router, journey_recovery_router, journey_recovery_execution_router, recovery_reconciliation_router, recovery_control_plane_router, recovery_reliability_router, recovery_strategy_governance_router, recovery_experimentation_router, recovery_learning_registry_router, recovery_data_governance_router, recovery_learning_incident_router, recovery_release_governance_router, recovery_runtime_verification_router, recovery_runtime_observability_router, recovery_runtime_telemetry_governance_router, recovery_runtime_telemetry_trust_router, recovery_runtime_identity_lifecycle_router, recovery_runtime_identity_reissuance_router, recovery_credential_authority_router, recovery_federated_trust_router, recovery_external_trust_witness_router, recovery_transparency_gossip_router, recovery_trust_plane_dr_router, recovery_trust_plane_chaos_router, recovery_continuous_chaos_router, recovery_waiver_exposure_governance_router, recovery_exception_debt_burndown_router, recovery_enterprise_risk_portfolio_router, recovery_enterprise_risk_appetite_router, recovery_enterprise_risk_forecast_router, recovery_risk_forecast_calibration_router, recovery_forecast_model_promotion_router, recovery_forecast_statistical_promotion_router, recovery_forecast_drift_governance_router, recovery_forecast_training_governance_router, recovery_forecast_artifact_governance_router, recovery_forecast_serving_governance_router, recovery_forecast_traffic_governance_router, recovery_forecast_online_feedback_router, recovery_forecast_online_segment_governance_router, recovery_forecast_segment_remediation_router, recovery_forecast_generalization_router, recovery_forecast_portfolio_governance_router, recovery_forecast_champion_governance_router, booking_router, fare_router, catalog_fare_router, compensation_router, truth_router, judgment_router, dashboard_router, interactive_router, outbox_router, webhook_router, ops_router, connectors_router, onboarding_router, routing_router, merge_router, go_ai_router]:
    app.include_router(r)
app.include_router(autonomy_execution_router)
app.include_router(rental_damage_router)
app.include_router(rental_deposit_router)
app.include_router(rental_deposit_money_router)
app.include_router(rental_operations_router)
app.include_router(ride_policy_operations_router)
app.include_router(hotel_partner_core_router)
app.include_router(commercial_constitution_router)
app.include_router(supplier_commercial_router)
app.include_router(good_hotel_standard_router)
app.include_router(production_connectors_router)
app.include_router(production_connector_runtime_router)
app.include_router(connector_activation_readiness_router)
app.include_router(paired_connector_pilot_router)
app.include_router(external_sandbox_certification_router)
app.include_router(named_supplier_external_execution_router)
app.include_router(hotel_supply_sandbox_router)
app.include_router(aoluguya_supply_truth_router)
app.include_router(real_external_execution_router)
app.include_router(hosted_direct_booking_router)
app.include_router(consumer_checkout_router)
app.include_router(mother_plan_p0_router)
app.include_router(go_identity_entitlements_router)
app.include_router(omnichannel_payment_router)
app.include_router(payment_sandbox_runtime_router)
app.include_router(unified_money_movement_router)
app.include_router(phase1_closure_router)
app.include_router(supplier_multivertical_router)
app.include_router(consumer_unified_lifecycle_router)
app.include_router(vertical_source_runtime_router)
app.include_router(order_supplier_fulfillment_router)
app.include_router(p0_final_closure_router)
app.include_router(p0_design_code_freeze_router)
app.include_router(hotel_autopage_factory_router)
app.include_router(personal_travel_vault_router)
app.include_router(consumer_growth_direct_value_router)
app.include_router(ai_travel_infrastructure_router)
app.include_router(operations_console_router)
app.include_router(rc20_module_depth_router)
app.include_router(supplier_operations_router)
app.include_router(r8_release_router)
app.include_router(staging_execution_evidence_router)
app.include_router(travel_intelligence_router)
install_agent_gateway(app)

class Sprint1RAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id=getattr(request.state,"request_id",None) or request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"
        request.state.request_id=request_id
        response=await call_next(request)
        p=getattr(request.state,"principal",None)
        if p and request.method in {"POST","PUT","PATCH","DELETE"}:
            try:
                await run_in_threadpool(audit_service.append, p, f"HTTP_{request.method}", "HTTP_RESOURCE", request.url.path, request_id=request_id, client_ip=request.client.host if request.client else None, http_method=request.method, path=request.url.path, metadata={"status_code":response.status_code})
            except Exception:
                pass
        response.headers["X-Request-ID"]=request_id
        return response

app.add_middleware(Sprint1RAuditMiddleware)

class Sprint1USecurityMiddleware(BaseHTTPMiddleware):
    SAFE={"GET","HEAD","OPTIONS"}
    EXEMPT={"/v1/registration/challenges","/bff/auth/login","/bff/auth/supplier/register","/bff/auth/sso/start","/bff/auth/sso/callback","/v1/consumer/auth/register","/v1/consumer/auth/login","/v1/mobile/auth/login","/v1/mobile/auth/refresh"}
    async def dispatch(self, request, call_next):
        if request.method not in self.SAFE and request.url.path not in self.EXEMPT:
            # Bearer/service clients preserve API compatibility. Browser cookie sessions require CSRF.
            from go_hotel.security.cookie_scope import session_cookie_names
            if not request.headers.get("Authorization"):
                from fastapi import HTTPException
                try:
                    access_name, refresh_name, csrf_name = session_cookie_names(request)
                except HTTPException as exc:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
            else:
                access_name = refresh_name = csrf_name = ''
            if not request.headers.get("Authorization") and (request.cookies.get(access_name) or request.cookies.get(refresh_name)):
                csrf_cookie=request.cookies.get(csrf_name)
                csrf_header=request.headers.get(settings.csrf_header_name)
                if not csrf_cookie or not csrf_header or csrf_cookie!=csrf_header:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"detail":"CSRF_VALIDATION_FAILED"},status_code=403)
                access=request.cookies.get(access_name)
                if access:
                    try:
                        p=await run_in_threadpool(identity_service.authenticate, access)
                        if not await run_in_threadpool(identity_service.verify_csrf, p.session_id, csrf_header):
                            from fastapi.responses import JSONResponse
                            return JSONResponse({"detail":"CSRF_SESSION_MISMATCH"},status_code=403)
                    except ValueError:
                        # Refresh may proceed using the rotating refresh cookie plus double-submit CSRF.
                        if request.url.path not in {"/bff/auth/refresh","/v1/consumer/auth/refresh"}:
                            from fastapi.responses import JSONResponse
                            return JSONResponse({"detail":"AUTHENTICATION_REQUIRED"},status_code=401)
        response=await call_next(request)
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
        if settings.cookie_secure: response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"]="no-store" if request.url.path.startswith(("/bff/auth","/v1/auth","/v1/consumer/auth","/v1/consumer/me")) else response.headers.get("Cache-Control","private")
        return response

app.add_middleware(Sprint1USecurityMiddleware)

def _incident_writes_blocked(scope):
    # Each service method owns and closes its Session inside the worker thread.
    # Keep the original short circuit and fail-closed exception behavior.
    return incident_service.active("GLOBAL_WRITES") or bool(scope and incident_service.active(scope))


class Sprint1VObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = now_monotonic()
        trace_id = request.headers.get("traceparent") or request.headers.get("X-Trace-ID") or f"tr_{uuid.uuid4().hex}"
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"
        request.state.trace_id = trace_id
        request.state.request_id = request_id
        path = request.url.path
        try:
            response = None
            # No cache or bypass: every write still checks current incident controls.
            # Blocking DB calls use the existing bounded Starlette/AnyIO pool.
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                scope = None
                if path.startswith("/v1/orders") or "/orders/" in path:
                    scope = "BOOKING_WRITES"
                if "payment" in path:
                    scope = "PAYMENT_WRITES"
                if "refund" in path:
                    scope = "REFUND_WRITES"
                if path.startswith("/v1/supplier"):
                    scope = "SUPPLIER_CONSOLE_WRITES"
                if path.startswith("/internal/v1") and any(x in path for x in ("activate", "suspend", "risk", "approval")):
                    scope = "ADMIN_HIGH_RISK_WRITES"
                if await run_in_threadpool(_incident_writes_blocked, scope):
                    from fastapi.responses import JSONResponse
                    response = JSONResponse({"detail": "INCIDENT_CONTROL_ACTIVE", "scope": scope or "GLOBAL_WRITES"}, status_code=503)
            if response is None:
                response = await call_next(request)
        except Exception:
            duration = (now_monotonic() - start) * 1000
            metrics.inc("go_http_requests_total")
            metrics.inc("go_http_requests_5xx_total")
            metrics.observe("go_http_request_duration_ms", duration, method=request.method)
            obs_logger.exception("request_failed", extra={"request_id": request_id, "trace_id": trace_id, "path": path, "method": request.method, "duration_ms": round(duration, 2)})
            raise
        duration = (now_monotonic() - start) * 1000
        metrics.inc("go_http_requests_total")
        metrics.observe("go_http_request_duration_ms", duration, method=request.method)
        metrics.inc("go_http_status_total", status=response.status_code)
        if response.status_code >= 500:
            metrics.inc("go_http_requests_5xx_total")
        if response.status_code in (401, 403):
            try:
                await run_in_threadpool(incident_service.record_security_signal, "AUTHZ_FAILURE", "MEDIUM", request_id=request_id, client_ip=request.client.host if request.client else None, metadata={"path": path, "status": response.status_code})
            except Exception:
                pass
        obs_logger.info("http_request", extra={"request_id": request_id, "trace_id": trace_id, "path": path, "method": request.method, "status_code": response.status_code, "duration_ms": round(duration, 2)})
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(Sprint1VObservabilityMiddleware)

# Sprint 1S operational frontends. Existing API contracts are unchanged.
_frontend_root = Path(__file__).resolve().parents[2] / "frontend"
if _frontend_root.exists():
    app.mount("/supplier-console", StaticFiles(directory=str(_frontend_root / "supplier"), html=True), name="supplier-console")
    app.mount("/go-admin", StaticFiles(directory=str(_frontend_root / "admin"), html=True), name="go-admin")
    app.mount("/console-assets", StaticFiles(directory=str(_frontend_root / "shared")), name="console-assets")
    app.mount("/go-app", StaticFiles(directory=str(_frontend_root / "consumer"), html=True), name="go-consumer-app")

from go_hotel.api.routes.registration_verification import router as registration_verification_router
app.include_router(registration_verification_router)

from go_hotel.api.routes.registration_privacy import router as registration_privacy_router
app.include_router(registration_privacy_router)
