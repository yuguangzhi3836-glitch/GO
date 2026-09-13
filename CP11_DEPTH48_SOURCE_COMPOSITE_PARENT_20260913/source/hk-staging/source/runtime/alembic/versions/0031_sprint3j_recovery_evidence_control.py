"""Sprint 3J recovery command ledger, supplier evidence chain and operational control plane
Revision ID: 0031_sprint3j
Revises: 0030_sprint3i
"""
from alembic import op
import sqlalchemy as sa
revision='0031_sprint3j';down_revision='0030_sprint3i';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_command_ledger',
      sa.Column('command_ledger_id',sa.String(64),primary_key=True),sa.Column('execution_id',sa.String(64),nullable=False),sa.Column('execution_item_id',sa.String(64),nullable=False),sa.Column('supplier_operation_id',sa.String(64)),sa.Column('sequence_no',sa.Integer(),nullable=False),sa.Column('command_kind',sa.String(48),nullable=False),sa.Column('actor_type',sa.String(32),nullable=False),sa.Column('actor_id',sa.String(64)),sa.Column('request_id',sa.String(96)),sa.Column('payment_id',sa.String(64)),sa.Column('refund_id',sa.String(64)),sa.Column('supplier_command_id',sa.String(96)),sa.Column('payload_hash',sa.String(64),nullable=False),sa.Column('previous_hash',sa.String(64)),sa.Column('entry_hash',sa.String(64),nullable=False),sa.Column('payload_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('execution_id','execution_item_id','supplier_operation_id','command_kind','actor_id','request_id','payment_id','refund_id','supplier_command_id','entry_hash','created_at'):op.create_index(f'ix_jrcl_{c}','journey_recovery_command_ledger',[c],unique=(c=='entry_hash'))
    op.create_index('uq_jrcl_item_sequence','journey_recovery_command_ledger',['execution_item_id','sequence_no'],unique=True)
    op.create_table('journey_recovery_evidence_chain',
      sa.Column('evidence_chain_id',sa.String(64),primary_key=True),sa.Column('execution_id',sa.String(64),nullable=False),sa.Column('execution_item_id',sa.String(64),nullable=False),sa.Column('supplier_operation_id',sa.String(64)),sa.Column('sequence_no',sa.Integer(),nullable=False),sa.Column('evidence_kind',sa.String(48),nullable=False),sa.Column('source',sa.String(24),nullable=False),sa.Column('external_event_id',sa.String(128)),sa.Column('external_operation_id',sa.String(128)),sa.Column('supplier_confirmation_id',sa.String(128)),sa.Column('observed_status',sa.String(40)),sa.Column('evidence_hash',sa.String(64),nullable=False),sa.Column('previous_hash',sa.String(64)),sa.Column('entry_hash',sa.String(64),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('execution_id','execution_item_id','supplier_operation_id','evidence_kind','source','external_event_id','external_operation_id','supplier_confirmation_id','observed_status','entry_hash','created_at'):op.create_index(f'ix_jrec_{c}','journey_recovery_evidence_chain',[c],unique=(c=='entry_hash'))
    op.create_index('uq_jrec_item_sequence','journey_recovery_evidence_chain',['execution_item_id','sequence_no'],unique=True)
    op.create_table('journey_recovery_operational_case',
      sa.Column('operational_case_id',sa.String(64),primary_key=True),sa.Column('execution_id',sa.String(64),nullable=False),sa.Column('execution_item_id',sa.String(64),nullable=False),sa.Column('supplier_operation_id',sa.String(64)),sa.Column('reconciliation_job_id',sa.String(64)),sa.Column('state',sa.String(32),nullable=False),sa.Column('severity',sa.String(16),nullable=False),sa.Column('assigned_to',sa.String(64)),sa.Column('assignment_note',sa.Text()),sa.Column('manual_review_reason',sa.String(128)),sa.Column('opened_at',sa.DateTime(timezone=True),nullable=False),sa.Column('assigned_at',sa.DateTime(timezone=True)),sa.Column('acknowledged_at',sa.DateTime(timezone=True)),sa.Column('resolved_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('execution_id','execution_item_id','supplier_operation_id','reconciliation_job_id','state','severity','assigned_to','opened_at'):op.create_index(f'ix_jroc_{c}','journey_recovery_operational_case',[c],unique=(c=='execution_item_id'))
    # Append-only evidence. SQLite and PostgreSQL compatible trigger bodies are selected at runtime.
    bind=op.get_bind()
    if bind.dialect.name=='sqlite':
        for table in ('journey_recovery_command_ledger','journey_recovery_evidence_chain'):
            op.execute(sa.text(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END"))
            op.execute(sa.text(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END"))
    elif bind.dialect.name=='postgresql':
        op.execute("CREATE OR REPLACE FUNCTION go_recovery_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'APPEND_ONLY'; END; $$ LANGUAGE plpgsql")
        for table in ('journey_recovery_command_ledger','journey_recovery_evidence_chain'):
            op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION go_recovery_append_only()")

def downgrade():
    bind=op.get_bind()
    if bind.dialect.name=='sqlite':
        for table in ('journey_recovery_command_ledger','journey_recovery_evidence_chain'):
            op.execute(sa.text(f'DROP TRIGGER IF EXISTS {table}_no_update'));op.execute(sa.text(f'DROP TRIGGER IF EXISTS {table}_no_delete'))
    elif bind.dialect.name=='postgresql':
        for table in ('journey_recovery_command_ledger','journey_recovery_evidence_chain'):
            op.execute(f'DROP TRIGGER IF EXISTS {table}_no_update ON {table}')
        op.execute('DROP FUNCTION IF EXISTS go_recovery_append_only()')
    op.drop_table('journey_recovery_operational_case');op.drop_table('journey_recovery_evidence_chain');op.drop_table('journey_recovery_command_ledger')
