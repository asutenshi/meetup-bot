from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import ProjectSettings
from meetup_bot.services.projects import (
    ensure_membership,
    get_or_create_project,
    get_or_create_user,
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
