"""Управление вебхуком бота через Telegram Bot API — для smoke-теста.

Не часть приложения, не входит в roadmap TASKS.md. Использует BOT_TOKEN и
PUBLIC_BASE_URL из .env. URL вебхука: {PUBLIC_BASE_URL}/webhook/{BOT_TOKEN}
(должен совпадать с scripts/smoke_webhook_server.py).

Использование:
    uv run python scripts/set_webhook.py set     # выставить вебхук
    uv run python scripts/set_webhook.py info    # посмотреть текущий статус
    uv run python scripts/set_webhook.py delete  # снять вебхук (вернуться к getUpdates)
"""

import json
import os
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv


def call(api_base: str, method: str, params: dict[str, str] | None = None) -> dict:
    url = f"{api_base}/{method}"
    if params:
        url += f"?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url) as resp:
        return json.load(resp)


def main() -> None:
    load_dotenv()

    if len(sys.argv) != 2 or sys.argv[1] not in {"set", "info", "delete"}:
        sys.exit(f"Использование: {sys.argv[0]} set|info|delete")
    command = sys.argv[1]

    token = os.environ.get("BOT_TOKEN")
    if not token:
        sys.exit("BOT_TOKEN не задан (проверьте .env)")

    api_base = f"https://api.telegram.org/bot{token}"

    if command == "set":
        base_url = os.environ.get("PUBLIC_BASE_URL")
        if not base_url or base_url == "https://example.com":
            sys.exit("PUBLIC_BASE_URL не задан или не заменён в .env")
        webhook_url = f"{base_url.rstrip('/')}/webhook/{token}"
        print(f"webhook_url: {webhook_url}")
        result = call(api_base, "setWebhook", {"url": webhook_url})
    elif command == "delete":
        result = call(api_base, "deleteWebhook")
    else:
        result = call(api_base, "getWebhookInfo")

    print(result)


if __name__ == "__main__":
    main()
