import uvicorn

from meetup_bot.app import create_app
from meetup_bot.config import get_settings
from meetup_bot.logging_config import configure_logging
from meetup_bot.scheduler.runner import run_worker as worker_main

__all__ = ["main", "worker_main"]


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level)
    # uvicorn перенастраивает логирование под себя при `log_config` по умолчанию —
    # отдаём ему наш конфиг корня (см. configure_logging), поэтому log_config=None.
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
    )
