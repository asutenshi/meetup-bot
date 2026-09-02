/**
 * Навигация между экранами Web App без перезагрузки (задача 2.9.1).
 *
 * Точки входа задают начальный экран через query-параметры URL кнопки
 * (`?project=…&event=…`, см. `services/webapp_url.py`): кнопка-меню бота ведёт на
 * хаб (без параметров), ответ на `/new_event` / `/edit_event` — сразу на форму.
 * Экран мероприятия — только навигационный (тап по строке списка на хабе), своей
 * точки входа по URL у него нет: `?project=&event=` при заходе извне по-прежнему
 * открывает форму редактирования (`/edit_event`). Экран настроек проекта (задача
 * 4.5) — тоже чисто навигационный (кнопка в секции проекта на хабе,
 * owner/admin), URL несёт только `?project=` для `apiFetch`.
 *
 * Экран дальше держим в состоянии React (стек вью), а адресную строку лишь
 * подтягиваем под текущий экран через `history.replaceState`, чтобы `apiFetch`
 * по-прежнему читал `project` из `window.location` (`api/client.ts`). На History
 * API как на источник навигации не опираемся: во встроенном вебвью Telegram
 * (особенно на десктопе) `popstate` ведёт себя неодинаково.
 *
 * Отдельная точка входа — `startapp`-ссылка под групповым анонсом
 * (`t.me/<bot>/<app>?startapp=<invite_payload>_<eventId>`, кнопка «Подробности
 * мероприятия»): контекст приходит не в URL, а в `tgWebAppStartParam` launch-
 * параметров (`telegram/init.ts::getStartParam`). Такой заход открывает экран
 * мероприятия поверх хаба (`parseInitialStack`), чтобы «назад» вёл на хаб.
 */

export type View =
  | { name: 'hub' }
  | { name: 'form'; project: string; eventId: number | null }
  | { name: 'event'; project: string; eventId: number }
  | { name: 'attendance'; project: string; eventId: number }
  | { name: 'settings'; project: string };

/** Базовый путь Mini App (`/app/`), совпадает с `base` в vite.config.ts. */
const BASE = import.meta.env.BASE_URL;

/** URL адресной строки для экрана — тот же контракт параметров, что у кнопок бота.
 *  Нужен только чтобы `apiFetch` видел `?project=`; экран мероприятия и форма
 *  редактирования дают одинаковый URL — на источник навигации мы его не берём. */
export function viewUrl(view: View, base: string = BASE): string {
  if (view.name === 'hub') {
    return base;
  }
  const params = new URLSearchParams({ project: view.project });
  if (view.name === 'attendance') {
    params.set('attendance', String(view.eventId));
  } else if (view.name !== 'settings' && view.eventId !== null) {
    params.set('event', String(view.eventId));
  }
  return `${base}?${params.toString()}`;
}

function positiveInt(raw: string | null): number | null {
  const value = raw ? Number(raw) : NaN;
  return Number.isInteger(value) && value > 0 ? value : null;
}

/** Разбор начального экрана из query-строки (`window.location.search`). */
export function parseView(search: string): View {
  const params = new URLSearchParams(search);
  const project = params.get('project')?.trim();
  if (!project) {
    return { name: 'hub' };
  }
  // Кнопка из `/attendance` (задача 3.1): `?project=&attendance=<id>` — экран
  // постфактум-корректировки RSVP, отдельная точка входа помимо формы.
  const attendanceId = positiveInt(params.get('attendance'));
  if (attendanceId !== null) {
    return { name: 'attendance', project, eventId: attendanceId };
  }
  return {
    name: 'form',
    project,
    eventId: positiveInt(params.get('event')),
  };
}

/**
 * Разбор `startapp`-параметра `<invite_payload>_<eventId>` (кнопка «Подробности
 * мероприятия» под групповым анонсом) в экран мероприятия. `null`, если формат
 * не подходит. Режем по последнему `_`: `invite_payload` сам может содержать
 * `_`/`-`, а `eventId` — только цифры.
 */
export function parseStartParam(
  startParam: string | undefined,
): Extract<View, { name: 'event' }> | null {
  if (!startParam) {
    return null;
  }
  const sep = startParam.lastIndexOf('_');
  if (sep <= 0) {
    return null;
  }
  const project = startParam.slice(0, sep);
  const eventId = positiveInt(startParam.slice(sep + 1));
  if (!project || eventId === null) {
    return null;
  }
  return { name: 'event', project, eventId };
}

/**
 * Начальный стек экранов. Обычно — один экран, разобранный из query-строки
 * (кнопки бота кладут контекст в URL). Для входа по `startapp`-ссылке под
 * анонсом (контекст в `startParam`, не в URL, и `?project=` в URL нет) — пара
 * `[хаб, экран мероприятия]`, чтобы кнопка «назад» вела на хаб.
 */
export function parseInitialStack(
  search: string,
  startParam: string | undefined,
): View[] {
  const deep = parseStartParam(startParam);
  if (deep && !new URLSearchParams(search).get('project')) {
    return [{ name: 'hub' }, deep];
  }
  return [parseView(search)];
}
