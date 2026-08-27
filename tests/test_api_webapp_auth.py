import hashlib
import hmac
import json
import time
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import Depends, FastAPI

from meetup_bot.api.webapp_auth import (
    INIT_DATA_HEADER,
    InitDataError,
    get_tg_user_id,
    parse_init_data,
)
from meetup_bot.config import Settings

BOT_TOKEN = "123:abc"


def _settings(**overrides: object) -> Settings:
    return Settings(
        bot_token=BOT_TOKEN,
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        **overrides,  # type: ignore[arg-type]
    )


def _sign(payload: dict[str, str], *, token: str = BOT_TOKEN) -> str:
    """Собрать валидно подписанную строку initData (алгоритм Telegram)."""
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": signature})


def _payload(**overrides: str) -> dict[str, str]:
    base = {
        "user": json.dumps({"id": 42, "first_name": "Ada", "username": "ada"}),
        "auth_date": str(int(time.time())),
        "query_id": "AAABBB",
    }
    base.update(overrides)
    return base


def test_parse_init_data_valid() -> None:
    raw = _sign(_payload())

    data = parse_init_data(raw, bot_token=BOT_TOKEN, max_age=timedelta(days=1))

    assert data.user is not None
    assert data.user.id == 42
    assert data.user.username == "ada"


def test_parse_init_data_rejects_missing() -> None:
    with pytest.raises(InitDataError) as exc:
        parse_init_data("", bot_token=BOT_TOKEN, max_age=timedelta(days=1))

    assert exc.value.reason == "missing"


def test_parse_init_data_rejects_bad_signature() -> None:
    raw = _sign(_payload(), token="999:wrong")

    with pytest.raises(InitDataError) as exc:
        parse_init_data(raw, bot_token=BOT_TOKEN, max_age=timedelta(days=1))

    assert exc.value.reason == "invalid_signature"


def test_parse_init_data_rejects_tampered_payload() -> None:
    raw = _sign(_payload())
    tampered = raw.replace("query_id=AAABBB", "query_id=TAMPERED")

    with pytest.raises(InitDataError) as exc:
        parse_init_data(tampered, bot_token=BOT_TOKEN, max_age=timedelta(days=1))

    assert exc.value.reason == "invalid_signature"


def test_parse_init_data_rejects_expired_auth_date() -> None:
    old = str(int(time.time()) - 3 * 3600)
    raw = _sign(_payload(auth_date=old))

    with pytest.raises(InitDataError) as exc:
        parse_init_data(raw, bot_token=BOT_TOKEN, max_age=timedelta(hours=1))

    assert exc.value.reason == "expired"


def test_parse_init_data_rejects_without_user() -> None:
    payload = {"auth_date": str(int(time.time())), "query_id": "AAABBB"}
    raw = _sign(payload)

    with pytest.raises(InitDataError) as exc:
        parse_init_data(raw, bot_token=BOT_TOKEN, max_age=timedelta(days=1))

    assert exc.value.reason == "no_user"


def _probe_app(**settings_overrides: object) -> FastAPI:
    app = FastAPI()
    app.state.settings = _settings(**settings_overrides)

    @app.get("/api/_probe")
    async def probe(
        tg_user_id: Annotated[int, Depends(get_tg_user_id)],
    ) -> dict[str, int]:
        return {"tg_user_id": tg_user_id}

    return app


async def _get(app: FastAPI, headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/api/_probe", headers=headers)


async def test_dependency_passes_through_tg_user_id() -> None:
    raw = _sign(_payload())

    response = await _get(_probe_app(), {INIT_DATA_HEADER: raw})

    assert response.status_code == 200
    assert response.json() == {"tg_user_id": 42}


async def test_dependency_401_without_header() -> None:
    response = await _get(_probe_app())

    assert response.status_code == 401
    assert response.json()["detail"] == "missing"


async def test_dependency_401_on_bad_signature() -> None:
    raw = _sign(_payload(), token="999:wrong")

    response = await _get(_probe_app(), {INIT_DATA_HEADER: raw})

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_signature"


async def test_dependency_respects_configured_max_age() -> None:
    raw = _sign(_payload(auth_date=str(int(time.time()) - 120)))

    response = await _get(_probe_app(webapp_init_data_max_age=60), {INIT_DATA_HEADER: raw})

    assert response.status_code == 401
    assert response.json()["detail"] == "expired"
