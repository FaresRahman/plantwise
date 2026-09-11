"""failure_case_signatures

Revision ID: 0004_failure_case_signatures
Revises: 0003_connector_jobs
Create Date: 2026-07-13

Adds pm_failure_case_signatures — one monitored metric's pre-failure trend,
captured automatically whenever a corrective MaintenanceHistory row commits.
Backs the historical pattern-matching predictive-maintenance check (see
app/modules/predictive_maintenance/engine.py:_check_historical_pattern_match).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004_failure_case_signatures'
down_revision: Union[str, None] = '0003_connector_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('pm_failure_case_signatures',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('maintenance_history_id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.String(length=100), nullable=False),
    sa.Column('slope', sa.Float(), nullable=False),
    sa.Column('start_value', sa.Float(), nullable=False),
    sa.Column('end_value', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(length=50), nullable=False),
    sa.Column('days_span', sa.Float(), nullable=False),
    sa.Column('captured_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['pm_assets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['maintenance_history_id'], ['pm_maintenance_history.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pm_failure_case_signatures_tenant_id'), 'pm_failure_case_signatures', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_pm_failure_case_signatures_asset_id'), 'pm_failure_case_signatures', ['asset_id'], unique=False)
    op.create_index('ix_pm_failure_signatures_asset_metric', 'pm_failure_case_signatures', ['asset_id', 'metric'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_pm_failure_signatures_asset_metric', table_name='pm_failure_case_signatures')
    op.drop_index(op.f('ix_pm_failure_case_signatures_asset_id'), table_name='pm_failure_case_signatures')
    op.drop_index(op.f('ix_pm_failure_case_signatures_tenant_id'), table_name='pm_failure_case_signatures')
    op.drop_table('pm_failure_case_signatures')
