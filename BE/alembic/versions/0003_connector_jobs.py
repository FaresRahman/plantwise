"""connector_jobs

Revision ID: 0003_connector_jobs
Revises: 0002_db_import_connections
Create Date: 2026-07-10

Adds db_import_connector_jobs — the job relay a Local Connector polls for
work through (see app/modules/db_import/models.py:ConnectorJob). Params
never carry database credentials, only action-specific arguments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003_connector_jobs'
down_revision: Union[str, None] = '0002_db_import_connections'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('db_import_connector_jobs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('connector_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['connector_id'], ['db_import_connectors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_db_import_connector_jobs_connector_id'), 'db_import_connector_jobs', ['connector_id'], unique=False)
    op.create_index(op.f('ix_db_import_connector_jobs_tenant_id'), 'db_import_connector_jobs', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_db_import_connector_jobs_tenant_id'), table_name='db_import_connector_jobs')
    op.drop_index(op.f('ix_db_import_connector_jobs_connector_id'), table_name='db_import_connector_jobs')
    op.drop_table('db_import_connector_jobs')
