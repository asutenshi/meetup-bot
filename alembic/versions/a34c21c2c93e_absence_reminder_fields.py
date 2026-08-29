"""absence reminder fields

Поля для джобы личного напоминания «давно не виделись» (TZ §3.4 п.2, задача 4.3):
- `project_settings.reminder_send_hour` — час локального времени проекта, в который
  worker рассылает напоминания/эскалации (TZ §2.3);
- `project_membership.last_reminder_sent_at` — троттлинг: не чаще одного напоминания
  в день на участника.

Revision ID: a34c21c2c93e
Revises: 129c67986763
Create Date: 2026-08-29 08:44:33.019106

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a34c21c2c93e'
down_revision: str | Sequence[str] | None = '129c67986763'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'project_settings',
        sa.Column('reminder_send_hour', sa.Integer(), server_default='20', nullable=False),
    )
    op.add_column(
        'project_membership',
        sa.Column('last_reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project_membership', 'last_reminder_sent_at')
    op.drop_column('project_settings', 'reminder_send_hour')
