import datetime
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import pytest
from aiogram import Bot
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.api import router as api_router
from meetup_bot.api.webapp_auth import INIT_DATA_HEADER
from meetup_bot.config import Settings
from meetup_bot.db.enums import (
    EventStatus,
    MembershipRole,
    MembershipStatus,
    RSVPStatus,
    TopicCategory,
)
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    ProjectTopicSetting,
    User,
)
from tests.conftest import BOT_TOKEN, FakeBotApi

_CREATOR_TG_ID = 111
_OTHER_TG_ID = 222
_OUTSIDER_TG_ID = 999


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


async def _seed(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Проект «Alpha» (`payload=alpha`), создатель + ещё один участник + чужак
    из другого проекта. Возвращает id-шники для проверок."""
    async with session_factory() as session:
        project = Project(tg_chat_id=-100_100, name="Alpha", invite_payload="alpha")
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id, timezone="Europe/Moscow"))

        creator = User(tg_user_id=_CREATOR_TG_ID, first_name="Аня", username="anya")
        other = User(tg_user_id=_OTHER_TG_ID, first_name="Миша", last_name="Родин")
        session.add_all([creator, other])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    project_id=project.id, user_id=creator.id, role=MembershipRole.OWNER
                ),
                ProjectMembership(
                    project_id=project.id, user_id=other.id, role=MembershipRole.MEMBER
                ),
            ]
        )

        outsider_project = Project(
            tg_chat_id=-100_200, name="Beta", invite_payload="beta"
        )
        session.add(outsider_project)
        await session.flush()
        outsider = User(tg_user_id=_OUTSIDER_TG_ID, first_name="Чужак")
        session.add(outsider)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=outsider_project.id,
                user_id=outsider.id,
                role=MembershipRole.MEMBER,
            )
        )
        await session.commit()

        return {
            "project_id": project.id,
            "chat_id": project.tg_chat_id,
            "creator_id": creator.id,
            "other_id": other.id,
        }


async def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _valid_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "starts_at": "2026-09-14T15:00:00Z",
        "location": "Парк Горького",
        "description": "Вечерняя прогулка",
        "co_organizer_user_ids": [],
    }
    body.update(overrides)
    return body


async def test_context_returns_members_with_self_flag(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/events/context",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "Alpha"
    by_id = {m["user_id"]: m for m in data["members"]}
    assert by_id[ids["creator_id"]]["is_self"] is True
    assert by_id[ids["other_id"]]["is_self"] is False
    assert by_id[ids["other_id"]]["name"] == "Миша Родин"


async def test_context_401_without_init_data(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get("/api/events/context", params={"project": "alpha"})

    assert response.status_code == 401


async def test_context_400_without_project_param(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/events/context", headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "missing_project"


async def test_context_403_when_not_a_member(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/events/context",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OUTSIDER_TG_ID)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_registered"


async def test_create_event_persists_and_publishes_announcement(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    fake_bot_api: FakeBotApi,
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_valid_body(
                ends_at="2026-09-15T15:00:00Z",
                budget_per_person="1250.00",
                seats_limit=8,
                co_organizer_user_ids=[ids["creator_id"], ids["other_id"]],
            ),
        )

    assert response.status_code == 201
    body = response.json()

    async with session_factory() as session:
        event = await session.scalar(select(Event).where(Event.id == body["event_id"]))
        assert event is not None
        assert event.project_id == ids["project_id"]
        assert event.created_by == ids["creator_id"]
        assert event.location == "Парк Горького"
        assert event.seats_limit == 8
        assert event.announcement_message_id == body["announcement_message_id"]

        co = await session.scalars(
            select(EventCoOrganizer.user_id).where(EventCoOrganizer.event_id == event.id)
        )
        assert set(co) == {ids["creator_id"], ids["other_id"]}

    sent = fake_bot_api.sent_messages[-1]
    assert sent.chat_id == ids["chat_id"]
    assert "Парк Горького" in (sent.text or "")
    assert "✅ Участвует: 0/8" in (sent.text or "")
    assert sent.reply_markup is not None


async def test_create_event_without_co_organizers(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_valid_body(co_organizer_user_ids=[]),
        )

    assert response.status_code == 201
    async with session_factory() as session:
        count = await session.scalars(select(EventCoOrganizer.id))
        assert list(count) == []


async def test_create_event_rejects_co_organizer_outside_project(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_valid_body(co_organizer_user_ids=[123456]),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "co_organizer_not_a_member"


async def test_create_event_rejects_ends_before_starts(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_valid_body(ends_at="2026-09-13T15:00:00Z"),
        )

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["location", "description"])
async def test_create_event_requires_non_blank_text(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, field: str
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_valid_body(**{field: "   "}),
        )

    assert response.status_code == 422


async def test_create_event_403_for_non_member(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OUTSIDER_TG_ID)},
            json=_valid_body(),
        )

    assert response.status_code == 403


async def test_create_event_publishes_to_events_topic(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        session.add(
            ProjectTopicSetting(
                project_id=ids["project_id"],
                category=TopicCategory.EVENTS,
                thread_id=4242,
            )
        )
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_valid_body(),
        )

    assert response.status_code == 201
    assert fake_bot_api.sent_thread_ids[-1] == 4242


async def _make_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: int,
    created_by: int,
    co_organizer_ids: list[int] | None = None,
    going_user_ids: list[int] | None = None,
) -> int:
    async with session_factory() as session:
        event = Event(
            project_id=project_id,
            description="Старое описание",
            starts_at=datetime.datetime(2026, 10, 1, 18, 0, tzinfo=datetime.UTC),
            location="Старое место",
            created_by=created_by,
            announcement_message_id=777,
        )
        session.add(event)
        await session.flush()
        for uid in co_organizer_ids or []:
            session.add(EventCoOrganizer(event_id=event.id, user_id=uid))
        for uid in going_user_ids or []:
            session.add(
                EventRSVP(
                    event_id=event.id,
                    user_id=uid,
                    status=RSVPStatus.GOING,
                    updated_by=uid,
                )
            )
        await session.commit()
        return event.id


def _edit_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "starts_at": "2026-10-01T18:00:00Z",
        "location": "Старое место",
        "description": "Старое описание",
        "co_organizer_user_ids": [],
    }
    body.update(overrides)
    return body


async def test_edit_context_returns_prefill(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory,
        project_id=ids["project_id"],
        created_by=ids["creator_id"],
        co_organizer_ids=[ids["creator_id"]],
    )
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            f"/api/events/{event_id}",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "Alpha"
    assert data["event"]["location"] == "Старое место"
    assert data["event"]["co_organizer_user_ids"] == [ids["creator_id"]]
    assert {m["user_id"] for m in data["members"]} == {ids["creator_id"], ids["other_id"]}


async def test_edit_context_403_for_non_organizer(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory,
        project_id=ids["project_id"],
        created_by=ids["creator_id"],
        co_organizer_ids=[ids["creator_id"]],
    )
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            f"/api/events/{event_id}",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OTHER_TG_ID)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_an_organizer"


async def test_edit_context_404_for_event_of_other_project(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory, project_id=ids["project_id"], created_by=ids["creator_id"]
    )
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            f"/api/events/{event_id}",
            params={"project": "beta"},
            headers={INIT_DATA_HEADER: _init_data(_OUTSIDER_TG_ID)},
        )

    assert response.status_code == 404


async def test_update_event_changes_fields_and_edits_announcement(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory, project_id=ids["project_id"], created_by=ids["creator_id"]
    )
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            f"/api/events/{event_id}",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_edit_body(location="Новое место", seats_limit=10),
        )

    assert response.status_code == 200
    async with session_factory() as session:
        event = await session.get(Event, event_id)
        assert event is not None
        assert event.location == "Новое место"
        assert event.seats_limit == 10

    edited = fake_bot_api.edited_messages[-1]
    assert edited.message_id == 777
    assert "Новое место" in (edited.text or "")


async def test_update_event_notifies_going_members(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory,
        project_id=ids["project_id"],
        created_by=ids["creator_id"],
        going_user_ids=[ids["other_id"]],
    )
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            f"/api/events/{event_id}",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_edit_body(starts_at="2026-10-02T18:00:00Z"),
        )

    assert response.status_code == 200
    assert response.json()["notified_going"] == 1
    dm = [m for m in fake_bot_api.sent_messages if m.chat_id == _OTHER_TG_ID]
    assert dm
    text = dm[-1].text or ""
    assert "Перенос" in text and "Новое время" in text
    keyboard = dm[-1].reply_markup
    assert keyboard is not None
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert any(b.url == "https://t.me/c/100/777" for b in buttons)
    assert any(b.callback_data == f"rsvp:{event_id}:going" for b in buttons)


async def test_update_event_replaces_co_organizers(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory,
        project_id=ids["project_id"],
        created_by=ids["creator_id"],
        co_organizer_ids=[ids["creator_id"]],
    )
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            f"/api/events/{event_id}",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_edit_body(co_organizer_user_ids=[ids["other_id"]]),
        )

    assert response.status_code == 200
    async with session_factory() as session:
        rows = await session.scalars(
            select(EventCoOrganizer.user_id).where(EventCoOrganizer.event_id == event_id)
        )
        assert set(rows) == {ids["other_id"]}


async def test_update_event_403_for_non_organizer(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory,
        project_id=ids["project_id"],
        created_by=ids["creator_id"],
        co_organizer_ids=[ids["creator_id"]],
    )
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            f"/api/events/{event_id}",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_OTHER_TG_ID)},
            json=_edit_body(location="Взлом"),
        )

    assert response.status_code == 403


async def test_update_event_409_when_cancelled(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    event_id = await _make_event(
        session_factory, project_id=ids["project_id"], created_by=ids["creator_id"]
    )
    async with session_factory() as session:
        event = await session.get(Event, event_id)
        assert event is not None
        event.status = EventStatus.CANCELLED
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            f"/api/events/{event_id}",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_edit_body(),
        )

    assert response.status_code == 409


async def test_create_event_removed_member_cannot_be_co_organizer(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == ids["project_id"],
                ProjectMembership.user_id == ids["other_id"],
            )
        )
        assert membership is not None
        membership.status = MembershipStatus.REMOVED
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.post(
            "/api/events",
            params={"project": "alpha"},
            headers={INIT_DATA_HEADER: _init_data(_CREATOR_TG_ID)},
            json=_valid_body(co_organizer_user_ids=[ids["other_id"]]),
        )

    assert response.status_code == 422
