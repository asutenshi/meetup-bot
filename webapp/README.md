# Web App (Telegram Mini App)

Фронтенд Mini App meetup-бота: Vite + React + TypeScript, UI на
[`@telegram-apps/telegram-ui`](https://github.com/Telegram-Mini-Apps/TelegramUI),
интеграция с Telegram — [`@telegram-apps/sdk`](https://docs.telegram-mini-apps.com/).

Каркас (TASKS.md 2.1). Реальные экраны — форма создания мероприятия и т.д. —
задачи 2.4+. Визуальный язык (карточки-секции, токены, сменяемый акцент) —
[`../docs/WEBAPP_DESIGN.md`](../docs/WEBAPP_DESIGN.md).

## Команды

| Команда | Что делает |
|---|---|
| `npm install` / `npm ci` | зависимости |
| `npm run dev` | dev-сервер Vite на `:5173`, `/api` и `/health` проксируются на бэкенд `:8080` |
| `npm run build` | `tsc -b` (типы) + `vite build` → `dist/` |
| `npm run preview` | локальный предпросмотр `dist/` |
| `npm run gen:api` | сгенерировать `src/api/schema.ts` из `./openapi.json` |

Из корня репозитория: `make webapp-install`, `make webapp-dev`, `make webapp-build`,
`make openapi`.

## Как это связано с бэкендом

- **Раздача.** `vite build` кладёт статику в `webapp/dist`. Бэкенд
  (`src/meetup_bot/app.py`, `_mount_webapp`) раздаёт её под `/app`, если каталог
  существует. Поэтому `base` в `vite.config.ts` — `/app/`. В Docker-образе сборка
  идёт отдельной стадией (`Dockerfile`, `webapp-build`).
- **Типы API.** `make openapi` дампит OpenAPI-схему FastAPI в `webapp/openapi.json`
  (в `.gitignore`) и генерит из неё `src/api/schema.ts` (коммитится).
  Перегенерировать после изменения эндпоинтов бэкенда.
- **Аутентификация.** `src/api/client.ts` кладёт `initData` в заголовок
  `X-Telegram-Init-Data`. Валидация на бэкенде — задача 2.2.

## Оформление

- `src/theme/tokens.css` — семантические токены. Поверхности/текст берутся из
  Telegram `themeParams` (проставляются в JS, `src/theme/applyThemeParams.ts`),
  фолбэки в CSS — для запуска вне Telegram.
- **Акцент — один токен `--accent`** в `tokens.css` (+ `--accent-contrast`).
  Оттенки — производные через `color-mix()`. Ни один компонент не хардкодит
  акцентный цвет. Переопределение на этапе сборки: `VITE_ACCENT=#4a63e7 npm run build`.
- Финальный акцентный цвет ещё не выбран — сейчас заглушка «нейтральный графит».
