"""sync_schedules

Revision ID: 0005_sync_schedules
Revises: 0004_failure_case_signatures
Create Date: 2026-07-13

Adds db_import_sync_schedules — a saved source-table -> target-entity mapping
re-run on a timer instead of once by hand, for either a Cloud DB Import
connection or a Local Connector. See app/modules/db_import/service.py:run_sync.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005_sync_schedules'
down_revision: Union[str, None] = '0004_failure_case_signatures'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('db_import_sync_schedules',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('connection_id', sa.Integer(), nullable=True),
    sa.Column('connector_id', sa.Integer(), nullable=True),
    sa.Column('entity', sa.String(length=40), nullable=False),
    sa.Column('schema_name', sa.String(length=120), nullable=True),
    sa.Column('table_name', sa.String(length=255), nullable=False),
    sa.Column('column_mapping', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('watermark_column', sa.String(length=255), nullable=False),
    sa.Column('last_watermark_value', sa.Text(), nullable=True),
    sa.Column('interval_minutes', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_synced_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=20), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['db_import_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['connector_id'], ['db_import_connectors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_db_import_sync_schedules_tenant_id'), 'db_import_sync_schedules', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_db_import_sync_schedules_tenant_id'), table_name='db_import_sync_schedules')
    op.drop_table('db_import_sync_schedules')
