# Web App (Telegram Mini App)

Фронтенд Mini App meetup-бота: Vite + React + TypeScript, UI на
[`@telegram-apps/telegram-ui`](https://github.com/Telegram-Mini-Apps/TelegramUI),
интеграция с Telegram — [`@telegram-apps/sdk`](https://docs.telegram-mini-apps.com/).

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

## Известные ограничения

Разобраны 2026-08. Первые два пункта закрываются одной задачей — миграцией SDK на
`@tma.js/*` (`docs/TASKS.md`, «Технический долг», сделать до 2.2). Третий —
остаётся.

- **SDK: `@telegram-apps/sdk` заморожен, надо мигрировать на `@tma.js/sdk`.**
  `@telegram-apps/sdk@3.11.8` сам не deprecated, но последняя публикация —
  2025-12-05, а его транзитивные `@telegram-apps/bridge` / `transformers` /
  `types` помечены deprecated с явным «Use @tma.js/… instead». `@tma.js/sdk@3.3.0`
  (публикация 2026-07-14) — тот же мажор 3.x и тот же API (`init`, `themeParams`,
  `viewport`, `retrieveRawInitData`). Наша поверхность SDK — 3 файла
  (`src/api/client.ts`, `src/telegram/init.ts`, `src/theme/applyThemeParams.ts`);
  миграция = смена строки импорта + замена зависимости. Пока не сделано,
  `npm install` показывает deprecation-warnings — это ожидаемо.

- **`npm audit` — 4 high severity, чинится той же миграцией.** Advisory
  `GHSA-vqpr-j7v3-hqw9` (ReDoS в `EMOJI_REGEX`) и `GHSA-5qjj-4xww-7phc` (throw в
  `flatten()`) сидят в `valibot <=1.4.1`. `@telegram-apps/bridge` пинит
  `valibot@1.0.0`, `@telegram-apps/transformers` — `1.0.0-beta.14` **точными
  версиями** и заморожены — апстрим-фикса не будет. `npm audit fix --force` =
  даунгрейд SDK до v2 (breaking API). `@tma.js/sdk@3.3.0` тянет `valibot@1.4.2`,
  проверено на чистом дереве — `npm audit` даёт 0 уязвимостей. До миграции —
  принятый риск: код фронтовый (серверу не грозит), вектор — строка
  launch-параметров, которую SDK парсит при старте Mini App.

- **React закреплён на 18, не 19 — из-за `telegram-ui`.** Причина именно в
  `@telegram-apps/telegram-ui@2.1.13` (`peerDependencies` → `react@^18.2.0`,
  последний релиз октябрь 2025, преемника в `@tma.js` нет; сам он **не**
  deprecated). SDK не мешает: `@tma.js/sdk-react` поддерживает React 17/18/19.
  Из telegram-ui используется только `AppRoot` + `dist/styles.css` — путь к
  React 19 лежит через отказ от telegram-ui в пользу своих токен-компонентов
  (`docs/WEBAPP_DESIGN.md` уже закладывает свою мини-библиотеку). Решение
  отложено до экранов 2.5/2.7, когда будет видно, сколько telegram-ui реально
  нужно. React 18.3.1 стабилен и патчится — для MVP не блокер.

## Оформление

- `src/theme/tokens.css` — семантические токены. Поверхности/текст берутся из
  Telegram `themeParams` (проставляются в JS, `src/theme/applyThemeParams.ts`),
  фолбэки в CSS — для запуска вне Telegram.
- **Акцент — один токен `--accent`** в `tokens.css` (+ `--accent-contrast`).
  Оттенки — производные через `color-mix()`. Ни один компонент не хардкодит
  акцентный цвет. Переопределение на этапе сборки: `VITE_ACCENT=#4a63e7 npm run build`.
- Финальный акцентный цвет ещё не выбран — сейчас заглушка «нейтральный графит».
