"""project settings all command throttle

Revision ID: a407b48ed209
Revises: 5315a5b9c6d2
Create Date: 2026-08-24 11:46:33.063130

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a407b48ed209'
down_revision: str | Sequence[str] | None = '5315a5b9c6d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'project_settings',
        sa.Column('all_command_throttle_seconds', sa.Integer(), server_default='180', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project_settings', 'all_command_throttle_seconds')
