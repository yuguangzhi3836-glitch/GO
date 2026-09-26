"""One resource-scoped boundary for Hosted administrative HTTP operations.

The only provisioned hotel delegation is an explicit engineering fixture. A
staff-role form cannot create the reserved root grant. Real hotel delegation
must supply a separate trusted adapter before this mode may be extended.
"""
import json
import os
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.hosted_content_acceptance import (
    principal_checked, user_checked, binding_hash, digest,
)
from go_hotel.services.travel_operational_facts import environment_allowed

ROOT_ROLE = 'HOTEL_OPERATIONS_ADMIN'
ROOT_SOURCE = 'isolated://hosted-operations-authority/v1'
STAFF_ROLES = {'FRONT_DESK', 'RESERVATIONS', 'DUTY_MANAGER'}


def root_grant(session, hotel_id, user_id):
    environment_allowed('ENGINEERING')
    if os.getenv('GO_HOSTED_OPERATIONS_AUTHORITY_MODE') != 'ISOLATED_FIXTURE':
        raise PermissionError('HOSTED_REAL_DELEGATION_UNVERIFIED')
    grant = session.scalar(select(m.HostedStaffRoleRow).where(
        m.HostedStaffRoleRow.hosted_hotel_id == hotel_id,
        m.HostedStaffRoleRow.staff_id == user_id,
        m.HostedStaffRoleRow.role == ROOT_ROLE,
        m.HostedStaffRoleRow.state == 'ACTIVE').with_for_update())
    if not grant or grant.evidence_reference != ROOT_SOURCE:
        raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')
    user_checked(session, user_id, 'admin:rules')
    return grant


def valid_staff(session, row):
    if not row or row.state != 'ACTIVE' or row.role not in STAFF_ROLES:
        raise PermissionError('HOTEL_STAFF_ROLE_REQUIRED')
    user_checked(session, row.staff_id, 'admin:orders')
    try:
        proof = json.loads(row.evidence_reference)
        if set(proof) != {'schema', 'grant_id', 'grant_hash', 'reference'} or proof['schema'] != 'HOSTED_STAFF_V1':
            raise ValueError()
        grant = session.get(m.HostedStaffRoleRow, proof['grant_id'])
        if not grant or grant.hosted_hotel_id != row.hosted_hotel_id:
            raise ValueError()
        current = root_grant(session, row.hosted_hotel_id, grant.staff_id)
        if current.staff_role_id != grant.staff_role_id or binding_hash(grant) != proof['grant_hash']:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise PermissionError('HOSTED_STAFF_AUTHORITY_UNVERIFIED') from None
    return row.role


def scoped(session, principal, hotel_id, permission, *, root_only=False):
    uid = principal_checked(session, principal, permission)
    if not session.get(m.HostedDirectHotelRow, hotel_id):
        raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')
    try:
        return root_grant(session, hotel_id, uid)
    except PermissionError:
        if root_only:
            raise
    rows = session.scalars(select(m.HostedStaffRoleRow).where(
        m.HostedStaffRoleRow.hosted_hotel_id == hotel_id,
        m.HostedStaffRoleRow.staff_id == uid, m.HostedStaffRoleRow.state == 'ACTIVE',
        m.HostedStaffRoleRow.role.in_(STAFF_ROLES))).all()
    for row in rows:
        try:
            role = valid_staff(session, row)
            if permission in {'admin:read', 'admin:orders'} or role == 'DUTY_MANAGER':
                return row
        except PermissionError:
            continue
    raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')


def reservation_hotel(session, reservation_id):
    row = session.get(m.HostedDirectReservationRow, reservation_id)
    offer = session.get(m.HostedDirectRoomOfferRow, row.hosted_offer_id) if row else None
    if not offer:
        raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')
    return offer.hosted_hotel_id


def _row(session, cls, key):
    row = session.get(cls, key)
    if row is None:
        raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')
    return row


def resource_hotels(session, route, params):
    """Resolve every supplied resource from DB; never trust a claimed hotel ID."""
    hotels = set()
    if 'hotel_id' in params:
        hotels.add(_row(session, m.HostedDirectHotelRow, params['hotel_id']).hosted_hotel_id)
    if 'slug' in params:
        hotel = session.scalar(select(m.HostedDirectHotelRow).where(m.HostedDirectHotelRow.page_slug == params['slug']))
        if not hotel: raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')
        hotels.add(hotel.hosted_hotel_id)
    for key, cls in [('pool_id', m.HostedDirectInventoryPoolRow), ('variant_id', m.HostedDirectRateVariantRow),
                     ('offer_id', m.HostedDirectRoomOfferRow), ('snapshot_id', m.HostedContentSnapshotRow),
                     ('binding_id', m.AlipayMerchantBindingRow), ('mandate_id', m.HostedFaultDebitMandateRow)]:
        if key in params:
            row = _row(session, cls, params[key])
            if key == 'variant_id':
                row = _row(session, m.HostedDirectRoomOfferRow, row.hosted_offer_id)
            hotels.add(row.hosted_hotel_id)
    reservation = params.get('reservation_id')
    if 'authorization_id' in params:
        reservation = _row(session, m.AlipayAuthorizationRow, params['authorization_id']).hosted_reservation_id
    if 'episode_id' in params:
        reservation = _row(session, m.HostedMoneyUnknownEpisodeRow, params['episode_id']).hosted_reservation_id
    if 'approval_id' in params:
        cls = m.HostedActionApprovalRow if route == 'action_approve' else m.AlipayAdjustmentApprovalRow
        row = _row(session, cls, params['approval_id'])
        reservation = row.hosted_reservation_id if cls == m.HostedActionApprovalRow else _row(session, m.AlipayAuthorizationRow, row.authorization_id).hosted_reservation_id
    stay_id = params.get('stay_id')
    case_id = params.get('case_id')
    decision_id = params.get('decision_id')
    if 'eligibility_id' in params:
        decision_id = _row(session, m.RefundEligibilityRow, params['eligibility_id']).post_stay_decision_id
    if decision_id:
        case_id = _row(session, m.PostStayDecisionRow, decision_id).dispute_case_id
    if case_id:
        if 'supplier_disruption' in route:
            row = _row(session, m.HostedSupplierDisruptionRow, case_id)
            hotels.add(row.hosted_hotel_id)
            reservation = row.hosted_reservation_id
        else:
            stay_id = _row(session, m.PostStayDisputeCaseRow, case_id).stay_lifecycle_id
    if stay_id:
        reservation = _row(session, m.GuestStayLifecycleRow, stay_id).hosted_reservation_id
    if reservation:
        hotels.add(reservation_hotel(session, reservation))
    if len(hotels) > 1:
        raise PermissionError('HOSTED_RESOURCE_SCOPE_MISMATCH')
    return hotels


RULE_ACTIONS = {'configure', 'hotel', 'offer', 'publish', 'content_snapshot', 'media_asset',
                'calendar_bootstrap', 'inventory_day', 'rate_day', 'staff_role', 'publish_fare_rule',
                'publication_preview'}
APPROVE_ACTIONS = {'content_approve', 'action_approve', 'uat_scenario', 'alipay_adjustment_approve',
                   'dispute_decision_approve', 'review_supplier_disruption', 'publication_review'}
FINANCE_ACTIONS = {'daily_close', 'alipay_merchant', 'alipay_credentials', 'alipay_authorize',
                   'alipay_release', 'alipay_fulfill', 'alipay_capture', 'alipay_adjustment',
                   'alipay_reconcile', 'open_funding_unknown_episode', 'resolve_funding_unknown_episode',
                   'refund_execute', 'create_supplier_fault_mandate', 'revoke_supplier_fault_mandate',
                   'supplier_fault_recovery', 'supplier_fault_finance', 'request_supplier_disruption',
                   'get_supplier_disruption', 'add_supplier_disruption_evidence', 'execute_supplier_disruption',
                   'list_supplier_disruptions', 'list_supplier_disruption_candidates'}
GLOBAL_ACTIONS = {'dashboard', 'hotel', 'expire_pending', 'expire_stay_credits',
                  'list_supplier_disruptions', 'list_supplier_disruption_candidates'}


def hosted_admin(request: Request, principal: Principal = Depends(admin_principal)):
    route = request.scope['route'].name
    permission = ('admin:rules' if route in RULE_ACTIONS else 'admin:approve' if route in APPROVE_ACTIONS
                  else 'admin:finance' if route in FINANCE_ACTIONS else 'admin:read' if request.method == 'GET'
                  else 'admin:orders')
    try:
        with SessionLocal() as session:
            principal_checked(session, principal, permission)
            if route == 'hotel':
                return principal  # Draft creation grants no hotel-scoped authority.
            params = dict(request.path_params)
            if route == 'configure': params['slug'] = 'aoluguya-harbin'
            hotels = resource_hotels(session, route, params)
            if not hotels:
                if route not in GLOBAL_ACTIONS:
                    raise PermissionError('HOSTED_RESOURCE_SCOPE_REQUIRED')
                # Existing global jobs/views may not silently cross hotel scopes.
                hotels = set(session.scalars(select(m.HostedDirectHotelRow.hosted_hotel_id)))
            for hotel_id in hotels:
                scoped(session, principal, hotel_id, permission, root_only=route == 'staff_role')
        return principal
    except (PermissionError, ValueError):
        raise HTTPException(403, detail='HOSTED_OPERATION_NOT_AUTHORIZED') from None


def mask_operation_result(value):
    """Only the audited guest-access endpoint may return unmasked guest data."""
    if isinstance(value, list): return [mask_operation_result(x) for x in value]
    if not isinstance(value, dict): return value
    return {key: ('***' if key in {'guest_name', 'guest_contact'} else mask_operation_result(item))
            for key, item in value.items()}
