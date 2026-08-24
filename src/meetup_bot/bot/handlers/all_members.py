import time
from collections.abc import Awaitable, Callable
from html import escape
from typing import Any

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command
from aiogram.types import Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipStatus
from meetup_bot.db.models import Project, ProjectMembership, ProjectSettings, User

_NOT_SET_UP_TEXT = (
    "Бот ещё не настроен в этом чате. Администратор должен вызвать "
    "/setup_registration."
)
_NO_MEMBERS_TEXT = "В проекте пока нет зарегистрированных участников."
_THROTTLED_TEXT = "Команда /all уже вызывалась недавно, попробуйте через пару минут."
_MAX_MESSAGE_LENGTH = 4096


def _mention(user: User) -> str:
    """`@username`, если он есть, иначе text-mention по `tg_user_id` (TZ §4.2) —
    так тегаются и участники, скрывшие `@username` в настройках приватности."""
    if user.username:
        return f"@{escape(user.username)}"
    return f'<a href="tg://user?id={user.tg_user_id}">{escape(user.first_name)}</a>'


def _split_into_messages(mentions: list[str]) -> list[str]:
    """Разбивает список упоминаний на сообщения не длиннее лимита Telegram
    (TZ §4.2 "разбивка на несколько сообщений при превышении лимита длины)."""
    messages: list[str] = []
    current: list[str] = []
    current_length = 0
    for mention in mentions:
        addition_length = len(mention) + (1 if current else 0)
        if current and current_length + addition_length > _MAX_MESSAGE_LENGTH:
            messages.append("\n".join(current))
            current = []
            current_length = 0
        current.append(mention)
        current_length += len(mention) + (1 if len(current) > 1 else 0)
    if current:
        messages.append("\n".join(current))
    return messages


class AllThrottleMiddleware(BaseMiddleware):
    """Троттлинг `/all` — не чаще раза в `ProjectSettings.all_command_throttle_seconds`
    на проект (TZ §6.1 "Rate limiting"). Store — атрибут инстанса, а не
    module-level dict, чтобы каждый `create_dispatcher()` (в т.ч. в тестах)
    получал независимое состояние, не разделяемое между инстансами приложения."""

    def __init__(self) -> None:
        self._last_call_at: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["all_throttle_store"] = self._last_call_at
        return await handler(event, data)


def create_router() -> Router:
    router = Router(name="all_members")

    @router.message(Command("all"), F.chat.type.in_({"group", "supergroup"}))
    async def on_all(
        message: Message,
        session: AsyncSession,
        all_throttle_store: dict[int, float],
    ) -> None:
        project = await session.scalar(
            select(Project).where(Project.tg_chat_id == message.chat.id)
        )
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return

        settings = await session.get(ProjectSettings, project.id)
        throttle_seconds = settings.all_command_throttle_seconds if settings else 0

        now = time.monotonic()
        last_call_at = all_throttle_store.get(project.id)
        if last_call_at is not None and now - last_call_at < throttle_seconds:
            await message.answer(_THROTTLED_TEXT)
            return

        members = await session.scalars(
            select(User)
            .join(ProjectMembership, ProjectMembership.user_id == User.id)
            .where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.status == MembershipStatus.ACTIVE,
            )
        )
        mentions = [_mention(user) for user in members]
        if not mentions:
            await message.answer(_NO_MEMBERS_TEXT)
            return

        all_throttle_store[project.id] = now
        # Отвечаем туда же, откуда позвали команду (`message.answer()` сама
        # подставляет `message_thread_id` входящего апдейта, если это топик).
        for chunk in _split_into_messages(mentions):
            await message.answer(chunk)

    return router
