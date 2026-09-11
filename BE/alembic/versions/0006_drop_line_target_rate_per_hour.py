"""drop_line_target_rate_per_hour

Revision ID: 0006_drop_target_rate
Revises: 0005_sync_schedules
Create Date: 2026-07-16

Drops lines.target_rate_per_hour — collected on every add-line form/CSV
import but never consumed by any calculation or display. The one function
that read it (engine.compute_oee_trend, an "actual vs plan" trend at
selectable granularity) had no frontend caller; the dashboard's actual
production-target chart is built on shift_target_units instead, which maps
cleanly onto compute_oee_history's fixed daily buckets without needing a
separate rate field.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0006_drop_target_rate'
down_revision: Union[str, None] = '0005_sync_schedules'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('lines', 'target_rate_per_hour')


def downgrade() -> None:
    op.add_column('lines', sa.Column('target_rate_per_hour', sa.Float(), nullable=False, server_default='0'))
