"""Worker-процесс напоминаний: APScheduler + периодический проход по БД.

Отдельная точка входа режима `worker` (TZ §3.1, п.1): тот же код и модели, что
и у режима `bot+api`, но без приёма входящих HTTP-запросов. Запускается вторым
контейнером из того же образа (`docker-compose.yml`, сервис `worker`), чтобы
падение долгого cron-цикла не роняло приём сообщений бота, и наоборот.

Сам проход (`run_scheduler_pass`) прогоняет по очереди независимые джобы из
TZ §3.4 (финализация явки — задача 4.2; личное напоминание «давно не виделись» —
задача 4.3; эскалация организатору/админу — задача 4.4) как элементы `_PASSES`.
Точка входа процесса — `meetup_bot.scheduler.runner`.

Каждый шаг получает `(session, bot)`: `session` — своя на шаг (своя транзакция),
`bot` — общий на весь worker (создаётся в `runner`), нужен рассылающим шагам
(4.3–4.4); финализация явки его игнорирует.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.config import Settings
from meetup_bot.scheduler.absence_reminder import remind_absent_members
from meetup_bot.scheduler.attendance import finalize_attendance

logger = logging.getLogger("meetup_bot.scheduler")

# Фиксированный id периодической джобы: повторная регистрация (рестарт worker,
# `replace_existing=True`) не плодит дубликаты.
PASS_JOB_ID = "reminders-pass"

# Шаг периодического прохода (TZ §3.4). Каждый — независимая джоба в собственной
# транзакции: ошибка одного шага логируется и не отменяет остальные. Список
# наполняется в задачах 4.2–4.4.
SchedulerPass = Callable[[AsyncSession, Bot | None], Awaitable[None]]
_PASSES: list[SchedulerPass] = [
    finalize_attendance,  # 4.2 — финализация явки по списку RSVP (TZ §3.4, п.1)
    remind_absent_members,  # 4.3 — личное напоминание «давно не виделись» (TZ §3.4, п.2)
]


async def run_scheduler_pass(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot | None = None
) -> None:
    """Один периодический проход по БД (TZ §3.4).

    Логирует старт и итог прохода (TZ §6.2: «Cron-задача планировщика логирует
    старт/итог каждого прохода»). Каждый шаг из `_PASSES` выполняется в своей
    сессии/транзакции; исключение внутри шага логируется и не срывает остальные
    шаги и следующий тик. Пока `_PASSES` пуст — проход только пишет две строки в
    лог.
    """
    logger.info("проход напоминаний: начало (%d шаг(ов))", len(_PASSES))
    for scheduler_pass in _PASSES:
        try:
            async with session_factory() as session, session.begin():
                await scheduler_pass(session, bot)
        except Exception:
            logger.exception("проход напоминаний: шаг %s упал", scheduler_pass.__name__)
    logger.info("проход напоминаний: конец")


def create_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    bot: Bot | None = None,
) -> AsyncIOScheduler:
    """Собирает `AsyncIOScheduler` с единственной периодической джобой
    `run_scheduler_pass` (интервал — `Settings.worker_poll_interval_minutes`).

    `bot` пробрасывается в каждый проход для рассылающих шагов (4.3–4.4);
    `runner` передаёт сюда живой инстанс, тесты — обычно `None`.

    Таймзона планировщика — UTC (детерминизм расписания); таймзона проекта
    (`ProjectSettings.timezone`) учитывается уже внутри самих шагов прохода.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_scheduler_pass,
        trigger=IntervalTrigger(minutes=settings.worker_poll_interval_minutes),
        args=[session_factory, bot],
        id=PASS_JOB_ID,
        name="Проход напоминаний (TZ §3.4)",
        # worker лежал несколько тиков → один прогон при возврате, а не очередь.
        coalesce=True,
        # проход не должен наслаиваться сам на себя, если затянулся.
        max_instances=1,
        replace_existing=True,
        # первый проход — сразу при старте worker, не через целый интервал
        # (после деплоя финализация/напоминания не ждут 15–30 минут).
        next_run_time=datetime.now(UTC),
    )
    return scheduler
