# Web App (Telegram Mini App)

Фронтенд Mini App meetup-бота: Vite + React + TypeScript, UI на
[`@telegram-apps/telegram-ui`](https://github.com/Telegram-Mini-Apps/TelegramUI),
интеграция с Telegram — [`@tma.js/sdk`](https://docs.telegram-mini-apps.com/).

Каркас (TASKS.md 2.1). Кнопка открытия Mini App из лички — задача 2.2, реальные
экраны (форма создания мероприятия и т.д.) — задачи 2.5+. Визуальный язык
(карточки-секции, токены, сменяемый акцент) —
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
  `X-Telegram-Init-Data`. Валидация на бэкенде — задача 2.3.

## SDK: `@tma.js/sdk`

Интеграция с Telegram — `@tma.js/sdk@3.3.0`. Раньше был `@telegram-apps/sdk@3.11.8`,
но он заморожен (последняя публикация 2025-12-05), а его транзитивные
`@telegram-apps/bridge` / `transformers` / `types` помечены deprecated с явным
«Use @tma.js/… instead» и точечными версиями пинили уязвимый `valibot` без шанса
на апстрим-фикс. `@tma.js/sdk` — от того же мейнтейнера, тот же мажор 3.x, тянет
`valibot@1.4.2` → `npm audit` даёт 0 уязвимостей.

API v3.3 **не** дословно совпадает с `@telegram-apps/sdk`:

- `themeParams.mountSync()` → единый `themeParams.mount()` (синхронный,
  с `.isAvailable()`);
- ключи темы читаются сигнал-геттерами инстанса (`themeParams.secondaryBgColor()`,
  `themeParams.bgColor()` и т.д.), а не из camelCase-полей `themeParams.state()`
  (сам `state()` теперь отдаёт snake_case-ключи Telegram);
- `init`, `viewport.mount`/`viewport.expand`, `retrieveRawInitData`,
  `themeParams.isDark()`/`isMounted()`/`state.sub()` — без изменений.

Поверхность SDK — 3 файла (`src/api/client.ts`, `src/telegram/init.ts`,
`src/theme/applyThemeParams.ts`).

## Известные ограничения

- **React закреплён на 18, не 19 — из-за `telegram-ui`.** Причина именно в
  `@telegram-apps/telegram-ui@2.1.13` (`peerDependencies` → `react@^18.2.0`,
  последний релиз октябрь 2025, преемника в `@tma.js` нет; сам он **не**
  deprecated). SDK не мешает: `@tma.js/sdk-react` поддерживает React 17/18/19.
  Из telegram-ui используется только `AppRoot` + `dist/styles.css` — путь к
  React 19 лежит через отказ от telegram-ui в пользу своих токен-компонентов
  (`docs/WEBAPP_DESIGN.md` уже закладывает свою мини-библиотеку). Решение
  отложено до экранов 2.5/2.7, когда будет видно, сколько telegram-ui реально
  нужно. React 18.3.1 стабилен и патчится — для MVP не блокер.

- **TypeScript закреплён на 5.9, не 7 — из-за `openapi-typescript`.**
  `openapi-typescript@7.13.0` (`peerDependencies` → `typescript: ^5.x`) при
  сборке `src/api/schema.ts` дёргает `ts.factory` из compiler API; нативный
  `tsc` v7 этот API не отдаёт — `npm run gen:api` падает
  (`Cannot read properties of undefined (reading 'createKeywordTypeNode')`).
  Сам `tsc -b` и `vite build` под TS 7 работают. Ждём релиз `openapi-typescript`
  с поддержкой TS 7, тогда бампаем.

Инструментарий сборки — **Vite 8** (бандлер Rolldown) + `@vitejs/plugin-react` 6
(трансформ через oxc, не Babel). Требует Node `>=22.12` — CI и `Dockerfile`
используют тег `node:22`/`node-version: 22` (последний 22.x), проходит.

## Оформление

- `src/theme/tokens.css` — семантические токены. Поверхности/текст берутся из
  Telegram `themeParams` (проставляются в JS, `src/theme/applyThemeParams.ts`),
  фолбэки в CSS — для запуска вне Telegram.
- **Акцент — один токен `--accent`** в `tokens.css` (+ `--accent-contrast`).
  Оттенки — производные через `color-mix()`. Ни один компонент не хардкодит
  акцентный цвет. Переопределение на этапе сборки: `VITE_ACCENT=#4a63e7 npm run build`.
- Финальный акцентный цвет ещё не выбран — сейчас заглушка «нейтральный графит».
