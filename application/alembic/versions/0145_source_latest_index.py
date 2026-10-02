"""Bound the ordered lookup within one order's source-decision history."""
from alembic import op
from sqlalchemy import inspect, text

revision = '0145_source_latest_index'
down_revision = '0144_credit_source_intent_index'
branch_labels = None
depends_on = None

TABLE = 'vertical_source_decision'
INDEX = 'ix_vertical_source_latest'
COLUMNS = ['vertical', 'business_id', 'created_at']


def upgrade():
    bind = op.get_bind()
    # Migration 0097 creates this table from current metadata on a fresh DB.
    # Accept that index only after checking its shape and PostgreSQL validity;
    # IF NOT EXISTS alone would silently accept a broken concurrent build.
    existing = next((i for i in inspect(bind).get_indexes(TABLE) if i['name'] == INDEX), None)
    if existing is not None:
        if existing['column_names'] != COLUMNS or existing['unique'] or existing.get('column_sorting'):
            raise RuntimeError('SOURCE_LATEST_INDEX_DEFINITION_MISMATCH')
        if bind.dialect.name == 'postgresql':
            valid = bind.scalar(text('''SELECT i.indisvalid AND i.indisready
                AND i.indpred IS NULL AND i.indexprs IS NULL
                AND i.indnkeyatts=3 AND i.indnatts=3 AND i.indoption::text='0 0 0'
                AND am.amname='btree'
                FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
                JOIN pg_am am ON am.oid=c.relam
                WHERE i.indexrelid=to_regclass(:name) AND i.indrelid=to_regclass(:table)'''),
                {'name': INDEX, 'table': TABLE})
            if not valid:
                raise RuntimeError('SOURCE_LATEST_INDEX_INVALID_OR_INCOMPATIBLE')
        elif existing.get('dialect_options', {}).get('sqlite_where') is not None:
            raise RuntimeError('SOURCE_LATEST_INDEX_DEFINITION_MISMATCH')
        return
    if op.get_bind().dialect.name == 'postgresql':
        # Run only through the separately approved migration process.
        with op.get_context().autocommit_block():
            op.execute(f'CREATE INDEX CONCURRENTLY {INDEX} ON {TABLE} ({", ".join(COLUMNS)})')
    else:
        op.create_index(INDEX, TABLE, COLUMNS)


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute(f'DROP INDEX CONCURRENTLY {INDEX}')
    else:
        op.drop_index(INDEX, table_name=TABLE)
