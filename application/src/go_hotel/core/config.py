from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "local"
    database_url: str = "postgresql+psycopg://go:go@localhost:5432/go_hotel"
    outbox_batch_size: int = 100
    outbox_poll_seconds: float = 0.5
    outbox_max_attempts: int = 5
    outbox_lock_timeout_seconds: int = 30
    outbox_transport: str = "logging"
    outbox_http_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    saga_retry_seconds: int = 2
    webhook_secret: str = "dev-webhook-secret"
    connector_timeout_seconds: float = 4.0
    connector_retry_count: int = 1
    reconciliation_interval_seconds: int = 30
    connector_vault_master_key: str = "dev-only-change-me"
    alipay_webhook_verification_key: str | None = None
    connector_initial_rollout_percent: int = 5
    jwt_signing_key: str = "dev-only-change-me-jwt"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    bootstrap_admin_username: str = "go_admin"
    bootstrap_admin_password: str = "change-me-admin"
    bootstrap_supplier_username: str = "supplier_owner"
    bootstrap_supplier_password: str = "change-me-supplier"
    bootstrap_supplier_id: str = "sup_mock"
    cookie_secure: bool = False
    cookie_domain: str | None = None
    access_cookie_name: str = "go_access"
    refresh_cookie_name: str = "go_refresh"
    csrf_cookie_name: str = "go_csrf"
    consumer_access_cookie_name: str = "go_consumer_access"
    consumer_refresh_cookie_name: str = "go_consumer_refresh"
    consumer_csrf_cookie_name: str = "go_consumer_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_cookie_samesite: str = "lax"
    mfa_required_for_admin: bool = False
    mfa_issuer: str = "GO"
    oidc_enabled: bool = False
    oidc_provider_name: str = "corporate"
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_default_actor_type: str = "GO_ADMIN"
    oidc_default_roles: str = "GO_READ_ONLY"
    allowed_origins: str = ""
    trace_sample_rate: float = 1.0
    slow_request_ms: int = 1500
    # Registration cannot open until a real outbound verification service and its
    # delivery/receipt acceptance evidence have been approved for the environment.
    registration_privacy_evidence_path: str = ""
    registration_verification_enabled: bool = False
    registration_email_config_path: str = ""
    registration_terms_version: str = "2026-09-19-draft-v2"
    mobile_push_mode: str = "mock"
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    mobile_push_batch_size: int = 100
    mobile_push_receipt_batch_size: int = 200
    mobile_push_receipt_min_age_seconds: int = 15
    readiness_require_postgres: bool = True
    hosted_reservation_expiry_worker_enabled: bool = False
    vertical_reservation_expiry_worker_enabled: bool = True

    # GO AI - GO-owned multi-model orchestration. Product name remains "GO AI".
    # Provider secrets are referenced by environment-variable name inside GO_AI_PROVIDERS_JSON.
    # The secret values themselves remain in GO-owned KMS/Secret Manager/runtime environment.
    go_ai_providers_json: str = ""
    go_ai_timeout_seconds: float = 20.0
    go_ai_max_provider_attempts: int = 3
    go_ai_max_input_chars: int = 20000
    go_ai_max_output_tokens: int = 8000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    travel_intelligence_enabled: bool = False
    model_gateway_external_egress_enabled: bool = False

settings = Settings()
