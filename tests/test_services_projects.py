from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import ProjectSettings
from meetup_bot.services.projects import (
    ensure_membership,
    get_or_create_project,
    get_or_create_user,
    is_project_admin,
    provision_project,
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

    first = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )
    await session.commit()
    second = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )

    assert first.id == second.id
    assert second.role == MembershipRole.ADMIN


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


async def test_provision_project_creates_admin_membership(session: AsyncSession) -> None:
    project, _, _ = await provision_project(
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

    user = await get_or_create_user(
        session, tg_user_id=1, username="admin", first_name="Admin", last_name=None
    )
    membership = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )

    assert membership.role == MembershipRole.ADMIN


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
