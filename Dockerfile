# --- Стадия 1: сборка Telegram Mini App (Vite → webapp/dist) ---
FROM node:22-slim AS webapp-build
WORKDIR /webapp
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build

# --- Стадия 2: Python-приложение (бот + API), раздаёт собранный Mini App ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# Собранная статика Mini App — app._mount_webapp раздаёт её под /app
COPY --from=webapp-build /webapp/dist ./webapp/dist

CMD ["meetup-bot"]
