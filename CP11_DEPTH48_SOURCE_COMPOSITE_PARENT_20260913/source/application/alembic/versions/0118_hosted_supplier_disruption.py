"""Independent hotel disruption decisions and scoped fault debit mandates."""
from alembic import op
import sqlalchemy as sa
revision='0118_hosted_supplier_disruption'
down_revision='0117_hosted_stay_credit'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('hosted_supplier_disruption',
        sa.Column('case_id',sa.String(64),primary_key=True),
        sa.Column('hosted_reservation_id',sa.String(64),nullable=False,unique=True),
        *[sa.Column(x,sa.String(64),nullable=False) for x in ['hosted_hotel_id','account_id','requester_id','request_hash','evidence_hash']],
        sa.Column('request_json',sa.JSON(),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),
        sa.Column('checker_id',sa.String(64)),sa.Column('state',sa.String(40),nullable=False),
        sa.Column('decision_json',sa.JSON()),sa.Column('decision_hash',sa.String(64)),
        sa.Column('post_stay_case_id',sa.String(64),nullable=False,unique=True),
        sa.Column('refund_eligibility_id',sa.String(64),unique=True),sa.Column('compensation_intent_id',sa.String(64),unique=True),
        *[sa.Column(x,sa.DateTime(timezone=True),nullable=False) for x in ['created_at','updated_at']])
    for field in ['hosted_hotel_id','account_id']:op.create_index('ix_hosted_supplier_disruption_'+field,'hosted_supplier_disruption',[field])
    op.create_table('hosted_fault_debit_mandate',
        sa.Column('mandate_id',sa.String(64),primary_key=True),sa.Column('hosted_hotel_id',sa.String(64),nullable=False),
        sa.Column('currency',sa.String(3),nullable=False),sa.Column('scope',sa.String(64),nullable=False),
        sa.Column('maximum_per_case_minor',sa.BigInteger(),nullable=False),
        sa.Column('authority_reference',sa.String(512),nullable=False),sa.Column('authority_hash',sa.String(64),nullable=False),
        sa.Column('registered_by',sa.String(64),nullable=False),sa.Column('state',sa.String(24),nullable=False),
        sa.Column('deactivated_by',sa.String(64)),sa.Column('deactivated_at',sa.DateTime(timezone=True)),
        *[sa.Column(x,sa.DateTime(timezone=True),nullable=False) for x in ['expires_at','created_at']])
    op.create_index('ix_hosted_fault_debit_mandate_hosted_hotel_id','hosted_fault_debit_mandate',['hosted_hotel_id'])


    op.create_table('hosted_fault_recovery',
        sa.Column('recovery_id',sa.String(64),primary_key=True),sa.Column('hosted_hotel_id',sa.String(64),nullable=False),
        sa.Column('source_reference_hash',sa.String(64),nullable=False,unique=True),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('request_json',sa.JSON(),nullable=False),sa.Column('result_json',sa.JSON(),nullable=False),
        sa.Column('actor_id',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_hosted_fault_recovery_hosted_hotel_id','hosted_fault_recovery',['hosted_hotel_id'])


def downgrade():
    op.drop_table('hosted_fault_recovery');op.drop_table('hosted_fault_debit_mandate');op.drop_table('hosted_supplier_disruption')
