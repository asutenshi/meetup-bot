"""Точка входа режима `worker` (TZ §3.1): запускает APScheduler и держит event
loop живым. Регистрируется как консольный скрипт `meetup-bot-worker`
(`pyproject.toml`), в `docker-compose.yml` — сервис `worker` из того же образа.
"""

import asyncio
import logging

from meetup_bot.bot import create_bot
from meetup_bot.config import get_settings
from meetup_bot.db.session import create_engine, create_session_factory
from meetup_bot.logging_config import configure_logging
from meetup_bot.scheduler import create_scheduler

logger = logging.getLogger("meetup_bot.scheduler")


async def _serve() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    # Один инстанс на весь worker: рассылающие шаги прохода (личные напоминания,
    # эскалация — TZ §3.4, п.2–3) шлют сообщения от имени бота.
    bot = create_bot(settings)
    scheduler = create_scheduler(session_factory, settings, bot)
    scheduler.start()
    logger.info(
        "worker запущен: проход напоминаний каждые %d мин",
        settings.worker_poll_interval_minutes,
    )
    try:
        # Планировщик работает в фоне на этом же loop — просто не даём процессу
        # завершиться.
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()


def run_worker() -> None:
    configure_logging(level=get_settings().log_level)
    try:
        asyncio.run(_serve())
    except (KeyboardInterrupt, SystemExit):
        logger.info("worker остановлен")
