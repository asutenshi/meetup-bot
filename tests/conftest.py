import itertools
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    GetMe,
    SendMessage,
    SetMyCommands,
    TelegramMethod,
)
from aiogram.types import Chat, Message
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from meetup_bot.db.base import Base
from meetup_bot.db.models import (  # noqa: F401
    Project,
    ProjectMembership,
    ProjectSettings,
    ProjectTopicSetting,
    User,
)

BOT_TOKEN = "123:test-token"


class FakeBotApi:
    """Подменяет `Bot.__call__`, чтобы хендлеры не делали реальные запросы к
    Telegram Bot API в тестах. Понимает методы, которые реально используются
    (`get_me`/`send_message`) — для прочих (например, `message.answer`)
    возвращаемое значение хендлерам не нужно, поэтому просто `None`."""

    def __init__(self) -> None:
        self._message_ids = itertools.count(1000)
        self.posts: list[int] = []
        self.sent_texts: list[str] = []
        self.sent_thread_ids: list[int | None] = []
        self.sent_messages: list[SendMessage] = []
        self.edited_texts: list[str] = []
        self.callback_answers: list[str] = []
        self.set_my_commands_calls: list[SetMyCommands] = []

    async def __call__(self, method: TelegramMethod, request_timeout: int | None = None):  # type: ignore[no-untyped-def]
        if isinstance(method, GetMe):
            return TgUser(id=123, is_bot=True, first_name="TestBot", username="test_bot")
        if isinstance(method, SendMessage):
            self.sent_texts.append(method.text or "")
            self.sent_thread_ids.append(method.message_thread_id)
            self.sent_messages.append(method)
            message_id = next(self._message_ids)
            if method.reply_markup is not None:
                self.posts.append(message_id)
            return Message(
                message_id=message_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=method.chat_id, type="supergroup"),
            )
        if isinstance(method, EditMessageText):
            self.edited_texts.append(method.text or "")
            return Message(
                message_id=method.message_id or next(self._message_ids),
                date=datetime.now(tz=UTC),
                chat=Chat(id=method.chat_id, type="supergroup"),
            )
        if isinstance(method, SetMyCommands):
            self.set_my_commands_calls.append(method)
            return True
        if isinstance(method, AnswerCallbackQuery):
            self.callback_answers.append(method.text or "")
            return True
        return None


@pytest.fixture
def fake_bot_api(monkeypatch: pytest.MonkeyPatch) -> FakeBotApi:
    api = FakeBotApi()
    monkeypatch.setattr(Bot, "__call__", api)
    return api


@pytest.fixture
def bot(fake_bot_api: FakeBotApi) -> Bot:
    return Bot(token=BOT_TOKEN)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session
