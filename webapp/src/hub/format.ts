import { formatDate } from '../event-form/datetime';

/**
 * ISO-строка мероприятия → «14 сентября 2026, сб · 18:00» в зоне устройства.
 * Дату форматируем общим `formatDate`, время добавляем 24-часовым.
 */
export function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number): string => String(n).padStart(2, '0');
  const date = formatDate(
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
  );
  return `${date} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
