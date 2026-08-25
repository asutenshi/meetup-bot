"""membership role: owner

Revision ID: ac3a4e4b9d75
Revises: a407b48ed209
Create Date: 2026-08-25 10:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ac3a4e4b9d75'
down_revision: str | Sequence[str] | None = 'a407b48ed209'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = 'ck_project_membership_membershiprole'


def upgrade() -> None:
    """Upgrade schema."""
    # `op.drop_constraint`/`create_check_constraint` пропускают имя через
    # naming_convention метаданных (см. `db/base.py`) и задваивают префикс
    # `ck_project_membership_` — используем raw SQL с уже готовым именем.
    op.execute(f'ALTER TABLE project_membership DROP CONSTRAINT {_CONSTRAINT_NAME}')
    op.execute(
        f"ALTER TABLE project_membership ADD CONSTRAINT {_CONSTRAINT_NAME} "
        "CHECK (role IN ('owner', 'admin', 'member'))"
    )
    # Главный админ (owner) проекта — тот, кто первым получил роль admin
    # (создатель проекта: добавил бота в чат или первым вызвал
    # /setup_registration). Остальные admin-строки того же проекта остаются
    # обычными со-админами.
    op.execute(
        """
        UPDATE project_membership pm
        SET role = 'owner'
        FROM (
            SELECT DISTINCT ON (project_id) id
            FROM project_membership
            WHERE role = 'admin'
            ORDER BY project_id, registered_at, id
        ) AS first_admin
        WHERE pm.id = first_admin.id
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE project_membership SET role = 'admin' WHERE role = 'owner'")
    op.execute(f'ALTER TABLE project_membership DROP CONSTRAINT {_CONSTRAINT_NAME}')
    op.execute(
        f"ALTER TABLE project_membership ADD CONSTRAINT {_CONSTRAINT_NAME} "
        "CHECK (role IN ('admin', 'member'))"
    )
