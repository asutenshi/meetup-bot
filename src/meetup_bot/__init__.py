import uvicorn

from meetup_bot.app import create_app
from meetup_bot.config import get_settings
from meetup_bot.scheduler.runner import run_worker as worker_main

__all__ = ["main", "worker_main"]


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
