import logging
import pathlib

import httpx
import pytest

from meetup_bot.app import create_app
from meetup_bot.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(
        bot_token="123:abc",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        **overrides,  # type: ignore[arg-type]
    )


async def test_health() -> None:
    app = create_app(_settings())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_webhook_path_uses_bot_token() -> None:
    app = create_app(_settings())

    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/webhook/123:abc" in paths


async def test_webhook_not_in_openapi_schema() -> None:
    # Путь вебхука содержит токен — он не должен утекать в OpenAPI-схему,
    # из которой генерятся TS-типы фронтенда.
    app = create_app(_settings())

    assert "/health" in app.openapi()["paths"]
    assert not any(p.startswith("/webhook/") for p in app.openapi()["paths"])


async def test_webapp_not_mounted_without_build() -> None:
    app = create_app(_settings(webapp_dist_dir="webapp/dist-does-not-exist"))

    paths = {getattr(route, "path", "") for route in app.routes}

    assert not any(p.startswith("/app") for p in paths)


async def test_unhandled_request_exception_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(_settings())

    @app.get("/api/_boom")
    async def _boom() -> None:
        raise RuntimeError("kaboom")

    caplog.set_level(logging.ERROR, logger="meetup_bot.api")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/_boom")

    assert response.status_code == 500
    (record,) = [r for r in caplog.records if r.message == "unhandled request exception"]
    assert record.path == "/api/_boom"
    assert record.method == "GET"
    assert "kaboom" in caplog.text


async def test_webapp_served_when_dist_exists(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>webapp</title>")
    app = create_app(_settings(webapp_dist_dir=str(tmp_path)))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/app/")

    assert response.status_code == 200
    assert "webapp" in response.text
