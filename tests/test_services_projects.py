from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole, MembershipStatus
from meetup_bot.db.models import ProjectMembership, ProjectSettings
from meetup_bot.services.projects import (
    ensure_membership,
    get_or_create_project,
    get_or_create_user,
    is_project_admin,
    is_project_owner,
    provision_project,
    remove_membership,
)


async def test_get_or_create_project_creates_settings(session: AsyncSession) -> None:
    project, created = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    await session.commit()

    settings = await session.scalar(
        select(ProjectSettings).where(ProjectSettings.project_id == project.id)
    )

    assert created is True
    assert project.tg_chat_id == -100
    assert project.invite_payload
    assert settings is not None
    assert settings.reminder_days_threshold == 14


async def test_get_or_create_project_is_idempotent(session: AsyncSession) -> None:
    first, first_created = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    await session.commit()

    second, second_created = await get_or_create_project(session, tg_chat_id=-100, name="Friends")

    assert first_created is True
    assert second_created is False
    assert second.id == first.id


async def test_get_or_create_user_updates_profile_fields(session: AsyncSession) -> None:
    first = await get_or_create_user(
        session, tg_user_id=1, username="old", first_name="Old", last_name=None
    )
    await session.commit()

    second = await get_or_create_user(
        session, tg_user_id=1, username="new", first_name="New", last_name="Name"
    )

    assert second.id == first.id
    assert second.username == "new"
    assert second.first_name == "New"
    assert second.last_name == "Name"


async def test_ensure_membership_is_idempotent(session: AsyncSession) -> None:
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    user = await get_or_create_user(
        session, tg_user_id=1, username="admin", first_name="Admin", last_name=None
    )
    await session.commit()

    first, first_created = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )
    await session.commit()
    second, second_created = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )

    assert first.id == second.id
    assert second.role == MembershipRole.ADMIN
    assert first_created is True
    assert second_created is False


async def test_provision_project_without_force_keeps_existing_thread_id(
    session: AsyncSession,
) -> None:
    project, created, thread_changed = await provision_project(
        session,
        tg_chat_id=-100,
        chat_name="Friends",
        thread_id=42,
        force_thread_id=True,
        admin_tg_user_id=1,
        admin_username="admin",
        admin_first_name="Admin",
        admin_last_name=None,
    )
    await session.commit()
    assert project.default_thread_id == 42
    assert created is True
    assert thread_changed is True

    project, created, thread_changed = await provision_project(
        session,
        tg_chat_id=-100,
        chat_name="Friends",
        thread_id=None,
        force_thread_id=False,
        admin_tg_user_id=1,
        admin_username="admin",
        admin_first_name="Admin",
        admin_last_name=None,
    )

    assert project.default_thread_id == 42
    assert created is False
    assert thread_changed is False


async def test_provision_project_with_force_overwrites_thread_id(session: AsyncSession) -> None:
    project, _, _ = await provision_project(
        session,
        tg_chat_id=-100,
        chat_name="Friends",
        thread_id=42,
        force_thread_id=True,
        admin_tg_user_id=1,
        admin_username="admin",
        admin_first_name="Admin",
        admin_last_name=None,
    )
    await session.commit()
    assert project.default_thread_id == 42

    project, created, thread_changed = await provision_project(
        session,
        tg_chat_id=-100,
        chat_name="Friends",
        thread_id=None,
        force_thread_id=True,
        admin_tg_user_id=1,
        admin_username="admin",
        admin_first_name="Admin",
        admin_last_name=None,
    )

    assert project.default_thread_id is None
    assert created is False
    assert thread_changed is True


async def test_provision_project_creates_owner_membership(session: AsyncSession) -> None:
    """Тот, кто добавил бота в чат / первым вызвал /setup_registration, становится
    главным админом проекта (`owner`), а не рядовым `admin` (защита владельца от
    удаления и монополия на `/add_admin` — см. `admin_commands.py`)."""
    project, created, _ = await provision_project(
        session,
        tg_chat_id=-100,
        chat_name="Friends",
        thread_id=None,
        force_thread_id=False,
        admin_tg_user_id=1,
        admin_username="admin",
        admin_first_name="Admin",
        admin_last_name=None,
    )
    await session.commit()
    assert created is True

    user = await get_or_create_user(
        session, tg_user_id=1, username="admin", first_name="Admin", last_name=None
    )
    membership = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
        )
    )

    assert membership is not None
    assert membership.role == MembershipRole.OWNER


async def test_is_project_admin_true_for_active_admin(session: AsyncSession) -> None:
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    user = await get_or_create_user(
        session, tg_user_id=1, username="admin", first_name="Admin", last_name=None
    )
    await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )
    await session.commit()

    assert await is_project_admin(session, project_id=project.id, tg_user_id=1) is True


async def test_is_project_admin_false_for_member(session: AsyncSession) -> None:
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    user = await get_or_create_user(
        session, tg_user_id=2, username="member", first_name="Member", last_name=None
    )
    await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.MEMBER
    )
    await session.commit()

    assert await is_project_admin(session, project_id=project.id, tg_user_id=2) is False


async def test_is_project_admin_false_for_unknown_user(session: AsyncSession) -> None:
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    await session.commit()

    assert await is_project_admin(session, project_id=project.id, tg_user_id=999) is False


async def test_is_project_admin_true_for_owner(session: AsyncSession) -> None:
    """`owner` — тоже полноценный админ для команд вроде `/members`,
    `/remove_member`, `/setup_registration` (не только для owner-специфичных)."""
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    user = await get_or_create_user(
        session, tg_user_id=1, username="owner", first_name="Owner", last_name=None
    )
    await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.OWNER
    )
    await session.commit()

    assert await is_project_admin(session, project_id=project.id, tg_user_id=1) is True


async def test_is_project_owner_true_only_for_owner(session: AsyncSession) -> None:
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    owner = await get_or_create_user(
        session, tg_user_id=1, username="owner", first_name="Owner", last_name=None
    )
    co_admin = await get_or_create_user(
        session, tg_user_id=2, username="admin", first_name="Admin", last_name=None
    )
    await ensure_membership(
        session, project_id=project.id, user_id=owner.id, role=MembershipRole.OWNER
    )
    await ensure_membership(
        session, project_id=project.id, user_id=co_admin.id, role=MembershipRole.ADMIN
    )
    await session.commit()

    assert await is_project_owner(session, project_id=project.id, tg_user_id=1) is True
    # Со-админ (не главный) не проходит owner-проверку — ей гейтится
    # `/add_admin` и защита владельца от удаления.
    assert await is_project_owner(session, project_id=project.id, tg_user_id=2) is False


async def test_ensure_membership_reactivates_removed_member(session: AsyncSession) -> None:
    """Повторная регистрация после удаления не должна упираться в «уже
    зарегистрированы» — реального бага, который приводил к этому, больше нет:
    удалённое членство реактивируется, а не остаётся заблокированным навсегда."""
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    user = await get_or_create_user(
        session, tg_user_id=1, username="alice", first_name="Alice", last_name=None
    )
    membership, created = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.MEMBER
    )
    await session.commit()
    assert created is True

    admin_user = await get_or_create_user(
        session, tg_user_id=2, username="admin", first_name="Admin", last_name=None
    )
    await remove_membership(session, membership=membership, removed_by_tg_user_id=2)
    await session.commit()
    assert membership.status == MembershipStatus.REMOVED
    assert membership.removed_by == admin_user.id

    reactivated, reactivated_created = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.MEMBER
    )

    assert reactivated.id == membership.id
    assert reactivated_created is True
    assert reactivated.status == MembershipStatus.ACTIVE
    assert reactivated.removed_at is None
    assert reactivated.removed_by is None


async def test_ensure_membership_reactivation_resets_role_to_argument(
    session: AsyncSession,
) -> None:
    """Роль при возврате всегда берётся из аргумента, а не сохраняется прежняя —
    удалённый со-админ, вернувшийся по инвайт-ссылке, регистрируется как
    обычный участник, а не автоматически получает старые права обратно."""
    project, _ = await get_or_create_project(session, tg_chat_id=-100, name="Friends")
    user = await get_or_create_user(
        session, tg_user_id=1, username="admin", first_name="Admin", last_name=None
    )
    membership, _ = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )
    await session.commit()
    await remove_membership(session, membership=membership, removed_by_tg_user_id=1)
    await session.commit()

    reactivated, _ = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.MEMBER
    )

    assert reactivated.role == MembershipRole.MEMBER
