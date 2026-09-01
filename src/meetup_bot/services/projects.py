import datetime
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole, MembershipStatus, TopicCategory
from meetup_bot.db.models import (
    Project,
    ProjectMembership,
    ProjectSettings,
    ProjectTopicSetting,
    User,
)


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
) -> tuple[Project, bool, bool]:
    """Общий путь создания проекта и первого админа (TZ §3.3, шаг 2) — используется
    и при добавлении бота в группу (`my_chat_member`), и при `/setup_registration`.

    `force_thread_id=True` (только `/setup_registration`) всегда перезаписывает
    `Project.default_thread_id` значением `thread_id` (включая `None`, если команда
    вызвана вне топика) — команду можно вызвать повторно в другом топике, чтобы
    поменять топик по умолчанию. `force_thread_id=False` (`my_chat_member`, где
    топика у апдейта нет в принципе) не должен затирать уже настроенный топик при
    повторном добавлении бота в группу.

    Возвращает `(project, created, thread_changed)` — оба флага говорят вызывающей
    стороне, нужно ли (пере)публиковать закреплённый пост регистрации (TZ §3.3,
    шаг 3): при создании проекта или при смене топика по умолчанию."""
    project, created = await get_or_create_project(session, tg_chat_id=tg_chat_id, name=chat_name)
    previous_thread_id = project.default_thread_id
    if force_thread_id or thread_id is not None:
        project.default_thread_id = thread_id
    thread_changed = project.default_thread_id != previous_thread_id

    user = await get_or_create_user(
        session,
        tg_user_id=admin_tg_user_id,
        username=admin_username,
        first_name=admin_first_name,
        last_name=admin_last_name,
    )
    # Роль назначается только при создании проекта — тот, кто добавил бота в
    # чат/первым вызвал /setup_registration, становится главным админом
    # (`owner`), которого нельзя удалить и который единственный может назначать
    # со-админов (`/add_admin`). При повторных вызовах на уже существующем
    # проекте роль не имеет значения — `ensure_membership` не переопределяет её
    # для уже активного членства.
    role = MembershipRole.OWNER if created else MembershipRole.ADMIN
    await ensure_membership(session, project_id=project.id, user_id=user.id, role=role)
    return project, created, thread_changed


async def ensure_membership(
    session: AsyncSession, *, project_id: int, user_id: int, role: MembershipRole
) -> tuple[ProjectMembership, bool]:
    """Идемпотентно создаёт `ProjectMembership`, если для пары (project, user) её ещё
    нет. Существующее активное членство не переопределяет роль/статус — только
    явные админ-команды. Существующее удалённое (`status=removed`) членство,
    напротив, реактивируется: участник, вышедший/удалённый из проекта, должен
    иметь возможность зарегистрироваться заново по инвайт-ссылке (TZ §4.1), а не
    получать «вы уже зарегистрированы». Роль при этом всегда берётся из
    аргумента `role`, а не сохраняется прежняя — вернувшийся участник не должен
    автоматически получать обратно права, которых лишился при удалении.
    Возвращает `(membership, created)` — вызывающая сторона по этому флагу
    отличает первую/повторную регистрацию от уже активного членства."""
    membership = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
    )
    if membership is not None:
        if membership.status == MembershipStatus.REMOVED:
            membership.status = MembershipStatus.ACTIVE
            membership.role = role
            membership.removed_at = None
            membership.removed_by = None
            return membership, True
        return membership, False

    membership = ProjectMembership(project_id=project_id, user_id=user_id, role=role)
    session.add(membership)
    await session.flush()
    return membership, True


async def get_or_create_project_settings(
    session: AsyncSession, *, project_id: int
) -> ProjectSettings:
    """Возвращает `ProjectSettings` проекта, создавая строку с дефолтами, если её
    почему-то нет (обычно она создаётся вместе с проектом в
    [[get_or_create_project]]). Нужно `/settings` (задача 4.5), чтобы админ мог
    менять пороги напоминаний/эскалации, час рассылки и таймзону, не заходя в БД."""
    settings = await session.get(ProjectSettings, project_id)
    if settings is None:
        settings = ProjectSettings(project_id=project_id)
        session.add(settings)
        await session.flush()
    return settings


async def is_project_admin(session: AsyncSession, *, project_id: int, tg_user_id: int) -> bool:
    """Проверяет, что `tg_user_id` — активный админ проекта, `owner` или `admin`
    (TZ §6.1 "права ролей"). Используется там, где действие (например,
    `/setup_registration`, `/members`, `/remove_member`) должно быть доступно
    любому администратору, а не только главному (см. [[is_project_owner]] для
    действий, зарезервированных за главным админом)."""
    membership = await session.scalar(
        select(ProjectMembership)
        .join(User, User.id == ProjectMembership.user_id)
        .where(
            ProjectMembership.project_id == project_id,
            User.tg_user_id == tg_user_id,
            ProjectMembership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
            ProjectMembership.status == MembershipStatus.ACTIVE,
        )
    )
    return membership is not None


async def set_project_topic(
    session: AsyncSession, *, project_id: int, category: TopicCategory, thread_id: int
) -> tuple[ProjectTopicSetting, bool]:
    """Upsert `ProjectTopicSetting(project_id, category, thread_id)` — `/set_topic`
    (TZ §3.5 "Настройка топика админом"). Возвращает `(setting, changed)` —
    `changed=False`, если этот топик уже был назначен этой категории (повторный
    вызов `/set_topic` в том же топике — идемпотентный no-op)."""
    setting = await session.scalar(
        select(ProjectTopicSetting).where(
            ProjectTopicSetting.project_id == project_id,
            ProjectTopicSetting.category == category,
        )
    )
    if setting is None:
        setting = ProjectTopicSetting(
            project_id=project_id, category=category, thread_id=thread_id
        )
        session.add(setting)
        await session.flush()
        return setting, True

    if setting.thread_id == thread_id:
        return setting, False

    setting.thread_id = thread_id
    await session.flush()
    return setting, True


async def unset_project_topic(
    session: AsyncSession, *, project_id: int, category: TopicCategory
) -> bool:
    """Удаляет строку `ProjectTopicSetting(project_id, category)` — `/unset_topic`
    (TZ §3.5 "Снятие привязки"). Возвращает `True`, если строка была и удалена,
    `False`, если привязки и так не было (idempotent no-op). В отличие от
    `set_project_topic`, не требует вызова из конкретного топика — категория
    известна, физическое присутствие не нужно."""
    setting = await session.scalar(
        select(ProjectTopicSetting).where(
            ProjectTopicSetting.project_id == project_id,
            ProjectTopicSetting.category == category,
        )
    )
    if setting is None:
        return False

    await session.delete(setting)
    await session.flush()
    return True


async def resolve_thread_id(
    session: AsyncSession, *, project_id: int, category: TopicCategory
) -> int | None:
    """Резолвит `thread_id` для проактивного группового сообщения категории
    `category` (TZ §3.5 "Разрешение топика при отправке"): специфичная настройка
    `ProjectTopicSetting` → `Project.default_thread_id` → `None` (сообщение уйдёт
    в топик чата по умолчанию, без `message_thread_id`)."""
    setting = await session.scalar(
        select(ProjectTopicSetting).where(
            ProjectTopicSetting.project_id == project_id,
            ProjectTopicSetting.category == category,
        )
    )
    if setting is not None:
        return setting.thread_id

    project = await session.get(Project, project_id)
    return project.default_thread_id if project is not None else None


async def is_rights_gate_satisfied(
    session: AsyncSession,
    *,
    project_id: int,
    chat_is_forum: bool,
    message_thread_id: int | None,
) -> bool:
    """Гейт admin-команд, меняющих права/состав проекта (`/members`,
    `/remove_member`, `/add_admin`, `/remove_admin` — TZ §3.7): они разрешены
    только из топика, назначенного категории `rights`.

    Fallback (возвращает `True`, гейт не действует):
    - чат без топиков (`chat_is_forum=False`) — топик `rights` там существовать
      не может, гейтить нечем;
    - для проекта нет строки `ProjectTopicSetting(category=rights)` — новый
      проект или топик отвязали через `/unset_topic rights`; работает как до
      введения фичи, чистая ролевая проверка.

    Иначе — команда должна быть вызвана из назначенного топика
    (`message_thread_id` совпадает с `thread_id` строки `rights`)."""
    if not chat_is_forum:
        return True

    setting = await session.scalar(
        select(ProjectTopicSetting).where(
            ProjectTopicSetting.project_id == project_id,
            ProjectTopicSetting.category == TopicCategory.RIGHTS,
        )
    )
    if setting is None:
        return True

    return message_thread_id == setting.thread_id


async def is_project_owner(session: AsyncSession, *, project_id: int, tg_user_id: int) -> bool:
    """Проверяет, что `tg_user_id` — активный главный админ (`owner`) проекта.
    Со-админы (`admin`), назначенные через `/add_admin`, не проходят эту проверку —
    ей гейтится `/add_admin` (только владелец назначает новых админов) и защита
    владельца от удаления через `/remove_member`."""
    membership = await session.scalar(
        select(ProjectMembership)
        .join(User, User.id == ProjectMembership.user_id)
        .where(
            ProjectMembership.project_id == project_id,
            User.tg_user_id == tg_user_id,
            ProjectMembership.role == MembershipRole.OWNER,
            ProjectMembership.status == MembershipStatus.ACTIVE,
        )
    )
    return membership is not None


async def is_active_member(session: AsyncSession, *, project_id: int, tg_user_id: int) -> bool:
    """Проверяет, что `tg_user_id` — активный участник проекта (любая роль). Нужно
    командам из лички, доступным всем участникам (`/new_event` и т.п., TZ §3.8),
    и повторной сверке контекста при клике по инлайн-кнопке выбора проекта."""
    membership = await session.scalar(
        select(ProjectMembership)
        .join(User, User.id == ProjectMembership.user_id)
        .where(
            ProjectMembership.project_id == project_id,
            User.tg_user_id == tg_user_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
        )
    )
    return membership is not None


async def list_user_active_projects(
    session: AsyncSession, *, tg_user_id: int
) -> list[Project]:
    """Активные проекты, где `tg_user_id` — активный участник (любая роль),
    упорядоченные по имени. Используется командами из приватного чата, где
    контекст проекта выбирает сам пользователь: при одном проекте бот сразу
    отдаёт `web_app`-кнопку, при нескольких — сперва инлайн-выбор (TZ §3.8, §4.3)."""
    result = await session.scalars(
        select(Project)
        .join(ProjectMembership, ProjectMembership.project_id == Project.id)
        .join(User, User.id == ProjectMembership.user_id)
        .where(
            User.tg_user_id == tg_user_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
            Project.is_active.is_(True),
        )
        .order_by(Project.name)
    )
    return list(result)


async def list_user_projects_with_role(
    session: AsyncSession, *, tg_user_id: int
) -> list[tuple[Project, MembershipRole]]:
    """Активные проекты участника вместе с его ролью в каждом, по имени проекта.
    Нужно домашнему экрану-хабу Web App (`GET /api/home`, задача 2.9.1): он
    показывает секцию на каждый проект и роль пользователя в ней."""
    result = await session.execute(
        select(Project, ProjectMembership.role)
        .join(ProjectMembership, ProjectMembership.project_id == Project.id)
        .join(User, User.id == ProjectMembership.user_id)
        .where(
            User.tg_user_id == tg_user_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
            Project.is_active.is_(True),
        )
        .order_by(Project.name, Project.id)
    )
    return [(row.Project, row.role) for row in result]


async def list_active_memberships(
    session: AsyncSession, *, project_id: int, role: MembershipRole | None = None
) -> list[tuple[ProjectMembership, User]]:
    """Активные участники проекта вместе с их `User` (TZ §4.1 `/members`,
    `/remove_member`, `/add_admin`). `role` фильтрует по роли — используется
    `/add_admin`, которому нужны только ещё-не-админы."""
    query = (
        select(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
        )
        .order_by(User.first_name)
    )
    if role is not None:
        query = query.where(ProjectMembership.role == role)
    result = await session.execute(query)
    return [(row.ProjectMembership, row.User) for row in result]


async def remove_membership(
    session: AsyncSession, *, membership: ProjectMembership, removed_by_tg_user_id: int
) -> None:
    """Удаляет участника из проекта (TZ §4.1 `/remove_member`): статус переводится
    в `removed`, `removed_by`/`removed_at` заполняются — строка не удаляется физически."""
    removed_by = await session.scalar(select(User).where(User.tg_user_id == removed_by_tg_user_id))
    membership.status = MembershipStatus.REMOVED
    membership.removed_at = datetime.datetime.now(datetime.UTC)
    membership.removed_by = removed_by.id if removed_by else None


def promote_to_admin(membership: ProjectMembership) -> None:
    """Назначает участника со-админом проекта (TZ §4.1 `/add_admin`)."""
    membership.role = MembershipRole.ADMIN


def demote_to_member(membership: ProjectMembership) -> None:
    """Понижает со-админа обратно до обычного участника (TZ §4.1 `/remove_admin`) —
    обратная операция к `promote_to_admin`. Участник остаётся в проекте, снимаются
    только права. Владельца (`owner`) это не касается — он не попадает в список
    кандидатов `/remove_admin`."""
    membership.role = MembershipRole.MEMBER
