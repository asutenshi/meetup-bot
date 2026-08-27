"""Сборка URL Telegram Mini App с контекстом проекта.

Mini App раздаётся бэкендом под путём `/app` того же origin, что и вебхук
(TZ §3.8; `app._mount_webapp`). Базовый адрес этого origin — `public_base_url`
в конфиге; без него бот не строит `web_app`-кнопки.

Контекст проекта передаётся query-параметром `project` (= `Project.invite_payload`):
из группы `initData` не даёт `chat_id`, поэтому проект бэкенд узнаёт из этого
параметра и сверяет его с `ProjectMembership` пользователя (TZ §3.2 п.4, §3.8).
"""

from urllib.parse import urlencode

_WEBAPP_PATH = "/app/"


def build_web_app_url(public_base_url: str, *, project_payload: str) -> str:
    """`{public_base_url}/app/?project=<invite_payload>` — URL для
    `WebAppInfo(url=...)` inline-кнопки, открывающей форму Mini App в контексте
    конкретного проекта."""
    base = public_base_url.rstrip("/")
    query = urlencode({"project": project_payload})
    return f"{base}{_WEBAPP_PATH}?{query}"
