"""Подсказки команд по `/` (Bot API `setMyCommands`).

Список, который Telegram показывает при вводе `/`, — отдельная настройка на
стороне Bot API, не связанная с зарегистрированными в aiogram хендлерами. Его
надо явно выставить при старте приложения (см. TZ §3.6).

При добавлении/переименовании команды обновлять и хендлер, и список здесь —
иначе подсказки разъедутся с реальным поведением бота.
"""

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

# Команды только для лички (`F.chat.type == "private"`, см. start.py / new_event.py).
PRIVATE_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Зарегистрироваться по ссылке из чата"),
    BotCommand(command="new_event", description="Создать мероприятие"),
]

# Все групповые команды зарегистрированы на `group`/`supergroup` и доступны
# всем участникам чата (ролевые проверки — уже внутри хендлеров).
GROUP_COMMANDS: list[BotCommand] = [
    BotCommand(
        command="setup_registration",
        description="Настроить бота в этом чате / переназначить топик",
    ),
    BotCommand(command="set_topic", description="Привязать топик к категории сообщений"),
    BotCommand(command="unset_topic", description="Снять привязку категории от топика"),
    BotCommand(command="all", description="Позвать всех зарегистрированных участников"),
    BotCommand(command="members", description="Список участников проекта"),
    BotCommand(command="remove_member", description="Удалить участника из проекта"),
    BotCommand(command="add_admin", description="Назначить администратора проекта"),
    BotCommand(command="remove_admin", description="Понизить со-администратора до участника"),
]


async def set_bot_commands(bot: Bot) -> None:
    """Выставить подсказки команд отдельно для лички и групп.

    Два раздельных вызова, а не общий scope `default`: иначе `/start`
    подсказывался бы в группе (где не работает), а групповые команды — в личке.
    """
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
