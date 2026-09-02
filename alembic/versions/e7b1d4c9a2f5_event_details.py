"""event details field

Подробное описание мероприятия (TZ §2.6, §4.3 «Описание: краткое и подробное»,
техдолг «Краткое / подробное описание мероприятия»):
- `event.details` — опциональный развёрнутый текст (программа, что взять, как
  добраться). В анонс не идёт, показывается только на экране мероприятия в Web
  App. Краткая афиша остаётся в `event.description` (лимит понижен на бэкенде).

Revision ID: e7b1d4c9a2f5
Revises: 12fae64ba58e
Create Date: 2026-09-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7b1d4c9a2f5'
down_revision: str | Sequence[str] | None = '12fae64ba58e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('event', sa.Column('details', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('event', 'details')
