"""quality_hold_release_note

Revision ID: 0007_hold_release_note
Revises: 0006_drop_target_rate
Create Date: 2026-07-17

Adds quality_holds.release_note — a hold needs a reason to open, so it now
needs one to close too (enforced in service.release_hold), otherwise a lot
could be cleared to ship with no record of why it was safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0007_hold_release_note'
down_revision: Union[str, None] = '0006_drop_target_rate'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_holds', sa.Column('release_note', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('quality_holds', 'release_note')
