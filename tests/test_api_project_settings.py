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
from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import (
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from tests.conftest import BOT_TOKEN

_OWNER_TG = 111
_MEMBER_TG = 222
_OUTSIDER_TG = 999


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
    """Проект «Alpha»: owner + обычный участник. Отдельный проект «Beta» с чужаком."""
    async with session_factory() as session:
        project = Project(tg_chat_id=-100_100, name="Alpha", invite_payload="alpha")
        session.add(project)
        await session.flush()
        session.add(
            ProjectSettings(
                project_id=project.id,
                reminder_send_hour=20,
                timezone="Europe/Moscow",
                all_command_throttle_seconds=180,
            )
        )

        owner = User(tg_user_id=_OWNER_TG, first_name="Аня")
        member = User(tg_user_id=_MEMBER_TG, first_name="Миша")
        session.add_all([owner, member])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    project_id=project.id, user_id=owner.id, role=MembershipRole.OWNER
                ),
                ProjectMembership(
                    project_id=project.id, user_id=member.id, role=MembershipRole.MEMBER
                ),
            ]
        )

        other = Project(tg_chat_id=-100_200, name="Beta", invite_payload="beta")
        session.add(other)
        await session.flush()
        outsider = User(tg_user_id=_OUTSIDER_TG, first_name="Чужак")
        session.add(outsider)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=other.id, user_id=outsider.id, role=MembershipRole.MEMBER
            )
        )
        await session.commit()
        return {"project_id": project.id}


def _full_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "reminder_days_threshold": 14,
        "missed_events_escalation_count": 3,
        "reminder_send_hour": 20,
        "all_command_throttle_seconds": 180,
        "timezone": "Europe/Moscow",
    }
    body.update(overrides)
    return body


async def _read_settings(
    session_factory: async_sessionmaker[AsyncSession], project_id: int
) -> ProjectSettings:
    async with session_factory() as session:
        settings = await session.get(ProjectSettings, project_id)
        assert settings is not None
        return settings


async def test_get_returns_values_and_fields(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/alpha/settings",
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "Alpha"
    assert data["reminder_send_hour"] == 20
    assert data["timezone"] == "Europe/Moscow"
    assert data["all_command_throttle_seconds"] == 180
    field_attrs = {f["attr"] for f in data["fields"]}
    assert field_attrs == {
        "reminder_days_threshold",
        "missed_events_escalation_count",
        "reminder_send_hour",
        "all_command_throttle_seconds",
        "timezone",
    }
    hour_field = next(f for f in data["fields"] if f["attr"] == "reminder_send_hour")
    assert hour_field["kind"] == "int"
    assert hour_field["min"] == 0
    assert hour_field["max"] == 23
    tz_field = next(f for f in data["fields"] if f["attr"] == "timezone")
    assert tz_field["kind"] == "timezone"
    assert tz_field["min"] is None


async def test_put_updates_all_fields_and_persists(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            "/api/projects/alpha/settings",
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
            json=_full_body(
                reminder_days_threshold=30,
                reminder_send_hour=9,
                all_command_throttle_seconds=0,
                timezone="Asia/Novosibirsk",
            ),
        )

    assert response.status_code == 200
    assert response.json()["reminder_send_hour"] == 9

    settings = await _read_settings(session_factory, ids["project_id"])
    assert settings.reminder_days_threshold == 30
    assert settings.reminder_send_hour == 9
    assert settings.all_command_throttle_seconds == 0
    assert settings.timezone == "Asia/Novosibirsk"


async def test_put_admin_can_edit(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership)
            .join(User, User.id == ProjectMembership.user_id)
            .where(User.tg_user_id == _MEMBER_TG)
        )
        assert membership is not None
        membership.role = MembershipRole.ADMIN
        await session.commit()
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            "/api/projects/alpha/settings",
            headers={INIT_DATA_HEADER: _init_data(_MEMBER_TG)},
            json=_full_body(reminder_send_hour=8),
        )

    assert response.status_code == 200
    settings = await _read_settings(session_factory, ids["project_id"])
    assert settings.reminder_send_hour == 8


async def test_put_rejects_out_of_range_without_persisting(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            "/api/projects/alpha/settings",
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
            json=_full_body(reminder_send_hour=42),
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_setting"
    assert detail["field"] == "reminder_send_hour"

    settings = await _read_settings(session_factory, ids["project_id"])
    assert settings.reminder_send_hour == 20


async def test_put_rejects_bad_timezone(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            "/api/projects/alpha/settings",
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
            json=_full_body(timezone="Mars/Olympus"),
        )

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "timezone"
    settings = await _read_settings(session_factory, ids["project_id"])
    assert settings.timezone == "Europe/Moscow"


async def test_get_403_for_plain_member(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/alpha/settings",
            headers={INIT_DATA_HEADER: _init_data(_MEMBER_TG)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_an_admin"


async def test_get_403_for_outsider(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/alpha/settings",
            headers={INIT_DATA_HEADER: _init_data(_OUTSIDER_TG)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_registered"


async def test_get_403_for_unknown_project(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.get(
            "/api/projects/does-not-exist/settings",
            headers={INIT_DATA_HEADER: _init_data(_OWNER_TG)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_registered"


async def test_put_401_without_init_data(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    app = _app(session_factory, bot)

    async with await _client(app) as client:
        response = await client.put(
            "/api/projects/alpha/settings", json=_full_body()
        )

    assert response.status_code == 401
