import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import Project, ProjectMembership, ProjectSettings, User


async def get_or_create_project(
    session: AsyncSession, *, tg_chat_id: int, name: str
) -> tuple[Project, bool]:
    """Возвращает `Project` для `tg_chat_id`, создавая его вместе с `ProjectSettings`
    по умолчанию, если ещё не существует (TZ §3.3, шаг 2)."""
    project = await session.scalar(select(Project).where(Project.tg_chat_id == tg_chat_id))
    if project is not None:
        return project, False

    project = Project(
        tg_chat_id=tg_chat_id,
        name=name,
        invite_payload=secrets.token_urlsafe(16),
    )
    session.add(project)
    await session.flush()
    session.add(ProjectSettings(project_id=project.id))
    return project, True


async def get_or_create_user(
    session: AsyncSession,
    *,
    tg_user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None,
) -> User:
    user = await session.scalar(select(User).where(User.tg_user_id == tg_user_id))
    if user is not None:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        return user

    user = User(
        tg_user_id=tg_user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )
    session.add(user)
    await session.flush()
    return user


async def provision_project(
    session: AsyncSession,
    *,
    tg_chat_id: int,
    chat_name: str,
    thread_id: int | None,
    force_thread_id: bool,
    admin_tg_user_id: int,
    admin_username: str | None,
    admin_first_name: str,
    admin_last_name: str | None,
) -> Project:
    """Общий путь создания проекта и первого админа (TZ §3.3, шаг 2) — используется
    и при добавлении бота в группу (`my_chat_member`), и при `/setup_registration`.

    `force_thread_id=True` (только `/setup_registration`) всегда перезаписывает
    `Project.default_thread_id` значением `thread_id` (включая `None`, если команда
    вызвана вне топика) — команду можно вызвать повторно в другом топике, чтобы
    поменять топик по умолчанию. `force_thread_id=False` (`my_chat_member`, где
    топика у апдейта нет в принципе) не должен затирать уже настроенный топик при
    повторном добавлении бота в группу."""
    project, _ = await get_or_create_project(session, tg_chat_id=tg_chat_id, name=chat_name)
    if force_thread_id or thread_id is not None:
        project.default_thread_id = thread_id

    user = await get_or_create_user(
        session,
        tg_user_id=admin_tg_user_id,
        username=admin_username,
        first_name=admin_first_name,
        last_name=admin_last_name,
    )
    await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
    )
    return project


async def ensure_membership(
    session: AsyncSession, *, project_id: int, user_id: int, role: MembershipRole
) -> ProjectMembership:
    """Идемпотентно создаёт `ProjectMembership`, если для пары (project, user) её ещё
    нет. Существующее членство не переопределяет роль/статус — только явные
    админ-команды."""
    membership = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
    )
    if membership is not None:
        return membership

    membership = ProjectMembership(project_id=project_id, user_id=user_id, role=role)
    session.add(membership)
    await session.flush()
    return membership
