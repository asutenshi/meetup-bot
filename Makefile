.DEFAULT_GOAL := help

.PHONY: help up down restart redeploy migrate logs logs-worker logs-all ps psql \
	webhook-set webhook-info webhook-delete health smoke \
	check lint typecheck test \
	webapp-install webapp-dev webapp-build webapp-check openapi

help: ## Показать список целей
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Собрать, поднять postgres+app, применить миграции и выставить вебхук
	docker compose up -d --build
	$(MAKE) migrate
	$(MAKE) webhook-set
	$(MAKE) health

down: ## Остановить и удалить контейнеры
	docker compose down

restart: down up ## Пересоздать окружение с нуля

redeploy: webapp-install openapi ## Обновить Web App (deps + API-типы), пересобрать образ вместе с Mini App и поднять контейнеры
	docker compose up -d --build
	$(MAKE) migrate
	$(MAKE) webhook-set
	$(MAKE) health

migrate: ## Применить миграции Alembic внутри контейнера app
	docker compose exec app uv run alembic upgrade head

logs: ## Логи app в реальном времени (Ctrl+C для выхода)
	docker compose logs -f app

logs-worker: ## Логи worker-процесса напоминаний в реальном времени
	docker compose logs -f worker

logs-all: ## Логи всех сервисов в реальном времени
	docker compose logs -f

ps: ## Статус контейнеров
	docker compose ps

psql: ## Подключиться к БД psql внутри контейнера postgres
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

webhook-set: ## Выставить вебхук на PUBLIC_BASE_URL из .env
	uv run python scripts/set_webhook.py set

webhook-info: ## Посмотреть текущий статус вебхука
	uv run python scripts/set_webhook.py info

webhook-delete: ## Снять вебхук (вернуться к getUpdates)
	uv run python scripts/set_webhook.py delete

health: ## Дождаться и проверить GET /health локально
	curl --silent --show-error --fail --retry 5 --retry-delay 1 --retry-connrefused \
		http://localhost:8080/health && echo

smoke: ## Разовая проверка связи с Telegram Bot API (BOT_TOKEN/TEST_CHAT_ID из .env)
	uv run python scripts/smoke_test_bot.py

webapp-install: ## Установить зависимости Web App (webapp/)
	cd webapp && npm ci

webapp-dev: ## Dev-сервер Vite (нужен запущенный бэкенд на :8080 для /api и /health)
	cd webapp && npm run dev

webapp-build: ## Собрать Web App в webapp/dist (её раздаёт бэкенд под /app)
	cd webapp && npm run build

webapp-check: ## Проверки Web App как в CI (tsc + vite build)
	cd webapp && npm run build

openapi: ## Пересобрать webapp/src/api/schema.ts из OpenAPI-схемы FastAPI
	uv run python scripts/dump_openapi.py webapp/openapi.json
	cd webapp && npm run gen:api

check: lint typecheck test ## Прогнать тот же набор проверок, что в CI перед PR

lint: ## ruff check
	uv run ruff check .

typecheck: ## mypy
	uv run mypy src

test: ## pytest
	uv run pytest
