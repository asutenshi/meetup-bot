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


def build_hub_url(public_base_url: str) -> str:
    """`{public_base_url}/app/` — фиксированный URL домашнего экрана-хаба без
    контекста (задача 2.9.1). На него ведёт глобальная кнопка-меню бота
    (`setChatMenuButton` → `MenuButtonWebApp`); проект хаб разрешает сам по
    `initData` (TZ §3.8, блок «Домашний экран-хаб»)."""
    return f"{public_base_url.rstrip('/')}{_WEBAPP_PATH}"


def build_web_app_url(
    public_base_url: str,
    *,
    project_payload: str,
    event_id: int | None = None,
    attendance_event_id: int | None = None,
) -> str:
    """`{public_base_url}/app/?project=<invite_payload>` — URL для
    `WebAppInfo(url=...)` inline-кнопки, открывающей форму Mini App в контексте
    конкретного проекта.

    `event_id` задан (кнопка из `/edit_event`) → добавляется `&event=<id>`, и
    фронтенд открывает форму редактирования этого мероприятия вместо создания.
    `attendance_event_id` задан (кнопка из `/attendance`) → добавляется
    `&attendance=<id>`, и фронтенд открывает экран постфактум-корректировки RSVP
    (задача 3.1)."""
    base = public_base_url.rstrip("/")
    params: dict[str, str | int] = {"project": project_payload}
    if event_id is not None:
        params["event"] = event_id
    if attendance_event_id is not None:
        params["attendance"] = attendance_event_id
    return f"{base}{_WEBAPP_PATH}?{urlencode(params)}"


def build_event_start_param(*, invite_payload: str, event_id: int) -> str:
    """`<invite_payload>_<event_id>` — значение `startapp` для ссылки
    `t.me/<bot>/<app>?startapp=…`, открывающей экран мероприятия в Web App прямо
    из группового анонса (TZ §3.8, §4.3).

    Оба сегмента укладываются в допустимый для `startapp` алфавит
    (`[A-Za-z0-9_-]`, ≤ 512): `invite_payload` — это `secrets.token_urlsafe`
    (base64url), `event_id` — только цифры. Разбирается [[parse_event_start_param]]."""
    return f"{invite_payload}_{event_id}"


def parse_event_start_param(param: str) -> tuple[str, int] | None:
    """Разбирает значение, собранное [[build_event_start_param]], в
    `(invite_payload, event_id)`. `None`, если формат не подходит.

    Режем справа (`rsplit("_", 1)`): `invite_payload` сам может содержать `_`/`-`,
    а `event_id` — только цифры."""
    invite_payload, _, raw_event_id = param.rpartition("_")
    if not invite_payload or not raw_event_id.isdigit():
        return None
    return invite_payload, int(raw_event_id)


def build_event_startapp_url(
    *, bot_username: str, short_name: str, invite_payload: str, event_id: int
) -> str:
    """`https://t.me/<bot_username>/<short_name>?startapp=<invite_payload>_<event_id>`
    — URL для inline-кнопки под групповым анонсом: открывает Mini App сразу на
    экране мероприятия (TZ §3.8, §4.3). `short_name` — зарегистрированное в
    BotFather короткое имя Mini App (`Settings.webapp_short_name`)."""
    start_param = build_event_start_param(
        invite_payload=invite_payload, event_id=event_id
    )
    return f"https://t.me/{bot_username}/{short_name}?startapp={start_param}"
