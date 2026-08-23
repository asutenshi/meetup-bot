import uvicorn

from meetup_bot.app import create_app
from meetup_bot.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
