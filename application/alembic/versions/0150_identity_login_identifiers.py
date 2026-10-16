"""Three-in-one login: give ``identity_user`` its own email and phone columns.

Before this migration the only login identifier was ``identity_user.username``,
and the supplier sign-up path stored the applicant's email address *in* it
(frozen decision D-01). The platform now accepts **username OR email OR phone**,
all bound to the same account, so email and phone need their own columns.

``username`` is deliberately left untouched. Every pre-existing row whose
username is an email address gets that address back-filled into ``email``, so
those accounts keep logging in exactly as before; rows that never had an email
(the bootstrap ``go_admin`` / ``supplier_owner`` handles) keep ``email = NULL``
and simply cannot be used to log in by email.

Both columns are nullable and uniquely indexed. PostgreSQL, SQLite and MySQL all
tolerate any number of NULLs in a unique index, so accounts without a phone do
not collide with each other.
"""
from alembic import op
import sqlalchemy as sa

revision = '0150_identity_login_identifiers'
down_revision = '0149_hotel_search_indexes'
branch_labels = None
depends_on = None

TABLE = 'identity_user'
COLUMNS = (
    ('email', sa.String(length=255)),
    ('phone', sa.String(length=32)),
)


def _existing_columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        return
    existing = _existing_columns(bind)
    for name, type_ in COLUMNS:
        if name not in existing:
            op.add_column(TABLE, sa.Column(name, type_, nullable=True))
    # IF NOT EXISTS covers a database where the model already created the index
    # (the SQLite correctness fixture builds the schema from Base.metadata).
    for name, _ in COLUMNS:
        op.execute(sa.text(f'CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE}_{name} ON {TABLE} ({name})'))
    # The supplier sign-up path used to write the email address into username.
    op.execute(sa.text(f"UPDATE {TABLE} SET email = username WHERE email IS NULL AND username LIKE '%@%.%'"))


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        return
    for name, _ in COLUMNS:
        op.execute(sa.text(f'DROP INDEX IF EXISTS uq_{TABLE}_{name}'))
    existing = _existing_columns(bind)
    for name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
