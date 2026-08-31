import { describe, expect, it } from 'vitest';

import { formatDateTime, toIso, toLocalInput } from './datetime';

describe('toLocalInput / toIso', () => {
  it('раскладывает ISO обратно в значение datetime-local в зоне устройства', () => {
    const iso = toIso('2026-09-14T18:00');
    expect(toLocalInput(iso)).toBe('2026-09-14T18:00');
  });

  it('дополняет одно­значные месяц/день/час нулём', () => {
    const iso = toIso('2026-01-05T09:07');
    expect(toLocalInput(iso)).toBe('2026-01-05T09:07');
  });
});

describe('formatDateTime', () => {
  it('форматирует дату и время с днём недели', () => {
    // 14 сентября 2026 — понедельник.
    expect(formatDateTime('2026-09-14T18:00')).toBe('14 сентября 2026, пн · 18:00');
  });

  it('принимает значение с секундами', () => {
    expect(formatDateTime('2026-09-14T18:00:00')).toBe('14 сентября 2026, пн · 18:00');
  });

  it('пустой ввод и мусор → пустая строка', () => {
    expect(formatDateTime('')).toBe('');
    expect(formatDateTime('завтра')).toBe('');
    expect(formatDateTime('2026-13-40T99:99')).toBe('');
  });
});
