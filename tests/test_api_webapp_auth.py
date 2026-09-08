import hashlib
import hmac
import json
import logging
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


def test_parse_init_data_rejects_expired_when_strict() -> None:
    old = str(int(time.time()) - 3 * 3600)
    raw = _sign(_payload(auth_date=old))

    with pytest.raises(InitDataError) as exc:
        parse_init_data(
            raw, bot_token=BOT_TOKEN, max_age=timedelta(hours=1), reject_stale=True
        )

    assert exc.value.reason == "expired"
    assert exc.value.age_seconds is not None
    assert exc.value.age_seconds == pytest.approx(3 * 3600, abs=5)
    assert exc.value.max_age_seconds == 3600


def test_parse_init_data_accepts_expired_when_not_strict(
    caplog: pytest.LogCaptureFixture,
) -> None:
    old = str(int(time.time()) - 3 * 3600)
    raw = _sign(_payload(auth_date=old))
    caplog.set_level(logging.WARNING, logger="meetup_bot.api")

    data = parse_init_data(
        raw, bot_token=BOT_TOKEN, max_age=timedelta(hours=1), reject_stale=False
    )

    assert data.user is not None
    assert data.user.id == 42
    (record,) = [r for r in caplog.records if r.message == "initData stale but accepted"]
    assert record.age_seconds == pytest.approx(3 * 3600, abs=5)
    assert record.max_age_seconds == 3600


def test_parse_init_data_max_age_zero_skips_age_check() -> None:
    old = str(int(time.time()) - 30 * 86400)
    raw = _sign(_payload(auth_date=old))

    data = parse_init_data(
        raw, bot_token=BOT_TOKEN, max_age=timedelta(0), reject_stale=True
    )

    assert data.user is not None


def test_parse_init_data_rejects_clock_skew() -> None:
    # auth_date заметно в будущем относительно часов сервера.
    future = str(int(time.time()) + 3600)
    raw = _sign(_payload(auth_date=future))

    with pytest.raises(InitDataError) as exc:
        parse_init_data(raw, bot_token=BOT_TOKEN, max_age=timedelta(days=1))

    assert exc.value.reason == "clock_skew"
    assert exc.value.age_seconds is not None
    assert exc.value.age_seconds < 0


def test_parse_init_data_tolerates_small_clock_skew() -> None:
    # Небольшой дрейф часов (в пределах допуска) не должен ломать валидацию.
    future = str(int(time.time()) + 60)
    raw = _sign(_payload(auth_date=future))

    data = parse_init_data(raw, bot_token=BOT_TOKEN, max_age=timedelta(days=1))

    assert data.user is not None
    assert data.user.id == 42


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


async def test_dependency_accepts_stale_init_data_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Дефолт — необязательная проверка: просроченная initData проходит.
    raw = _sign(_payload(auth_date=str(int(time.time()) - 120)))
    caplog.set_level(logging.WARNING, logger="meetup_bot.api")

    response = await _get(
        _probe_app(webapp_init_data_max_age=60), {INIT_DATA_HEADER: raw}
    )

    assert response.status_code == 200
    assert response.json() == {"tg_user_id": 42}
    assert any(r.message == "initData stale but accepted" for r in caplog.records)


async def test_dependency_rejects_stale_init_data_in_strict_mode() -> None:
    raw = _sign(_payload(auth_date=str(int(time.time()) - 120)))

    response = await _get(
        _probe_app(webapp_init_data_max_age=60, webapp_init_data_reject_stale=True),
        {INIT_DATA_HEADER: raw},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "expired"


async def test_dependency_reports_clock_skew() -> None:
    raw = _sign(_payload(auth_date=str(int(time.time()) + 3600)))

    response = await _get(_probe_app(), {INIT_DATA_HEADER: raw})

    assert response.status_code == 401
    assert response.json()["detail"] == "clock_skew"


async def test_expired_is_logged_with_age_in_strict_mode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = _sign(_payload(auth_date=str(int(time.time()) - 120)))
    caplog.set_level(logging.INFO, logger="meetup_bot.api")

    await _get(
        _probe_app(webapp_init_data_max_age=60, webapp_init_data_reject_stale=True),
        {INIT_DATA_HEADER: raw},
    )

    (record,) = [r for r in caplog.records if r.message == "initData validation failed"]
    assert record.reason == "expired"
    assert record.age_seconds == pytest.approx(120, abs=5)
    assert record.max_age_seconds == 60


async def test_invalid_init_data_is_logged_as_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = _sign(_payload(), token="999:wrong")
    caplog.set_level(logging.INFO, logger="meetup_bot.api")

    await _get(_probe_app(), {INIT_DATA_HEADER: raw})

    (record,) = [r for r in caplog.records if r.message == "initData validation failed"]
    assert record.levelno == logging.WARNING
    assert record.reason == "invalid_signature"
    assert record.path == "/api/_probe"


async def test_missing_init_data_is_logged_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="meetup_bot.api")

    await _get(_probe_app())

    (record,) = [r for r in caplog.records if r.message == "initData validation failed"]
    assert record.levelno == logging.INFO
    assert record.reason == "missing"
