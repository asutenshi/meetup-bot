"""Разовая ручная проверка приёма вебхуков Telegram через Tailscale Funnel.

Не часть приложения — минимальный HTTP-приёмник для проверки входящего
доступа (Telegram -> интернет -> Tailscale Funnel -> контейнер) до начала
разработки. Не привязан к CMD в Dockerfile и не входит в roadmap TASKS.md.

Путь вебхука включает BOT_TOKEN как секрет в URL — стандартный приём,
чтобы посторонние запросы на публичный адрес не путались с реальными
апдейтами Telegram.

Использование (внутри контейнера/окружения с доступом к порту,
проброшенному через Tailscale Funnel):
    uv run python scripts/smoke_webhook_server.py

Слушает 0.0.0.0:8080. Порт задаётся через SMOKE_WEBHOOK_PORT (по умолчанию 8080).
"""

import os
from datetime import UTC, datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv()

token = os.environ.get("BOT_TOKEN")
if not token:
    raise SystemExit("BOT_TOKEN не задан (проверьте .env)")

app = FastAPI()
webhook_path = f"/webhook/{token}"


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}


@app.post(webhook_path)
async def webhook(request: Request) -> dict[str, str]:
    body = await request.json()
    print(f"[{datetime.now(UTC).isoformat()}] получен апдейт от Telegram:")
    print(body)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("SMOKE_WEBHOOK_PORT", "8080"))
    print(f"Слушаю на 0.0.0.0:{port}, путь вебхука: {webhook_path}")
    uvicorn.run(app, host="0.0.0.0", port=port)
