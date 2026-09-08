"""user bot_blocked_at field

Пометка «человек заблокировал бота в личке» (TZ §6.2, задача 5.1 «Граничные
случаи»):
- `user.bot_blocked_at` — момент, когда это стало известно (`my_chat_member` →
  `kicked` либо `403 bot was blocked` при отправке). Пока не `null`, worker не
  шлёт этому человеку личные напоминания/эскалации; сбрасывается, как только
  человек снова доступен.

Revision ID: c4d8f2a1b9e6
Revises: e7b1d4c9a2f5
Create Date: 2026-09-08 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d8f2a1b9e6'
down_revision: str | Sequence[str] | None = 'e7b1d4c9a2f5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user', sa.Column('bot_blocked_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user', 'bot_blocked_at')
