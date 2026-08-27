import re
from unittest.mock import MagicMock

from aiogram import Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from meetup_bot.bot import create_dispatcher
from meetup_bot.bot.commands import GROUP_COMMANDS, PRIVATE_COMMANDS, set_bot_commands
from tests.conftest import FakeBotApi

_MAX_DESCRIPTION = 256


async def test_set_bot_commands_two_scoped_calls(bot: Bot, fake_bot_api: FakeBotApi) -> None:
    await set_bot_commands(bot)

    calls = fake_bot_api.set_my_commands_calls
    assert len(calls) == 2

    by_scope = {type(call.scope): call for call in calls}
    assert set(by_scope) == {BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats}

    private = by_scope[BotCommandScopeAllPrivateChats]
    group = by_scope[BotCommandScopeAllGroupChats]
    assert [c.command for c in private.commands] == ["start"]
    assert [c.command for c in group.commands] == [
        "setup_registration",
        "set_topic",
        "unset_topic",
        "all",
        "members",
        "remove_member",
        "add_admin",
        "remove_admin",
    ]


def test_command_descriptions_valid() -> None:
    for cmd in [*PRIVATE_COMMANDS, *GROUP_COMMANDS]:
        assert re.fullmatch(r"[a-z_]+", cmd.command), cmd.command
        assert cmd.description
        assert len(cmd.description) <= _MAX_DESCRIPTION


def _registered_commands() -> set[str]:
    dispatcher = create_dispatcher(MagicMock())
    found: set[str] = set()

    def walk(router):  # type: ignore[no-untyped-def]
        yield router
        for sub in router.sub_routers:
            yield from walk(sub)

    for router in walk(dispatcher):
        for handler in router.message.handlers:
            for flt in handler.filters:
                callback = flt.callback
                if isinstance(callback, CommandStart):
                    found.add("start")
                elif isinstance(callback, Command):
                    found.update(callback.commands)
    return found


def test_menu_matches_registered_handlers() -> None:
    """Гейт против расхождения подсказок с реальными хендлерами (TZ §3.6 п.4)."""
    menu = {c.command for c in [*PRIVATE_COMMANDS, *GROUP_COMMANDS]}
    assert menu == _registered_commands()
