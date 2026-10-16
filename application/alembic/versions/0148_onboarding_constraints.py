"""Supplier onboarding hotel claim: relationship type + the two uniqueness rules.

Additive and fail-closed. Nothing existing is rewritten; the only schema change is
one nullable column, so this is safe to apply before the code that writes it.

Two uniqueness rules, each answering a concrete failure that application code
cannot answer on its own because two concurrent reviewers both pass the
application-level check:

  * ``uq_hreg_approved_hotel`` — one canonical hotel has at most one APPROVED
    GO Direct relation. Without it, two suppliers claiming the same hotel can both
    end up "verified owner" of it, and every later routing/contract decision
    becomes ambiguous.
  * ``uq_commercial_case_live_onboarding_hotel`` — one hotel has at most one
    *granted* supplier onboarding case. UNDER_REVIEW claims may legitimately
    race (that is what CLAIM_CONFLICT is for); a granted hotel may not.

Both indexes refuse to be created over data that already violates them: the
upgrade raises a named code instead of silently succeeding, because a partial
unique index that never got created is a guarantee that silently does not exist.

One index may already exist before this revision on a *fresh* database.
``commercial_case`` is created by an older revision from the live declarative
metadata (``Base.metadata.tables['commercial_case'].create(...)``), so as soon as
the model declares ``uq_commercial_case_live_onboarding_hotel`` the table is born
with it. Blindly creating it again aborts the whole upgrade, and a fresh install
is exactly the path a new environment takes. So each index is *accepted only
after checking its shape* -- same rule revision 0145 already applies to its own
index -- and created otherwise.
"""
from alembic import op
import sqlalchemy as sa

revision = '0148_onboarding_constraints'
down_revision = '0147_legal_entity_document'
branch_labels = None
depends_on = None

REGISTRATION = 'hotel_registration_go_direct'
CASE_TABLE = 'commercial_case'
RELATIONSHIPS = "'OWNER','OPERATOR','MANAGEMENT_COMPANY','AUTHORIZED_AGENT'"
LIVE_ONBOARDING_CASE = (
    "case_type = 'SUPPLIER_ONBOARDING' AND property_id IS NOT NULL AND state IN "
    "('VERIFIED','CONTRACT_PENDING','CONTRACT_NEEDS_CHANGES','CONTRACT_UNDER_REVIEW',"
    "'CONTRACT_ACTIVE','BUSINESS_ENABLED')"
)


def _assert_clean(bind):
    duplicate_hotels = bind.scalar(sa.text(
        "SELECT count(*) FROM (SELECT hotel_id FROM " + REGISTRATION +
        " WHERE state = 'APPROVED' GROUP BY hotel_id HAVING count(*) > 1) AS dup"))
    if duplicate_hotels:
        raise RuntimeError('HOTEL_GO_DIRECT_DUPLICATE_APPROVED_HOTEL_PRESENT')
    duplicate_cases = bind.scalar(sa.text(
        "SELECT count(*) FROM (SELECT property_id FROM " + CASE_TABLE +
        " WHERE " + LIVE_ONBOARDING_CASE + " GROUP BY property_id HAVING count(*) > 1) AS dup"))
    if duplicate_cases:
        raise RuntimeError('SUPPLIER_ONBOARDING_LIVE_HOTEL_DUPLICATE_PRESENT')


def _existing_index(bind, table, name):
    return next((i for i in sa.inspect(bind).get_indexes(table) if i['name'] == name), None)


def _accept_or_create_index(bind, *, name, table, columns, where_sql, tokens):
    """Create the partial unique index, or accept an identical one already there.

    "Identical" is verified, not assumed: unique, on the right column, partial,
    valid, and its predicate must still name every state it is supposed to cover.
    An index that exists but says something else is a worse failure than a
    missing one, so it is a hard error rather than a silent skip.
    """
    existing = _existing_index(bind, table, name)
    if existing is None:
        op.create_index(name, table, columns, unique=True,
                        postgresql_where=sa.text(where_sql), sqlite_where=sa.text(where_sql))
        return False
    if not existing['unique'] or existing['column_names'] != columns:
        raise RuntimeError(name.upper() + '_DEFINITION_MISMATCH')
    if bind.dialect.name == 'postgresql':
        definition = bind.scalar(sa.text(
            'SELECT indexdef FROM pg_indexes WHERE indexname = :n AND tablename = :t'),
            {'n': name, 't': table}) or ''
        valid = bind.scalar(sa.text(
            'SELECT i.indisvalid AND i.indisready AND i.indpred IS NOT NULL '
            'FROM pg_index i WHERE i.indexrelid = to_regclass(:n)'), {'n': name})
        if not valid:
            raise RuntimeError(name.upper() + '_INVALID_OR_NOT_PARTIAL')
        missing = [t for t in tokens if t not in definition]
        if missing:
            raise RuntimeError(name.upper() + '_PREDICATE_MISMATCH:' + ','.join(missing))
    elif existing.get('dialect_options', {}).get('sqlite_where') is None:
        raise RuntimeError(name.upper() + '_INVALID_OR_NOT_PARTIAL')
    return True


def upgrade():
    bind = op.get_bind()
    _assert_clean(bind)
    with op.batch_alter_table(REGISTRATION) as batch:
        batch.add_column(sa.Column('relationship_type', sa.String(32), nullable=True))
        batch.create_check_constraint(
            'ck_hreg_relationship_type',
            'relationship_type IS NULL OR relationship_type IN (' + RELATIONSHIPS + ')')
    _accept_or_create_index(
        bind, name='uq_hreg_approved_hotel', table=REGISTRATION, columns=['hotel_id'],
        where_sql="state = 'APPROVED'", tokens=['APPROVED'])
    _accept_or_create_index(
        bind, name='uq_commercial_case_live_onboarding_hotel', table=CASE_TABLE,
        columns=['property_id'], where_sql=LIVE_ONBOARDING_CASE,
        tokens=['SUPPLIER_ONBOARDING', 'VERIFIED', 'CONTRACT_PENDING',
                'CONTRACT_NEEDS_CHANGES', 'CONTRACT_UNDER_REVIEW', 'CONTRACT_ACTIVE',
                'BUSINESS_ENABLED'])


def downgrade():
    op.drop_index('uq_commercial_case_live_onboarding_hotel', table_name=CASE_TABLE)
    op.drop_index('uq_hreg_approved_hotel', table_name=REGISTRATION)
    with op.batch_alter_table(REGISTRATION) as batch:
        batch.drop_constraint('ck_hreg_relationship_type', type_='check')
        batch.drop_column('relationship_type')
