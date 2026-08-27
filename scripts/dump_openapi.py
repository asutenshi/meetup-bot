"""Дамп OpenAPI-схемы FastAPI в файл — источник для генерации TS-типов
фронтенда через openapi-typescript (см. Makefile: `make openapi`).

    uv run python scripts/dump_openapi.py [путь]

По умолчанию пишет в webapp/openapi.json (файл в .gitignore, коммитится
только результат — webapp/src/api/schema.ts).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from meetup_bot.app import create_app
from meetup_bot.config import Settings


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "webapp/openapi.json")
    settings = Settings(
        bot_token="0:openapi-dump",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
    )
    app = create_app(settings)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
    print(f"OpenAPI → {out}")


if __name__ == "__main__":
    main()
