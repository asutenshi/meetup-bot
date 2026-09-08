"""event row_version for optimistic locking

Оптимистичная блокировка одновременного редактирования мероприятия
(TZ §4.3 «Редактирование/отмена», задача 5.1 «Граничные случаи», п. 5.1d):
- `event.row_version` — целочисленная версия строки. SQLAlchemy инкрементит её
  при каждом flush изменений `Event` (`version_id_col`) и добавляет прежнее
  значение в `WHERE` соответствующего `UPDATE`. Форма редактирования получает
  версию в `GET /api/events/{id}` и возвращает в `PUT /api/events/{id}`;
  рассинхрон → `409 event_modified_concurrently` (второй со-организатор молча не
  затирает правки первого).

Revision ID: f2a5c8d1e3b7
Revises: c4d8f2a1b9e6
Create Date: 2026-09-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2a5c8d1e3b7'
down_revision: str | Sequence[str] | None = 'c4d8f2a1b9e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'event',
        sa.Column('row_version', sa.Integer(), server_default='1', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('event', 'row_version')
