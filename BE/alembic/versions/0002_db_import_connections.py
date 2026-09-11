"""db_import_connections

Revision ID: 0002_db_import_connections
Revises: 0001_initial
Create Date: 2026-07-10

Adds the (opt-in only) persistent-connection store for the Database Import
feature — see app/modules/db_import/models.py:DbConnection and
app/core/credential_crypto.py. The default one-time-import mode never
writes to this table at all. Also adds db_import_connectors, the Local
Connector registration/auth table (app/modules/db_import/models.py:
ConnectorRegistration) — backend API surface only, ahead of the packaged
connector application itself.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002_db_import_connections'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('db_import_connections',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('engine', sa.String(length=40), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('database', sa.String(length=255), nullable=True),
    sa.Column('username', sa.String(length=255), nullable=False),
    sa.Column('ssl', sa.Boolean(), nullable=False),
    sa.Column('encrypted_password', sa.LargeBinary(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_db_import_connections_tenant_id'), 'db_import_connections', ['tenant_id'], unique=False)

    op.create_table('db_import_connectors',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('registration_key_hash', sa.String(length=64), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('registered_at', sa.DateTime(), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_db_import_connectors_tenant_id'), 'db_import_connectors', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_db_import_connectors_token_hash'), 'db_import_connectors', ['token_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_db_import_connectors_token_hash'), table_name='db_import_connectors')
    op.drop_index(op.f('ix_db_import_connectors_tenant_id'), table_name='db_import_connectors')
    op.drop_table('db_import_connectors')
    op.drop_index(op.f('ix_db_import_connections_tenant_id'), table_name='db_import_connections')
    op.drop_table('db_import_connections')
