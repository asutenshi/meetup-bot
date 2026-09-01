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
