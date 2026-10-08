"""Preserve hosted confirmation states and full ledger account identities."""
from alembic import op
import sqlalchemy as sa

revision = '0137_hosted_funding_width'
down_revision = '0136_hosted_unknown_episode'
branch_labels = None
depends_on = None
WIDTHS = (('hosted_direct_reservation', 'reservation_state', 40, 64),
          ('omnichannel_ledger_entry', 'account_code', 64, 128))


def columns():
    inspector = sa.inspect(op.get_bind())
    result = []
    for table, name, old, new in WIDTHS:
        column = next(c for c in inspector.get_columns(table) if c['name'] == name)
        if not isinstance(column['type'], sa.String) or column['type'].length not in (old, new) or column['nullable']:
            raise RuntimeError('HOSTED_FUNDING_WIDTH_SCHEMA_MISMATCH')
        result.append((table, name, old, new, column['type'].length))
    return result


def resize(rows, upgrade):
    for table, name, old, new, current in rows:
        target = new if upgrade else old
        if current != target:
            with op.batch_alter_table(table) as batch:
                batch.alter_column(name, existing_type=sa.String(current), type_=sa.String(target), existing_nullable=False)


def upgrade():
    resize(columns(), True)


def downgrade():
    rows = columns()
    # Refuse all narrowing before any DDL: never truncate historical identities.
    for table, name, old, _, _ in rows:
        if op.get_bind().execute(sa.text(f'SELECT COUNT(*) FROM {table} WHERE length({name}) > :width'), {'width': old}).scalar_one():
            raise RuntimeError('HOSTED_FUNDING_DOWNGRADE_WOULD_TRUNCATE_HISTORY')
    resize(rows, False)
