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
    MenuButtonWebApp,
    WebAppInfo,
)

from meetup_bot.services.webapp_url import build_hub_url

# Команды только для лички (`F.chat.type == "private"`, см. start.py / new_event.py).
PRIVATE_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Зарегистрироваться по ссылке из чата"),
    BotCommand(command="new_event", description="Создать мероприятие"),
    BotCommand(command="edit_event", description="Редактировать мероприятие"),
    BotCommand(command="cancel_event", description="Отменить мероприятие"),
    BotCommand(command="attendance", description="Поправить явку участников"),
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
    BotCommand(command="settings", description="Пороги напоминаний и таймзона проекта"),
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


# Кнопка-меню (`MenuButtonWebApp`) поддерживается только в личке; текст не
# длиннее 64 символов (Bot API).
_MENU_BUTTON_TEXT = "Открыть"


async def set_menu_button(bot: Bot, *, public_base_url: str | None) -> None:
    """Глобальная кнопка-меню слева от поля ввода → домашний экран-хаб Web App
    (задача 2.9.1, TZ §3.8). `setChatMenuButton` без `chat_id` — одна на бота,
    фиксированный URL хаба без контекста (проект хаб разрешает сам).

    Без `public_base_url` (Mini App не раздаётся) кнопку не ставим — как и
    `/new_event` не строит `web_app`-кнопок. В группах Telegram кнопку-меню
    Web App всё равно показывает как список команд, отдельный вызов не нужен.
    """
    if not public_base_url:
        return
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text=_MENU_BUTTON_TEXT,
            web_app=WebAppInfo(url=build_hub_url(public_base_url)),
        )
    )
