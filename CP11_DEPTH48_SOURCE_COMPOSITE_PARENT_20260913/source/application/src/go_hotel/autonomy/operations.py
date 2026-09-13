"""Reviewed operational observations for all 14 cells.

Adapters query aggregate states from their owned services and persist observations
through the executor. They do not approve refunds, certify releases, expose PII,
change qualifications, or call suppliers. Wider business adapters need separate
capability-specific review and evidence before registration.
"""
from sqlalchemy import func, select

from go_hotel.db.models import Base, IdentityUserRow
from go_hotel.security.rbac import permissions_for
from .definitions import ALL_CELL_REGISTRY
from .durable import DurableExecutor, ExecutionError, Handler
from .types import Environment


# No caller-supplied SQL, table names, authority envelopes, or Python import paths.
OBSERVATIONS = {
    'C01': ('HOTEL_EXCEPTION', ('hotel_order_runtime', 'hosted_direct_reservation', 'post_stay_dispute_case')),
    'C02': ('FLIGHT_EXCEPTION', ('flight_order_runtime', 'flight_refund_runtime')),
    'C03': ('RAIL_EXCEPTION', ('rail_order_runtime', 'rail_refund_runtime')),
    'C04': ('RENTAL_PICKUP_RETURN', ('mobility_rental_order_runtime', 'rental_change_quote')),
    'C05': ('RIDE_CANCEL_EXCEPTION', ('mobility_ride_order_runtime',)),
    'C06': ('ATTRACTION_FULFILLMENT', ('attraction_order_runtime',)),
    'C07': ('TRAVELER_CONTEXT_EVIDENCE', ('profile_import_job',)),
    'C08': ('TOOL_ORCHESTRATION', ('go_ai_request',)),
    'C09': ('RECOMMENDATION_EVIDENCE', ('recommendation_decision_runtime',)),
    'C10': ('JOURNEY_EXCEPTION', ('go_journey_runtime',)),
    'C11': ('RECONCILIATION', ('omnichannel_payment_intent', 'finance_scoped_close_batch')),
    'C12': ('OBSERVABILITY', ('transactional_outbox',)),
    'C13': ('REGRESSION', ('journey_recovery_release_verification',)),
    'C14': ('LEGAL_EVIDENCE_AUDIT', ('autonomy_task',)),
}


def _observe(tables):
    def run(ctx):
        if ctx.payload:
            raise ExecutionError('OBSERVATION_PAYLOAD_MUST_BE_EMPTY')
        readings = {}
        for name in tables:
            table = Base.metadata.tables[name]
            state = table.c.get('status')
            if state is None:
                state = table.c.get('state')
            stmt = select(func.count()).select_from(table) if state is None else select(state, func.count()).group_by(state)
            if name == 'autonomy_task':
                stmt = stmt.where(table.c.environment == ctx.environment)
            result = ctx.execute(stmt).all()
            readings[name] = {'total': result[0][0]} if state is None else {str(k): n for k, n in result}
        return {'cell_id': ctx.cell_id, 'environment': ctx.environment,
                'readings': readings, 'scope': 'AGGREGATE_OPERATIONAL_OBSERVATION'}
    return run


def _assess(ctx):
    observations = ctx.previous[0]
    attention = [{'source': name, 'state': state, 'count': count}
        for name, states in observations['readings'].items() for state, count in states.items()
        if count and any(word in state.upper() for word in ('FAIL', 'DEAD', 'HOLD', 'UNKNOWN', 'UNCERTAIN', 'CONFLICT'))]
    return {**observations, 'attention': attention,
            'assessment': 'REVIEW_REQUIRED' if attention else 'NO_FLAGGED_STATE_OBSERVED',
            'business_actions_executed': False, 'production_certification': False}


def observation_handlers():
    handlers = []
    for cell_id, (capability, tables) in OBSERVATIONS.items():
        if capability not in ALL_CELL_REGISTRY.cell(cell_id).capabilities:
            raise ExecutionError('OBSERVATION_CAPABILITY_NOT_OWNED')
        for name in tables:
            if name not in Base.metadata.tables:
                raise ExecutionError('OBSERVATION_SCHEMA_MISSING:' + name)
        handlers.append(Handler(cell_id + '.OPERATIONS_OBSERVE', 'DEPTH08.1', cell_id,
                         capability, steps=(_observe(tables), _assess)))
    return tuple(handlers)


def operator_authorized(session, actor):
    # The user may have lost their role since submission. Lock against concurrent
    # role revocation for the duration of each local transactional step.
    user = session.scalar(select(IdentityUserRow).where(IdentityUserRow.user_id == actor).with_for_update())
    return bool(user and user.status == 'ACTIVE' and user.actor_type == 'GO_ADMIN'
                and 'admin:rules' in permissions_for(user.roles or []))


def application_executor():
    from go_hotel.core.config import settings
    from go_hotel.db.session import SessionLocal
    aliases = {'LOCAL': 'DEV', 'DEVELOPMENT': 'DEV', 'DEMO': 'TEST',
               'TESTING': 'TEST', 'PROD': 'PRODUCTION'}
    env = settings.app_env.upper()
    try:
        environment = Environment(aliases.get(env, env))
    except ValueError as exc:
        raise ExecutionError('UNKNOWN_EXECUTION_ENVIRONMENT') from exc
    return DurableExecutor(SessionLocal, observation_handlers(), environment=environment,
                           authorize_actor=operator_authorized)
