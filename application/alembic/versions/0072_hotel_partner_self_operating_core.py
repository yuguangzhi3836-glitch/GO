"""Hotel Partner Self-Operating Core (Mother Plan Production Build 1).

Revision ID: 0072_partner_core
Revises: 0071_sprint4x
"""
from alembic import op
import sqlalchemy as sa

revision='0072_partner_core'
down_revision='0071_sprint4x'
branch_labels=None
depends_on=None

def _json(): return sa.JSON()
def upgrade():
    op.create_table('hotel_partner_property',
      sa.Column('property_id',sa.String(64),primary_key=True),sa.Column('supplier_id',sa.String(64),nullable=False,index=True),
      sa.Column('name_zh',sa.String(256),nullable=False),sa.Column('name_en',sa.String(256)),sa.Column('property_type',sa.String(48),nullable=False),
      sa.Column('group_name',sa.String(128)),sa.Column('brand_name',sa.String(128)),sa.Column('address_json',_json(),nullable=False),
      sa.Column('latitude',sa.Float()),sa.Column('longitude',sa.Float()),sa.Column('contacts_json',_json(),nullable=False),sa.Column('legal_json',_json(),nullable=False),
      sa.Column('operations_json',_json(),nullable=False),sa.Column('poi_json',_json(),nullable=False),sa.Column('publication_state',sa.String(24),nullable=False,index=True),
      sa.Column('version',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('hotel_partner_change_request',
      sa.Column('change_request_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('field_group',sa.String(48),nullable=False,index=True),
      sa.Column('proposed_value_json',_json(),nullable=False),sa.Column('evidence_json',_json(),nullable=False),sa.Column('state',sa.String(24),nullable=False,index=True),
      sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('reviewed_by',sa.String(64)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('reviewed_at',sa.DateTime(timezone=True)))
    op.create_table('hotel_partner_room_type',
      sa.Column('room_type_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('name_zh',sa.String(256),nullable=False),sa.Column('name_en',sa.String(256)),
      sa.Column('sale_unit',sa.String(24),nullable=False),sa.Column('physical_room_count',sa.Integer(),nullable=False),sa.Column('occupancy_json',_json(),nullable=False),sa.Column('bed_configurations_json',_json(),nullable=False),
      sa.Column('attributes_json',_json(),nullable=False),sa.Column('media_json',_json(),nullable=False),sa.Column('state',sa.String(24),nullable=False,index=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('hotel_partner_sellable_product',
      sa.Column('sellable_product_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('room_type_id',sa.String(64),nullable=False,index=True),
      sa.Column('name',sa.String(256),nullable=False),sa.Column('occupancy_offer_json',_json(),nullable=False),sa.Column('state',sa.String(24),nullable=False,index=True))
    op.create_table('hotel_partner_rate_plan',
      sa.Column('rate_plan_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('sellable_product_id',sa.String(64),nullable=False,index=True),
      sa.Column('name',sa.String(256),nullable=False),sa.Column('payment_type',sa.String(24),nullable=False),sa.Column('meal_plan_json',_json(),nullable=False),sa.Column('cancellation_tiers_json',_json(),nullable=False),
      sa.Column('restrictions_json',_json(),nullable=False),sa.Column('default_ari_json',_json(),nullable=False),sa.Column('state',sa.String(24),nullable=False,index=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('hotel_partner_facility_definition',
      sa.Column('facility_definition_id',sa.String(64),primary_key=True),sa.Column('code',sa.String(96),nullable=False,unique=True),sa.Column('category',sa.String(64),nullable=False,index=True),
      sa.Column('name_zh',sa.String(128),nullable=False),sa.Column('name_en',sa.String(128)),sa.Column('attribute_schema_json',_json(),nullable=False))
    op.create_table('hotel_partner_facility_assignment',
      sa.Column('facility_assignment_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('room_type_id',sa.String(64),index=True),
      sa.Column('facility_definition_id',sa.String(64),nullable=False,index=True),sa.Column('status',sa.String(24),nullable=False),sa.Column('inherited',sa.Boolean(),nullable=False),
      sa.Column('attributes_json',_json(),nullable=False),sa.Column('evidence_json',_json(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
      sa.UniqueConstraint('property_id','room_type_id','facility_definition_id',name='uq_partner_facility_scope'))
    op.create_table('hotel_partner_policy',
      sa.Column('policy_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('policy_type',sa.String(48),nullable=False,index=True),
      sa.Column('rule_json',_json(),nullable=False),sa.Column('effective_from',sa.String(10)),sa.Column('effective_to',sa.String(10)),sa.Column('state',sa.String(24),nullable=False),
      sa.Column('version',sa.Integer(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('hotel_partner_ari_override',
      sa.Column('ari_override_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('room_type_id',sa.String(64),nullable=False,index=True),sa.Column('rate_plan_id',sa.String(64),nullable=False,index=True),
      sa.Column('stay_date',sa.String(10),nullable=False,index=True),sa.Column('sell_status',sa.String(16),nullable=False),sa.Column('inventory_mode',sa.String(16),nullable=False),sa.Column('remaining_rooms',sa.Integer()),
      sa.Column('exhaustion_policy',sa.String(24),nullable=False),sa.Column('inventory_sharing',sa.String(24),nullable=False),sa.Column('price_json',_json(),nullable=False),sa.Column('restrictions_json',_json(),nullable=False),
      sa.Column('override_fields_json',_json(),nullable=False),sa.Column('evidence_json',_json(),nullable=False),sa.Column('updated_by',sa.String(64),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
      sa.UniqueConstraint('rate_plan_id','stay_date',name='uq_partner_ari_rate_date'))
    op.create_table('hotel_partner_operational_inbox',
      sa.Column('inbox_item_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('item_type',sa.String(48),nullable=False,index=True),sa.Column('priority',sa.String(16),nullable=False,index=True),
      sa.Column('sla_due_at',sa.DateTime(timezone=True),index=True),sa.Column('owner_id',sa.String(64),index=True),sa.Column('state',sa.String(24),nullable=False,index=True),sa.Column('subject',sa.String(256),nullable=False),
      sa.Column('payload_json',_json(),nullable=False),sa.Column('evidence_json',_json(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('hotel_partner_go_offer_authority',
      sa.Column('go_offer_authority_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('requirement_type',sa.String(32),nullable=False),
      sa.Column('quote_mode',sa.String(24),nullable=False),sa.Column('authorized_inventory_json',_json(),nullable=False),sa.Column('authorized_rules_json',_json(),nullable=False),sa.Column('packages_json',_json(),nullable=False),
      sa.Column('price_floor_json',_json(),nullable=False),sa.Column('validity_json',_json(),nullable=False),sa.Column('conditions_json',_json(),nullable=False),sa.Column('source_scope',sa.String(32),nullable=False),
      sa.Column('state',sa.String(24),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('property_id','requirement_type',name='uq_partner_offer_authority_type'))
    op.create_table('hotel_partner_audit_event',
      sa.Column('audit_event_id',sa.String(64),primary_key=True),sa.Column('property_id',sa.String(64),nullable=False,index=True),sa.Column('event_type',sa.String(64),nullable=False,index=True),
      sa.Column('aggregate_type',sa.String(48),nullable=False),sa.Column('aggregate_id',sa.String(64),nullable=False,index=True),sa.Column('payload_json',_json(),nullable=False),sa.Column('actor_id',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,index=True))

def downgrade():
    for table in ['hotel_partner_audit_event','hotel_partner_go_offer_authority','hotel_partner_operational_inbox','hotel_partner_ari_override','hotel_partner_policy','hotel_partner_facility_assignment','hotel_partner_facility_definition','hotel_partner_rate_plan','hotel_partner_sellable_product','hotel_partner_room_type','hotel_partner_change_request','hotel_partner_property']:
        op.drop_table(table)
