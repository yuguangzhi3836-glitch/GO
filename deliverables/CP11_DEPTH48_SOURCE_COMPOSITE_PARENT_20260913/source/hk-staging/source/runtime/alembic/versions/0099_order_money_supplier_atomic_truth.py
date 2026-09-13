from alembic import op
import sqlalchemy as sa
from go_hotel.db.models import Base

revision='0099_e9ab838ca46d'
down_revision='0098_1372d8c45b6f'
branch_labels=None
depends_on=None

TABLES=['payment_order_root','psp_settlement_line','bank_statement_line','order_supplier_fulfillment','order_supplier_fulfillment_event']
IMMUTABLE=['payment_order_root','psp_settlement_line','bank_statement_line','order_supplier_fulfillment_event','vertical_source_decision']

def upgrade():
    bind=op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind,checkfirst=True)
    cols={c['name'] for c in sa.inspect(bind).get_columns('payment_order_fact_binding')}
    if 'legal_entity_id' not in cols:
        with op.batch_alter_table('payment_order_fact_binding') as batch:
            batch.add_column(sa.Column('legal_entity_id',sa.String(length=64),nullable=True))
    op.execute("UPDATE payment_order_fact_binding SET legal_entity_id = CASE WHEN currency='CNY' THEN 'GO_CN' ELSE 'GO_GLOBAL' END WHERE legal_entity_id IS NULL")
    if bind.dialect.name=='sqlite':
        for table in IMMUTABLE:
            op.execute(f"CREATE TRIGGER IF NOT EXISTS trg_{table}_0099_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_0099_ATOMIC_TRUTH_EVIDENCE'); END")
            op.execute(f"CREATE TRIGGER IF NOT EXISTS trg_{table}_0099_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_0099_ATOMIC_TRUTH_EVIDENCE'); END")
    elif bind.dialect.name=='postgresql':
        op.execute("CREATE OR REPLACE FUNCTION deny_0099_atomic_truth_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_0099_ATOMIC_TRUTH_EVIDENCE'; END; $$ LANGUAGE plpgsql")
        for table in IMMUTABLE:
            op.execute(f"CREATE TRIGGER trg_{table}_0099_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_0099_atomic_truth_mutation()")
            op.execute(f"CREATE TRIGGER trg_{table}_0099_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_0099_atomic_truth_mutation()")

def downgrade():
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':
        for table in IMMUTABLE:
            op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_0099_deny_update ON {table}')
            op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_0099_deny_delete ON {table}')
        op.execute('DROP FUNCTION IF EXISTS deny_0099_atomic_truth_mutation()')
    cols={c['name'] for c in sa.inspect(bind).get_columns('payment_order_fact_binding')}
    if 'legal_entity_id' in cols:
        with op.batch_alter_table('payment_order_fact_binding') as batch:
            batch.drop_column('legal_entity_id')
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind,checkfirst=True)
