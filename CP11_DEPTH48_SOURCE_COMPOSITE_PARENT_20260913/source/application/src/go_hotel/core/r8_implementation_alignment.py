from __future__ import annotations

RELEASE_TRAIN = "R8.1"
CONTROL_VERSION = "V6.1"
EFFECTIVE_DATE = "2026-08-22"

DAY1_HOTEL_COVERAGE_PIPELINE = [
    "MULTI_OTA_OFFICIAL_DISCOVERY",
    "CANONICAL_HOTEL",
    "MULTI_SOURCE_MERGE",
    "MEDIA_HARVEST_AND_ROOM_BIND",
    "AUTHORIZED_FALLBACK_INVENTORY",
    "PAGE_LIVE",
    "HOTEL_REGISTRATION_AND_OFFICIAL_ASSOCIATION",
    "OFFICIAL_CONTENT_AND_GO_DIRECT_UPGRADE",
]

INVENTORY_PRIORITY = ["GO_DIRECT", "THIRD_PARTY_API_FALLBACK", "DEEP_LINK_FALLBACK"]

PUBLICATION_PRINCIPLES = {
    "page_requires_hotel_registration": False,
    "fallback_sellable_requires_go_direct": False,
    "page_owner": "GO",
    "third_party_content_requires_rights_basis": True,
    "room_media_requires_room_type_binding": True,
    "origin_hotlinks_are_not_public_media": True,
}

AFTER_SALES_MODEL = {
    "call_center": False,
    "traditional_after_sales_team": False,
    "consumer_entry": "GO_TRIPS_SELF_SERVICE",
    "default_resolution": "API_AUTOMATION",
    "exception_path": "EXCEPTION_RESOLUTION_ENGINE",
    "human_intervention": "EXCEPTION_ONLY",
}

FALLBACK_LEGAL_TRUTH_FIELDS = [
    "inventory_provider",
    "booking_provider",
    "service_provider",
    "payment_collector",
    "fulfillment_provider",
    "refund_provider",
    "liability_basis",
]

STAGING_CONSTRAINTS = {
    "alembic_revision_max_chars": 32,
    "postgres_object_name_max_chars": 63,
    "frontend_static_bundles_required": ["go-app", "supplier-console", "go-admin"],
    "browser_render_required": True,
    "workbench_shell": "/bin/sh",
    "pipefail_allowed": False,
    "unzip_required": False,
    "deployment_success_requires": ["container_health", "migration_log", "https_response", "browser_render"],
    "secrets_in_code_or_handoff": False,
}

IDENTITY_TRUTH = {
    "consumer_self_registration": True,
    "supplier_password_login": True,
    "admin_mfa_backend_enabled": True,
    "admin_first_enrollment_ui_delivered": False,
    "admin_password_login_claimed_usable": False,
}

def snapshot() -> dict:
    return {
        "release_train": RELEASE_TRAIN,
        "control_version": CONTROL_VERSION,
        "effective_date": EFFECTIVE_DATE,
        "day1_hotel_coverage_pipeline": DAY1_HOTEL_COVERAGE_PIPELINE,
        "inventory_priority": INVENTORY_PRIORITY,
        "publication_principles": PUBLICATION_PRINCIPLES,
        "after_sales_model": AFTER_SALES_MODEL,
        "fallback_legal_truth_fields": FALLBACK_LEGAL_TRUTH_FIELDS,
        "staging_constraints": STAGING_CONSTRAINTS,
        "identity_truth": IDENTITY_TRUTH,
    }
