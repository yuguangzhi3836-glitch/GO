"""Isolated-only, hotel-scoped authority for UNKNOWN recovery.

Retains the historical reserved operations grant. No public provisioner and no
real hotel delegation adapter exist here. Ordinary staff-role forms cannot
create HOTEL_OPERATIONS_ADMIN. Other administrative routes are unchanged.
"""
import os
from sqlalchemy import select
from go_hotel.db import models as m
from go_hotel.security.rbac import permissions_for
from go_hotel.security.service import Principal, aware, now
from go_hotel.services.hosted_checkout import isolated

ROOT_ROLE = 'HOTEL_OPERATIONS_ADMIN'
ROOT_SOURCE = 'isolated://hosted-operations-authority/v1'


def require_scope(session, principal, reservation_id):
    isolated()
    if os.getenv('GO_HOSTED_OPERATIONS_AUTHORITY_MODE') != 'ISOLATED_FIXTURE':
        raise PermissionError('HOSTED_REAL_DELEGATION_UNVERIFIED')
    if not isinstance(principal, Principal):
        raise PermissionError('UNKNOWN_AUTHENTICATED_PRINCIPAL_REQUIRED')
    user = session.get(m.IdentityUserRow, principal.user_id, with_for_update=True)
    auth = session.get(m.AuthSessionRow, principal.session_id, with_for_update=True)
    if (not user or user.status != 'ACTIVE' or user.actor_type != 'GO_ADMIN'
            or 'admin:finance' not in permissions_for(user.roles or [])
            or not auth or auth.user_id != user.user_id or auth.status != 'ACTIVE'
            or auth.revoked_at is not None or aware(auth.expires_at) <= now()):
        raise PermissionError('UNKNOWN_ACTIVE_FINANCE_SESSION_REQUIRED')
    reservation = session.get(m.HostedDirectReservationRow, reservation_id)
    offer = session.get(m.HostedDirectRoomOfferRow, reservation.hosted_offer_id) if reservation else None
    grant = session.scalar(select(m.HostedStaffRoleRow).where(
        m.HostedStaffRoleRow.hosted_hotel_id == offer.hosted_hotel_id,
        m.HostedStaffRoleRow.staff_id == user.user_id,
        m.HostedStaffRoleRow.role == ROOT_ROLE,
        m.HostedStaffRoleRow.state == 'ACTIVE',
        m.HostedStaffRoleRow.evidence_reference == ROOT_SOURCE,
    ).with_for_update()) if offer else None
    if not grant:
        raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')
