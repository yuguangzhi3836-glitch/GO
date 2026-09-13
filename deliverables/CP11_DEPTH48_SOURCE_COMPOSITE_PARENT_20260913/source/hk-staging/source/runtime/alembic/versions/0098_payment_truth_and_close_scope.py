from alembic import op
from go_hotel.db.models import Base

revision='0098_1372d8c45b6f'
down_revision='0097_vertical_source_runtime'
branch_labels=None
depends_on=None

TABLES=['payment_order_fact_binding','finance_scoped_close_batch','finance_scoped_close_line']

def upgrade():
    bind=op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind,checkfirst=True)

    # The payment fact binding is append-only evidence.  Scoped close lines are
    # immutable after creation; close batch state changes only through the
    # governed service so approval can revalidate the live scope first.
    if bind.dialect.name == 'sqlite':
        for table in ('payment_order_fact_binding','finance_scoped_close_line'):
            op.execute(f'''CREATE TRIGGER IF NOT EXISTS trg_{table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_P0_FINANCE_EVIDENCE'); END''')
            op.execute(f'''CREATE TRIGGER IF NOT EXISTS trg_{table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_P0_FINANCE_EVIDENCE'); END''')
    elif bind.dialect.name == 'postgresql':
        op.execute('''CREATE OR REPLACE FUNCTION deny_p0_finance_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_P0_FINANCE_EVIDENCE'; END; $$ LANGUAGE plpgsql''')
        for table in ('payment_order_fact_binding','finance_scoped_close_line'):
            op.execute(f'''CREATE TRIGGER trg_{table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_p0_finance_evidence_mutation()''')
            op.execute(f'''CREATE TRIGGER trg_{table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_p0_finance_evidence_mutation()''')

def downgrade():
    bind=op.get_bind()
    if bind.dialect.name == 'postgresql':
        for table in ('payment_order_fact_binding','finance_scoped_close_line'):
            op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_deny_update ON {table}')
            op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_deny_delete ON {table}')
        op.execute('DROP FUNCTION IF EXISTS deny_p0_finance_evidence_mutation()')
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind,checkfirst=True)
