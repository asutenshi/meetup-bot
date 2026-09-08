import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.models import User
from meetup_bot.services.users import clear_bot_blocked, mark_bot_blocked


async def test_mark_and_clear_bot_blocked(session: AsyncSession) -> None:
    session.add(User(tg_user_id=1, first_name="Тест"))
    await session.commit()

    await mark_bot_blocked(session, tg_user_id=1, now=dt.datetime(2026, 1, 2, tzinfo=dt.UTC))
    stored = await session.get(User, 1)
    assert stored is not None
    assert stored.bot_blocked_at == dt.datetime(2026, 1, 2, tzinfo=dt.UTC)

    await clear_bot_blocked(session, tg_user_id=1)
    assert stored.bot_blocked_at is None


async def test_mark_keeps_first_moment(session: AsyncSession) -> None:
    first = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    session.add(User(tg_user_id=1, first_name="Тест", bot_blocked_at=first))
    await session.commit()

    await mark_bot_blocked(session, tg_user_id=1, now=dt.datetime(2026, 6, 1, tzinfo=dt.UTC))

    stored = await session.get(User, 1)
    assert stored is not None
    # SQLite отдаёт naive datetime — сравниваем без tzinfo.
    assert stored.bot_blocked_at.replace(tzinfo=dt.UTC) == first


async def test_helpers_noop_for_unknown_user(session: AsyncSession) -> None:
    await mark_bot_blocked(session, tg_user_id=999)
    await clear_bot_blocked(session, tg_user_id=999)
    assert await session.get(User, 999) is None
