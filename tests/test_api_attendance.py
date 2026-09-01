import datetime
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
from aiogram import Bot
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.api import router as api_router
from meetup_bot.api.webapp_auth import INIT_DATA_HEADER
from meetup_bot.config import Settings
from meetup_bot.db.enums import EventStatus, MembershipRole, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from tests.conftest import BOT_TOKEN, FakeBotApi

_OWNER_TG = 111
_MEMBER_TG = 222
_OUTSIDER_TG = 999

_NOW = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)


def _dt(days: int) -> datetime.datetime:
    return _NOW + datetime.timedelta(days=days)


def _settings() -> Settings:
    return Settings(bot_token=BOT_TOKEN, database_url="sqlite+aiosqlite:///:memory:")


def _app(session_factory: async_sessionmaker[AsyncSession], bot: Bot) -> FastAPI:
    app = FastAPI()
    app.state.settings = _settings()
    app.state.session_factory = session_factory
    app.state.bot = bot
    app.include_router(api_router)
    return app


def _init_data(tg_user_id: int) -> str:
    payload = {
        "user": json.dumps({"id": tg_user_id, "first_name": "Web", "username": "web"}),
        "auth_date": str(int(time.time())),
        "query_id": "AAA",
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": signature})


async def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _seed(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Проект «Alpha»: owner (может править) + участник (не может) + чужак.
    Одно предстоящее мероприятие с опубликованным анонсом."""
    async with session_factory() as session:
        project = Project(tg_chat_id=-100_100, name="Alpha", invite_payload="alpha")
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id, timezone="Europe/Moscow"))

        owner = User(tg_user_id=_OWNER_TG, first_name="Аня")
        member = User(tg_user_id=_MEMBER_TG, first_name="Миша", last_name="Родин")
        session.add_all([owner, member])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    project_id=project.id,
                    user_id=owner.id,
                    role=MembershipRole.OWNER,
                    registered_at=_dt(-100),
                ),
                ProjectMembership(
                    project_id=project.id,
                    user_id=member.id,
                    role=MembershipRole.MEMBER,
                    registered_at=_dt(-100),
                ),
            ]
        )

        other_project = Project(tg_chat_id=-100_200, name="Beta", invite_payload="beta")
        session.add(other_project)
        await session.flush()
        outsider = User(tg_user_id=_OUTSIDER_TG, first_name="Чужак")
        session.add(outsider)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=other_project.id,
                user_id=outsider.id,
                role=MembershipRole.MEMBER,
            )
        )

        event = Event(
            project_id=project.id,
            description="прогулка",
            starts_at=_dt(5),
            location="Парк Горького",
            created_by=owner.id,
            announcement_message_id=5000,
        )
        session.add(event)
        await session.flush()
        other_event = Event(
            project_id=other_project.id,
            description="чужое",
            starts_at=_dt(5),
            location="Где-то",
            created_by=outsider.id,
        )
        session.add(other_event)
        await session.commit()
        return {
            "project_id": project.id,
            "event_id": event.id,
            "other_event_id": other_event.id,
            "owner_id": owner.id,
            "member_id": member.id,
        }


async def test_context_lists_participants_with_status(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        session.add(
            EventRSVP(
                event_id=ids["event_id"],
                user_id=ids["member_id"],
                status=RSVPStatus.GOING,
                updated_by=ids["member_id"],
            )
        )
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            f"/api/events/{ids['event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "Alpha"
    assert data["finalized"] is False
    assert data["counters_locked"] is False
    by_id = {p["user_id"]: p for p in data["participants"]}
    assert by_id[ids["member_id"]]["status"] == "going"
    assert by_id[ids["member_id"]]["name"] == "Миша Родин"
    assert by_id[ids["owner_id"]]["status"] is None


async def test_context_403_for_member_without_rights(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            f"/api/events/{ids['event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_MEMBER_TG)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_an_organizer"


async def test_context_404_for_event_of_other_project(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            f"/api/events/{ids['other_event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
        )

    assert response.status_code == 404


async def test_context_409_for_cancelled_event(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        event.status = EventStatus.CANCELLED
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            f"/api/events/{ids['event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "event_cancelled"


async def test_set_attendance_upserts_with_updated_by_and_refreshes(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            f"/api/events/{ids['event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
            json={"user_id": ids["member_id"], "status": "not_going"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_going"
    assert body["announcement_refreshed"] is True
    assert body["counters_recomputed"] is False

    async with session_factory() as session:
        rsvp = await session.scalar(
            select(EventRSVP).where(
                EventRSVP.event_id == ids["event_id"],
                EventRSVP.user_id == ids["member_id"],
            )
        )
        assert rsvp is not None
        assert rsvp.status == RSVPStatus.NOT_GOING
        assert rsvp.updated_by == ids["owner_id"]

    assert fake_bot_api.edited_texts, "анонс должен перерисоваться"


async def test_set_attendance_null_clears_rsvp(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        session.add(
            EventRSVP(
                event_id=ids["event_id"],
                user_id=ids["member_id"],
                status=RSVPStatus.GOING,
                updated_by=ids["member_id"],
            )
        )
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            f"/api/events/{ids['event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
            json={"user_id": ids["member_id"], "status": None},
        )

    assert response.status_code == 200
    assert response.json()["status"] is None
    async with session_factory() as session:
        rsvp = await session.scalar(
            select(EventRSVP).where(
                EventRSVP.event_id == ids["event_id"],
                EventRSVP.user_id == ids["member_id"],
            )
        )
        assert rsvp is None


async def test_set_attendance_422_for_non_member(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            f"/api/events/{ids['event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
            json={"user_id": 4242, "status": "going"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "not_a_member"


async def test_set_attendance_recomputes_counters_after_finalization(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        event.starts_at = _dt(-3)
        event.attendance_finalized_at = _dt(-2)
        # После финализации участник числился пропустившим.
        membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.user_id == ids["member_id"]
            )
        )
        assert membership is not None
        membership.consecutive_missed_events = 1
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            f"/api/events/{ids['event_id']}/attendance",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
            json={"user_id": ids["member_id"], "status": "going"},
        )

    assert response.status_code == 200
    assert response.json()["counters_recomputed"] is True

    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.user_id == ids["member_id"]
            )
        )
        assert membership is not None
        assert membership.consecutive_missed_events == 0
        assert membership.last_attended_at is not None
