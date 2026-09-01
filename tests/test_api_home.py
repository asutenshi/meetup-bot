import datetime
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
from aiogram import Bot
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.api import router as api_router
from meetup_bot.api.webapp_auth import INIT_DATA_HEADER
from meetup_bot.config import Settings
from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from tests.conftest import BOT_TOKEN

_OWNER_TG_ID = 111
_MEMBER_TG_ID = 222
_OUTSIDER_TG_ID = 999
_STRANGER_TG_ID = 555


def _app(session_factory: async_sessionmaker[AsyncSession], bot: Bot) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        bot_token=BOT_TOKEN, database_url="sqlite+aiosqlite:///:memory:"
    )
    app.state.session_factory = session_factory
    app.state.bot = bot
    app.include_router(api_router)
    return app


def _init_data(tg_user_id: int, *, first_name: str = "Web", last_name: str | None = None) -> str:
    user: dict[str, object] = {"id": tg_user_id, "first_name": first_name}
    if last_name is not None:
        user["last_name"] = last_name
    payload = {
        "user": json.dumps(user),
        "auth_date": str(int(time.time())),
        "query_id": "AAA",
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": signature})


async def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with session_factory() as session:
        alpha = Project(tg_chat_id=-100_100, name="Alpha", invite_payload="alpha")
        beta = Project(tg_chat_id=-100_200, name="Beta", invite_payload="beta")
        session.add_all([alpha, beta])
        await session.flush()
        session.add_all(
            [
                ProjectSettings(project_id=alpha.id),
                ProjectSettings(project_id=beta.id),
            ]
        )

        owner = User(tg_user_id=_OWNER_TG_ID, first_name="Аня")
        member = User(tg_user_id=_MEMBER_TG_ID, first_name="Миша")
        outsider = User(tg_user_id=_OUTSIDER_TG_ID, first_name="Чужак")
        session.add_all([owner, member, outsider])
        await session.flush()
        session.add_all(
            [
                # owner состоит в обоих проектах.
                ProjectMembership(
                    project_id=alpha.id, user_id=owner.id, role=MembershipRole.OWNER
                ),
                ProjectMembership(
                    project_id=beta.id, user_id=owner.id, role=MembershipRole.MEMBER
                ),
                ProjectMembership(
                    project_id=alpha.id, user_id=member.id, role=MembershipRole.MEMBER
                ),
                ProjectMembership(
                    project_id=beta.id, user_id=outsider.id, role=MembershipRole.MEMBER
                ),
            ]
        )

        planned = Event(
            project_id=alpha.id,
            description="Прогулка",
            starts_at=datetime.datetime(2026, 10, 1, 18, 0, tzinfo=datetime.UTC),
            location="Парк",
            seats_limit=5,
            created_by=owner.id,
            announcement_message_id=1,
        )
        cancelled = Event(
            project_id=alpha.id,
            description="Отменёнка",
            starts_at=datetime.datetime(2026, 10, 2, 18, 0, tzinfo=datetime.UTC),
            location="Кафе",
            status=EventStatus.CANCELLED,
            created_by=owner.id,
        )
        session.add_all([planned, cancelled])
        await session.flush()
        session.add(
            EventRSVP(
                event_id=planned.id,
                user_id=member.id,
                status=RSVPStatus.GOING,
                updated_by=member.id,
            )
        )
        session.add(
            EventRSVP(
                event_id=planned.id,
                user_id=owner.id,
                status=RSVPStatus.NOT_GOING,
                updated_by=owner.id,
            )
        )
        await session.commit()

        return {"alpha_id": alpha.id, "planned_id": planned.id, "cancelled_id": cancelled.id}


async def test_home_lists_projects_with_role(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/home",
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG_ID, first_name="Аня", last_name="Ли")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["user_name"] == "Аня Ли"
    by_payload = {p["payload"]: p for p in data["projects"]}
    assert by_payload["alpha"]["role"] == "owner"
    assert by_payload["alpha"]["name"] == "Alpha"
    assert by_payload["beta"]["role"] == "member"


async def test_home_empty_projects_for_unregistered_user(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/home",
            headers={INIT_DATA_HEADER: _init_data(_STRANGER_TG_ID, first_name="Гость")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["user_name"] == "Гость"
    assert data["projects"] == []


async def test_home_401_without_init_data(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get("/api/home")

    assert response.status_code == 401


async def test_project_events_excludes_cancelled_and_counts_going(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/alpha/events",
            headers={INIT_DATA_HEADER: _init_data(_MEMBER_TG_ID)},
        )

    assert response.status_code == 200
    events = response.json()["events"]
    assert [e["id"] for e in events] == [ids["planned_id"]]
    card = events[0]
    assert card["going_count"] == 1
    assert card["location"] == "Парк"
    assert card["seats_limit"] == 5
    assert card["is_finalized"] is False


async def test_project_events_403_for_non_member(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/alpha/events",
            headers={INIT_DATA_HEADER: _init_data(_OUTSIDER_TG_ID)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_registered"


async def test_project_events_403_for_unknown_project(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/nope/events",
            headers={INIT_DATA_HEADER: _init_data(_MEMBER_TG_ID)},
        )

    assert response.status_code == 403


async def test_project_events_reports_finalized(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        event = await session.get(Event, ids["planned_id"])
        assert event is not None
        event.attendance_finalized_at = datetime.datetime.now(datetime.UTC)
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/alpha/events",
            headers={INIT_DATA_HEADER: _init_data(_MEMBER_TG_ID)},
        )

    assert response.json()["events"][0]["is_finalized"] is True


async def test_home_hides_project_where_membership_removed(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    from sqlalchemy import select

    await _seed(session_factory)
    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership)
            .join(User, User.id == ProjectMembership.user_id)
            .where(User.tg_user_id == _OWNER_TG_ID, ProjectMembership.project_id != 0)
            .order_by(ProjectMembership.id)
        )
        assert membership is not None
        membership.status = MembershipStatus.REMOVED
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/home",
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG_ID)},
        )

    # Одну из двух записей членства owner'а сняли — остаётся один проект.
    assert len(response.json()["projects"]) == 1
