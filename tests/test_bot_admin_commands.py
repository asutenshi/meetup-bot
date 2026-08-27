from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import MembershipRole, MembershipStatus, TopicCategory
from meetup_bot.db.models import (
    Project,
    ProjectMembership,
    ProjectSettings,
    ProjectTopicSetting,
    User,
)
from tests.conftest import FakeBotApi

_CHAT_ID = -100888
_ADMIN_TG_ID = 100
_ADMIN_USERNAME = "admin_user"


def _command_update(
    command: str,
    update_id: int = 1,
    chat_id: int = _CHAT_ID,
    user_id: int = _ADMIN_TG_ID,
    username: str = _ADMIN_USERNAME,
    first_name: str = "Admin",
    *,
    is_forum: bool = False,
    message_thread_id: int | None = None,
) -> dict:
    chat: dict = {"id": chat_id, "type": "supergroup", "title": "Test Group"}
    if is_forum:
        chat["is_forum"] = True
    message: dict = {
        "message_id": update_id,
        "date": 1700000000,
        "chat": chat,
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": first_name,
            "username": username,
        },
        "text": f"/{command}",
        "entities": [{"type": "bot_command", "offset": 0, "length": len(command) + 1}],
    }
    if message_thread_id is not None:
        message["message_thread_id"] = message_thread_id
        message["is_topic_message"] = True
    return {"update_id": update_id, "message": message}


def _callback_update(
    data: str,
    update_id: int = 1,
    callback_id: str = "cb1",
    chat_id: int = _CHAT_ID,
    message_id: int = 2000,
    user_id: int = _ADMIN_TG_ID,
    username: str = _ADMIN_USERNAME,
    first_name: str = "Admin",
) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": callback_id,
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": first_name,
                "username": username,
            },
            "message": {
                "message_id": message_id,
                "date": 1700000000,
                "chat": {"id": chat_id, "type": "supergroup", "title": "Test Group"},
                "text": "placeholder",
            },
            "chat_instance": "1",
            "data": data,
        },
    }


async def _create_project(session_factory: async_sessionmaker[AsyncSession]) -> Project:
    async with session_factory() as session:
        project = Project(tg_chat_id=_CHAT_ID, name="Test Group", invite_payload="payload")
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id))
        await session.commit()
        await session.refresh(project)
        return project


async def _add_member(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: int,
    *,
    tg_user_id: int,
    username: str | None,
    first_name: str = "Member",
    role: MembershipRole = MembershipRole.MEMBER,
) -> ProjectMembership:
    async with session_factory() as session:
        user = User(tg_user_id=tg_user_id, username=username, first_name=first_name)
        session.add(user)
        await session.flush()
        membership = ProjectMembership(project_id=project_id, user_id=user.id, role=role)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)
        return membership


def _first_button_callback_data(fake_bot_api: FakeBotApi) -> str:
    message = fake_bot_api.sent_messages[-1]
    assert message.reply_markup is not None
    data = message.reply_markup.inline_keyboard[0][0].callback_data
    assert data is not None
    return data


def _callback_data_for_membership(fake_bot_api: FakeBotApi, membership_id: int) -> str:
    """Список `/remove_member` включает всех активных участников (в т.ч. и самого
    вызвавшего админа), порядок которых не гарантирован — ищем кнопку конкретного
    участника по его `membership_id`, а не полагаемся на позицию в списке."""
    message = fake_bot_api.sent_messages[-1]
    assert message.reply_markup is not None
    suffix = f":{membership_id}"
    for row in message.reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data and button.callback_data.endswith(suffix):
                return button.callback_data
    raise AssertionError(f"no button found for membership {membership_id}")


async def test_members_lists_active_members_with_roles(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        first_name="Admin",
        role=MembershipRole.ADMIN,
    )
    await _add_member(session_factory, project.id, tg_user_id=2, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update("members")))

    text = fake_bot_api.sent_texts[-1]
    assert "Admin" in text and "админ" in text
    assert "alice" in text


async def test_members_shows_owner_suffix_distinct_from_admin(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=1,
        username="owner",
        first_name="Owner",
        role=MembershipRole.OWNER,
    )
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        first_name="Coadmin",
        role=MembershipRole.ADMIN,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update("members")))

    text = fake_bot_api.sent_texts[-1]
    assert "Owner (@owner) — главный админ" in text
    assert "Coadmin (@admin_user) — админ" in text


async def test_members_rejects_non_admin(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )

    dispatcher = create_dispatcher(session_factory)
    update = _command_update("members", user_id=999, username="intruder")
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(update))

    assert any("только администратор" in text for text in fake_bot_api.sent_texts)


async def test_members_without_project_shows_hint(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update("members")))

    assert any("не настроен" in text for text in fake_bot_api.sent_texts)


async def test_remove_member_full_flow_removes_membership(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )
    target = await _add_member(session_factory, project.id, tg_user_id=2, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_member"))
    )
    pick_data = _callback_data_for_membership(fake_bot_api, target.id)
    assert pick_data == f"rmm:{target.id}"

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(pick_data, update_id=2))
    )
    assert "alice" in fake_bot_api.edited_texts[-1]

    confirm_data = f"rmc:{target.id}"
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(confirm_data, update_id=3))
    )

    async with session_factory() as session:
        membership = await session.get(ProjectMembership, target.id)
        assert membership is not None
        assert membership.status == MembershipStatus.REMOVED
        assert membership.removed_at is not None
        admin = await session.scalar(select(User).where(User.tg_user_id == _ADMIN_TG_ID))
        assert membership.removed_by == admin.id  # type: ignore[union-attr]

    assert "удалён" in fake_bot_api.edited_texts[-1]


async def test_remove_member_cancel_keeps_membership_active(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )
    target = await _add_member(session_factory, project.id, tg_user_id=2, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_member"))
    )
    pick_data = _callback_data_for_membership(fake_bot_api, target.id)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(pick_data, update_id=2))
    )
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update("rmx", update_id=3))
    )

    async with session_factory() as session:
        membership = await session.get(ProjectMembership, target.id)
        assert membership is not None
        assert membership.status == MembershipStatus.ACTIVE

    assert "отменено" in fake_bot_api.edited_texts[-1].lower()


async def test_remove_member_rejects_non_admin_callback(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )
    target = await _add_member(session_factory, project.id, tg_user_id=2, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_member"))
    )
    pick_data = f"rmm:{target.id}"

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _callback_update(
                pick_data, update_id=2, user_id=999, username="intruder", first_name="Intruder"
            )
        ),
    )

    assert any("только администратор" in text for text in fake_bot_api.callback_answers)
    async with session_factory() as session:
        membership = await session.get(ProjectMembership, target.id)
        assert membership is not None
        assert membership.status == MembershipStatus.ACTIVE


async def test_add_admin_full_flow_promotes_member(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.OWNER,
    )
    target = await _add_member(session_factory, project.id, tg_user_id=2, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("add_admin"))
    )
    pick_data = _first_button_callback_data(fake_bot_api)
    assert pick_data == f"adm:{target.id}"

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(pick_data, update_id=2))
    )
    confirm_data = f"adc:{target.id}"
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(confirm_data, update_id=3))
    )

    async with session_factory() as session:
        membership = await session.get(ProjectMembership, target.id)
        assert membership is not None
        assert membership.role == MembershipRole.ADMIN

    assert "назначен" in fake_bot_api.edited_texts[-1]


async def test_add_admin_excludes_existing_admins(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.OWNER,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("add_admin"))
    )

    assert any("уже администраторы" in text for text in fake_bot_api.sent_texts)


async def test_add_admin_rejects_non_owner_caller(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Со-админ (роль `admin`, назначенный владельцем) не может назначать новых
    админов — это единственная привилегия, зарезервированная за `owner`."""
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=1, username="owner", role=MembershipRole.OWNER
    )
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )
    target = await _add_member(session_factory, project.id, tg_user_id=3, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("add_admin"))
    )

    assert any("только главный администратор" in text for text in fake_bot_api.sent_texts)
    async with session_factory() as session:
        membership = await session.get(ProjectMembership, target.id)
        assert membership is not None
        assert membership.role == MembershipRole.MEMBER


async def test_remove_member_excludes_owner_from_list(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    owner = await _add_member(
        session_factory, project.id, tg_user_id=1, username="owner", role=MembershipRole.OWNER
    )
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )
    target = await _add_member(session_factory, project.id, tg_user_id=3, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_member"))
    )

    message = fake_bot_api.sent_messages[-1]
    assert message.reply_markup is not None
    all_callback_data = {
        button.callback_data for row in message.reply_markup.inline_keyboard for button in row
    }
    assert f"rmm:{owner.id}" not in all_callback_data
    assert f"rmm:{target.id}" in all_callback_data


async def test_remove_member_protects_owner_via_crafted_callback(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Список `/remove_member` не показывает владельца, но злоумышленник может
    прислать callback_data напрямую — бэкенд обязан проверить роль ещё раз
    (аналогично защите не-админов от нажатия чужих кнопок)."""
    project = await _create_project(session_factory)
    owner = await _add_member(
        session_factory, project.id, tg_user_id=1, username="owner", role=MembershipRole.OWNER
    )
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"rmm:{owner.id}", update_id=1)),
    )

    assert any("Нельзя удалить" in text for text in fake_bot_api.callback_answers)
    async with session_factory() as session:
        membership = await session.get(ProjectMembership, owner.id)
        assert membership is not None
        assert membership.status == MembershipStatus.ACTIVE


async def test_remove_member_stale_pick_shows_alert(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update("rmm:9999", update_id=1))
    )

    assert any("неактуально" in text for text in fake_bot_api.callback_answers)


async def _assign_rights_topic(
    session_factory: async_sessionmaker[AsyncSession], project_id: int, thread_id: int
) -> None:
    async with session_factory() as session:
        session.add(
            ProjectTopicSetting(
                project_id=project_id, category=TopicCategory.RIGHTS, thread_id=thread_id
            )
        )
        await session.commit()


async def test_remove_admin_full_flow_demotes_admin(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.OWNER,
    )
    target = await _add_member(
        session_factory,
        project.id,
        tg_user_id=2,
        username="alice",
        role=MembershipRole.ADMIN,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_admin"))
    )
    pick_data = _first_button_callback_data(fake_bot_api)
    assert pick_data == f"dad:{target.id}"

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(pick_data, update_id=2))
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"dac:{target.id}", update_id=3)),
    )

    async with session_factory() as session:
        membership = await session.get(ProjectMembership, target.id)
        assert membership is not None
        assert membership.role == MembershipRole.MEMBER
        assert membership.status == MembershipStatus.ACTIVE

    assert "больше не администратор" in fake_bot_api.edited_texts[-1]


async def test_remove_admin_rejects_non_owner_caller(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=1, username="owner", role=MembershipRole.OWNER
    )
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_admin"))
    )

    assert any("только главный администратор" in text for text in fake_bot_api.sent_texts)


async def test_remove_admin_excludes_owner_and_members_from_list(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    owner = await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.OWNER,
    )
    co_admin = await _add_member(
        session_factory, project.id, tg_user_id=2, username="alice", role=MembershipRole.ADMIN
    )
    plain = await _add_member(session_factory, project.id, tg_user_id=3, username="bob")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_admin"))
    )

    message = fake_bot_api.sent_messages[-1]
    assert message.reply_markup is not None
    all_data = {
        button.callback_data for row in message.reply_markup.inline_keyboard for button in row
    }
    assert all_data == {f"dad:{co_admin.id}"}
    assert f"dad:{owner.id}" not in all_data
    assert f"dad:{plain.id}" not in all_data


async def test_remove_admin_without_co_admins_shows_hint(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.OWNER,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_command_update("remove_admin"))
    )

    assert any("нет со-администраторов" in text for text in fake_bot_api.sent_texts)


async def test_members_blocked_outside_rights_topic(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )
    await _assign_rights_topic(session_factory, project.id, thread_id=7)

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _command_update("members", is_forum=True, message_thread_id=3)
        ),
    )

    assert any("топика регулирования прав" in text for text in fake_bot_api.sent_texts)


async def test_members_allowed_from_rights_topic(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.ADMIN,
    )
    await _assign_rights_topic(session_factory, project.id, thread_id=7)

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _command_update("members", is_forum=True, message_thread_id=7)
        ),
    )

    assert any("Участники проекта" in text for text in fake_bot_api.sent_texts)


async def test_remove_admin_blocked_outside_rights_topic(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=_ADMIN_TG_ID,
        username=_ADMIN_USERNAME,
        role=MembershipRole.OWNER,
    )
    await _add_member(
        session_factory, project.id, tg_user_id=2, username="alice", role=MembershipRole.ADMIN
    )
    await _assign_rights_topic(session_factory, project.id, thread_id=7)

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _command_update("remove_admin", is_forum=True, message_thread_id=3)
        ),
    )

    assert any("топика регулирования прав" in text for text in fake_bot_api.sent_texts)
    assert not fake_bot_api.posts
