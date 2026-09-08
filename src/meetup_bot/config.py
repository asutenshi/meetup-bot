from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    database_url: str
    public_base_url: str | None = None
    # Короткое имя Telegram Mini App, зарегистрированное в BotFather
    # (`/newapp` → short name). Нужно для ссылок `t.me/<bot>/<short_name>?startapp=…`
    # — по такой кнопке под групповым анонсом открывается экран мероприятия в
    # Web App (TZ §3.8, §4.3). Без него кнопка «Подробности» под анонсом не
    # добавляется.
    webapp_short_name: str | None = None
    host: str = "0.0.0.0"
    port: int = 8080
    # Каталог со сборкой Web App (Vite → webapp/dist). Раздаётся под /app,
    # если каталог существует; иначе бэкенд поднимается без Mini App
    # (dev, CI без node). См. app._mount_webapp.
    webapp_dist_dir: str = "webapp/dist"
    # Возраст `auth_date` в Telegram Web App `initData` (секунды), после которого
    # `initData` считается просроченной (TZ §3.2). По умолчанию это лишь порог
    # для WARNING в лог — запрос всё равно проходит (см. ниже). Переопределяется
    # env `WEBAPP_INIT_DATA_MAX_AGE`; `0` — не проверять возраст вовсе.
    webapp_init_data_max_age: int = 604800
    # Отклонять ли просроченную по возрасту `initData` (`401 expired`). По
    # умолчанию НЕТ: настоящая аутентификация — HMAC-подпись, а `auth_date` лишь
    # ограничивает окно replay; при этом Telegram-клиенты (в первую очередь
    # Desktop) кэшируют launch-параметры и не обновляют `auth_date` даже между
    # полными перезапусками — жёсткий отказ оставлял бы организатора без доступа
    # без единого способа починить. `true` — вернуть строгий режим (env
    # `WEBAPP_INIT_DATA_REJECT_STALE`).
    webapp_init_data_reject_stale: bool = False
    # Интервал периодического прохода worker-процесса напоминаний, минуты
    # (TZ §3.4: точность до минуты не нужна, рекомендация 15–30 мин). См.
    # meetup_bot.scheduler.
    worker_poll_interval_minutes: int = 20
    # Порог корневого логгера (`DEBUG`/`INFO`/`WARNING`/...). Вывод — JSON в
    # stdout, ротация на стороне Docker (TZ §6.2). См. meetup_bot.logging_config.
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
