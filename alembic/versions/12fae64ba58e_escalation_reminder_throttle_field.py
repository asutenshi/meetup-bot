"""escalation reminder throttle field

Поле для джобы эскалации организатору/админу (TZ §3.4 п.3, задача 4.4):
- `project_membership.last_escalation_sent_at` — троттлинг: не чаще одной
  эскалации в неделю на пару участник—проект (по аналогии с
  `last_reminder_sent_at` из `a34c21c2c93e`).

Revision ID: 12fae64ba58e
Revises: a34c21c2c93e
Create Date: 2026-08-29 09:32:00.464067

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '12fae64ba58e'
down_revision: str | Sequence[str] | None = 'a34c21c2c93e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'project_membership',
        sa.Column('last_escalation_sent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project_membership', 'last_escalation_sent_at')
