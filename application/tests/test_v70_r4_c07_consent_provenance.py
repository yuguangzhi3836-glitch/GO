"""V70-R4-C07-01: graph release audit carries exact consent provenance."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from go_hotel.db.models import ProfileAccessAuditRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.personal_travel_vault import (
    personal_travel_vault_service as vault,
)
from go_hotel.travel_intelligence.service import (
    travel_intelligence_service as svc,
)
from tests.test_round2_c07_explicit_preferences import (
    PURPOSE,
    consent,
    save,
    traveler,
)


def context_consent(purpose, scope):
    return vault.grant_consent("owner", {
        "traveler_id": "traveler",
        "consent_type": "TRAVELER_CONTEXT",
        "purpose": purpose,
        "scope": scope,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat(),
    })["consent_id"]


def last_graph_audit():
    with SessionLocal() as session:
        return session.scalars(
            select(ProfileAccessAuditRow).where(
                ProfileAccessAuditRow.action == "TRAVELER_CONTEXT_READ"
            ).order_by(ProfileAccessAuditRow.created_at.desc())
        ).first()


def test_graph_audit_attributes_only_active_exact_purpose_context_grants():
    traveler()
    explicit = consent()
    saved = save(explicit)
    wrong_purpose = context_consent(
        "FLIGHT_PLANNING", ["TRAVEL_PREFERENCES"]
    )
    revoked = context_consent(PURPOSE, ["TRAVELER_IDENTITY"])
    vault.revoke_consent("owner", revoked)
    active = context_consent(PURPOSE, ["TRAVEL_PREFERENCES"])

    graph = svc.traveler_graph("traveler", purpose=PURPOSE)
    assert graph["durable_preferences"] == [saved]
    audit = last_graph_audit()
    assert audit.metadata_json["context_consent_ids"] == [active]
    assert explicit not in audit.metadata_json["context_consent_ids"]
    assert wrong_purpose not in audit.metadata_json["context_consent_ids"]
    assert revoked not in audit.metadata_json["context_consent_ids"]


def test_graph_with_no_context_grant_records_empty_provenance_and_releases_nothing():
    traveler()
    save(consent())
    graph = svc.traveler_graph("traveler", purpose=PURPOSE)
    assert graph["durable_preferences"] == []
    audit = last_graph_audit()
    assert audit.metadata_json["context_consent_ids"] == []
