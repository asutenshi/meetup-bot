import asyncio
import logging
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot import worker_main
from meetup_bot.config import Settings
from meetup_bot.scheduler import (
    PASS_JOB_ID,
    create_scheduler,
    run_scheduler_pass,
)


def _settings(**overrides: object) -> Settings:
    return Settings(
        bot_token="123:abc",
        database_url="sqlite+aiosqlite:///:memory:",
        **overrides,  # type: ignore[arg-type]
    )


def test_worker_main_importable() -> None:
    assert callable(worker_main)


def test_create_scheduler_registers_single_interval_pass() -> None:
    scheduler = create_scheduler(
        session_factory=None,  # type: ignore[arg-type]  # джоба не запускается, только инспекция
        settings=_settings(worker_poll_interval_minutes=25),
    )

    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    (job,) = jobs
    assert job.id == PASS_JOB_ID
    assert job.trigger.interval == timedelta(minutes=25)


async def test_run_scheduler_pass_empty_only_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="meetup_bot.scheduler")

    # `_PASSES` пуст (каркас 4.1) — session_factory не вызывается вовсе.
    await run_scheduler_pass(session_factory=None)  # type: ignore[arg-type]

    assert "начало" in caplog.text
    assert "конец" in caplog.text


async def test_run_scheduler_pass_runs_registered_steps(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[AsyncSession] = []

    async def _step(session: AsyncSession) -> None:
        seen.append(session)

    monkeypatch.setattr("meetup_bot.scheduler._PASSES", [_step])

    await run_scheduler_pass(session_factory)

    assert len(seen) == 1
    assert isinstance(seen[0], AsyncSession)


async def test_run_scheduler_pass_isolates_failing_step(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ran: list[str] = []

    async def _boom(session: AsyncSession) -> None:
        ran.append("boom")
        raise RuntimeError("boom")

    async def _ok(session: AsyncSession) -> None:
        ran.append("ok")

    monkeypatch.setattr("meetup_bot.scheduler._PASSES", [_boom, _ok])
    caplog.set_level(logging.ERROR, logger="meetup_bot.scheduler")

    await run_scheduler_pass(session_factory)  # не пробрасывает исключение

    assert ran == ["boom", "ok"]
    assert "_boom" in caplog.text


async def test_scheduler_fires_pass_on_start(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired = asyncio.Event()

    async def _fake_pass(sf: async_sessionmaker[AsyncSession]) -> None:
        assert sf is session_factory
        fired.set()

    monkeypatch.setattr("meetup_bot.scheduler.run_scheduler_pass", _fake_pass)

    scheduler = create_scheduler(session_factory, _settings())
    scheduler.start()
    try:
        await asyncio.wait_for(fired.wait(), timeout=5)
    finally:
        scheduler.shutdown(wait=False)
