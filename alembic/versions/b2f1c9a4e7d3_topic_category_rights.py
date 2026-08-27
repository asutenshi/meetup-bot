"""topic category: rights

Revision ID: b2f1c9a4e7d3
Revises: ac3a4e4b9d75
Create Date: 2026-08-27 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2f1c9a4e7d3'
down_revision: str | Sequence[str] | None = 'ac3a4e4b9d75'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = 'ck_project_topic_setting_topiccategory'


def upgrade() -> None:
    """Upgrade schema."""
    # Новая категория `rights` — топик регулирования прав (TZ §3.7). Как и с
    # ролью `owner` (миграция ac3a4e4b9d75), `op.drop_constraint`/
    # `create_check_constraint` задваивают префикс `ck_project_topic_setting_`
    # через naming_convention — используем raw SQL с готовым именем.
    op.execute(f'ALTER TABLE project_topic_setting DROP CONSTRAINT {_CONSTRAINT_NAME}')
    op.execute(
        f"ALTER TABLE project_topic_setting ADD CONSTRAINT {_CONSTRAINT_NAME} "
        "CHECK (category IN ('events', 'money_collections', 'general', 'rights'))"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM project_topic_setting WHERE category = 'rights'")
    op.execute(f'ALTER TABLE project_topic_setting DROP CONSTRAINT {_CONSTRAINT_NAME}')
    op.execute(
        f"ALTER TABLE project_topic_setting ADD CONSTRAINT {_CONSTRAINT_NAME} "
        "CHECK (category IN ('events', 'money_collections', 'general'))"
    )
