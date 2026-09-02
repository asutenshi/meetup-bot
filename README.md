# meetup-bot

Telegram-бот для системных встреч дружеской компании: снимает с людей рутину
организации встреч и вовремя напоминает тем, кто давно не появлялся.

Продукт и архитектура задокументированы отдельно:

- [`docs/CONCEPT.md`](./docs/CONCEPT.md) — проблема, ключевые решения, скоуп MVP и backlog.
- [`docs/TZ.md`](./docs/TZ.md) — технический стек, модель данных, архитектура, roadmap.

## Стек

Python 3.12+ (aiogram, FastAPI, SQLAlchemy 2.0 async, APScheduler), PostgreSQL,
управление зависимостями и запуск — [uv](https://docs.astral.sh/uv/). Web App
(Telegram Mini App) — React + TypeScript + Vite, в директории [`webapp/`](./webapp).

## Разработка

Требуется установленный [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv sync                 # установить зависимости (включая dev-группу)
cp .env.example .env    # заполнить BOT_TOKEN и остальные переменные
uv run pytest           # тесты
uv run ruff check .     # линтер
uv run mypy src         # типы
```

### Миграции БД

`DATABASE_URL` (из `.env`, экспортировать в окружение перед вызовом `alembic`
или использовать `docker compose exec app ...`).

```bash
uv run alembic upgrade head                        # применить миграции
uv run alembic revision --autogenerate -m "message" # сгенерировать новую после изменения моделей
```

## Запуск через Docker Compose

```bash
cp .env.example .env    # заполнить переменные окружения
docker compose up --build
```

## Логи

Оба режима (`app` и `worker`) пишут структурированные JSON-логи по строке на
событие в stdout — по одному объекту `{"ts","level","logger","message", ...}`,
доп. поля события идут верхним уровнем. Порог — `LOG_LEVEL` (по умолчанию `INFO`).
Ротацию держит Docker (`json-file`, `max-size=10m`, `max-file=5`, см.
`docker-compose.yml`). Обязательные к логированию события — TZ §6.2: ошибки
вызовов Bot API (включая `403 bot was blocked`), провалы валидации `initData`,
необработанные исключения хендлеров бота и ручек API.

## Структура проекта

```
src/meetup_bot/
├── bot/         # хендлеры и клавиатуры aiogram
├── api/         # FastAPI-роуты для Web App
├── db/          # модели SQLAlchemy, сессии, Alembic-миграции
└── scheduler/   # APScheduler-джобы напоминаний (отдельная точка входа worker)
webapp/          # Telegram Mini App (React + TypeScript + Vite)
tests/           # тесты
```

## Статус

Проект в разработке по этапам, описанным в [`docs/TZ.md`, раздел 7](./docs/TZ.md#7-этапы-реализации-roadmap).
Изменения проходят через Pull Request.
