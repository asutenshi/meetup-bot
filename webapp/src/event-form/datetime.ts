/*
  Работа со значениями `<input type="datetime-local">`: строка вида
  `2026-09-14T18:00` без зоны. ISO с зоной устройства организатора получаем на
  отправке (`toIso`), обратно раскладываем на предзаполнении (`toLocalInput`).
  `formatDateTime` — человекочитаемая подпись для PickerRow.
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

const LOCAL_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

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

/**
 * Значение `datetime-local` → подпись для строки-пикера, например
 * «14 сентября 2026, сб · 18:00». Парсим строку сами (формат фиксирован), без
 * `Intl`/повторного разбора зоны. Пустой ввод или мусор → пустая строка.
 */
export function formatDateTime(localValue: string): string {
  const match = LOCAL_RE.exec(localValue);
  if (!match) return '';
  const [, year, month, day, hh, mm] = match;
  const monthIndex = Number(month) - 1;
  const date = new Date(Number(year), monthIndex, Number(day));
  // Отсекаем переполнение («2026-13-40», «2026-02-30»): Date молча переносит на
  // следующий месяц, а нам нужен ровно тот день, что во вводе.
  if (
    date.getFullYear() !== Number(year) ||
    date.getMonth() !== monthIndex ||
    date.getDate() !== Number(day) ||
    Number(hh) > 23 ||
    Number(mm) > 59
  ) {
    return '';
  }
  return `${Number(day)} ${MONTHS[monthIndex]} ${year}, ${WEEKDAYS[date.getDay()]} · ${hh}:${mm}`;
}
