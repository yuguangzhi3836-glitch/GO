"""Trigram access paths for canonical hotel search (PostgreSQL only).

The applicant searches the canonical catalogue by name and by address/city. The
filter is a substring match, so a plain btree cannot serve it; ``pg_trgm`` GIN
indexes can, and the extension is already part of this database (migration
0135). The index expressions are exactly the expressions the query builder emits
(``canonical_json->>'name'`` etc. via SQLAlchemy's ``JSON.Comparator.as_string``),
so the planner actually uses them rather than falling back to a sequential scan.

No index is created on SQLite: the review runner's SQLite snapshot is a
correctness fixture, not a performance target, and ``pg_trgm`` does not exist
there. Ordering of results is computed in the service, identically on both
dialects, so search results do not depend on whether an index exists.
"""
from alembic import op
import sqlalchemy as sa

revision = '0149_hotel_search_indexes'
down_revision = '0148_onboarding_constraints'
branch_labels = None
depends_on = None

TABLE = 'hotel_canonical_profile'
INDEXES = (
    ('ix_hcp_name_trgm', "(canonical_json->>'name')"),
    ('ix_hcp_name_zh_trgm', "(canonical_json->>'name_zh')"),
    ('ix_hcp_name_en_trgm', "(canonical_json->>'name_en')"),
    ('ix_hcp_address_trgm', "(canonical_json->>'address')"),
)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql' or not sa.inspect(bind).has_table(TABLE):
        return
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction; the autocommit
    # block commits the migration transaction before each online DDL statement.
    with op.get_context().autocommit_block():
        op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        for name, expression in INDEXES:
            op.execute(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} '
                f'ON {TABLE} USING gin ({expression} gin_trgm_ops)'
            )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    with op.get_context().autocommit_block():
        for name, _ in reversed(INDEXES):
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {name}')
