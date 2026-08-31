import { describe, expect, it } from 'vitest';

import {
  combineLocal,
  formatDate,
  HOUR_OPTIONS,
  minuteOptions,
  splitLocal,
  toIso,
  toLocalInput,
} from './datetime';

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

describe('splitLocal / combineLocal', () => {
  it('splitLocal делит datetime-local на дату и время', () => {
    expect(splitLocal('2026-09-14T18:00')).toEqual({ date: '2026-09-14', time: '18:00' });
    expect(splitLocal('2026-09-14T18:00:00')).toEqual({ date: '2026-09-14', time: '18:00' });
  });

  it('splitLocal на пустой/битой строке → пустые части', () => {
    expect(splitLocal('')).toEqual({ date: '', time: '' });
    expect(splitLocal('2026-09-14')).toEqual({ date: '', time: '' });
  });

  it('combineLocal склеивает дату и время', () => {
    expect(combineLocal('2026-09-14', '18:00')).toBe('2026-09-14T18:00');
  });

  it('combineLocal без даты → пустая строка, без времени → начало суток', () => {
    expect(combineLocal('', '18:00')).toBe('');
    expect(combineLocal('2026-09-14', '')).toBe('2026-09-14T00:00');
  });

  it('split ∘ combine — тождество для валидного значения', () => {
    const { date, time } = splitLocal('2026-01-05T09:07');
    expect(combineLocal(date, time)).toBe('2026-01-05T09:07');
  });
});

describe('время: опции select', () => {
  it('часы — 24 штуки, 24-часовой формат', () => {
    expect(HOUR_OPTIONS).toHaveLength(24);
    expect(HOUR_OPTIONS[0]).toBe('00');
    expect(HOUR_OPTIONS[14]).toBe('14');
    expect(HOUR_OPTIONS[23]).toBe('23');
  });

  it('минуты по умолчанию — шаг 5', () => {
    expect(minuteOptions()).toEqual([
      '00', '05', '10', '15', '20', '25', '30', '35', '40', '45', '50', '55',
    ]);
  });

  it('нестандартную минуту добавляем в список по порядку', () => {
    const opts = minuteOptions('37');
    expect(opts).toContain('37');
    expect(opts).toEqual([...opts].sort());
    expect(opts).toHaveLength(13);
  });
});

describe('formatDate', () => {
  it('форматирует дату с днём недели', () => {
    // 14 сентября 2026 — понедельник.
    expect(formatDate('2026-09-14')).toBe('14 сентября 2026, пн');
  });

  it('пустой ввод, время и переполнение → пустая строка', () => {
    expect(formatDate('')).toBe('');
    expect(formatDate('2026-09-14T18:00')).toBe('');
    expect(formatDate('2026-02-30')).toBe('');
    expect(formatDate('2026-13-01')).toBe('');
  });
});
