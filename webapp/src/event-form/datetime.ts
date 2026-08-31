/*
  Дата и время в форме вводятся двумя полями: `<input type="date">` под нашей
  строкой-пикером (`PickerRow`) и время двумя `<select>` (`TimeSelect`). Внутри
  формы склеиваем их в значение `datetime-local` (`combineLocal`) и в ISO с
  зоной устройства организатора на отправке (`toIso`); при предзаполнении —
  обратный путь (`toLocalInput` → `splitLocal`).
*/

const MONTHS = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
] as const;

/** `Date.getDay()` → короткое имя дня недели (0 — воскресенье). */
const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'] as const;

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const LOCAL_RE = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/;

/** Шаг минут в выпадашке времени. */
const MINUTE_STEP = 5;

/** Часы для `<select>` времени — всегда 24-часовой формат, `00`…`23`. */
export const HOUR_OPTIONS: readonly string[] = Array.from({ length: 24 }, (_, i) =>
  String(i).padStart(2, '0'),
);

/**
 * Минуты для `<select>` времени: `00`, `05`, … `55`. Если текущее значение не
 * кратно шагу (мероприятие создано раньше нативным `datetime-local`) — добавляем
 * его в список, чтобы `<select>` не «съел» время при редактировании.
 */
export function minuteOptions(current?: string): string[] {
  const base = Array.from({ length: 60 / MINUTE_STEP }, (_, i) =>
    String(i * MINUTE_STEP).padStart(2, '0'),
  );
  if (current && /^\d{2}$/.test(current) && !base.includes(current)) {
    return [...base, current].sort();
  }
  return base;
}

/** `datetime-local` → ISO-строка с зоной устройства организатора. */
export function toIso(value: string): string {
  return new Date(value).toISOString();
}

/** ISO-строка → значение `datetime-local` в зоне устройства (для предзаполнения). */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** Значение `datetime-local` → части для отдельных полей даты и времени. */
export function splitLocal(local: string): { date: string; time: string } {
  const match = LOCAL_RE.exec(local);
  return match ? { date: match[1], time: match[2] } : { date: '', time: '' };
}

/**
 * Части полей даты и времени → значение `datetime-local`. Нет даты — пустая
 * строка (нечего отправлять); дата без времени — начало суток.
 */
export function combineLocal(date: string, time: string): string {
  if (!date) return '';
  return `${date}T${time || '00:00'}`;
}

/**
 * `2026-09-14` → «14 сентября 2026, сб» — подпись для строки-пикера. Парсим
 * сами (формат фиксирован), отсекаем переполнение («2026-02-30»). Пусто/мусор →
 * пустая строка.
 */
export function formatDate(date: string): string {
  const match = DATE_RE.exec(date);
  if (!match) return '';
  const [, year, month, day] = match;
  const monthIndex = Number(month) - 1;
  const parsed = new Date(Number(year), monthIndex, Number(day));
  if (
    parsed.getFullYear() !== Number(year) ||
    parsed.getMonth() !== monthIndex ||
    parsed.getDate() !== Number(day)
  ) {
    return '';
  }
  return `${Number(day)} ${MONTHS[monthIndex]} ${year}, ${WEEKDAYS[parsed.getDay()]}`;
}
