import { describe, expect, it } from 'vitest';

import { parseInitialStack, parseStartParam, parseView, viewUrl } from './navigation';

describe('parseView', () => {
  it('без параметров → хаб', () => {
    expect(parseView('')).toEqual({ name: 'hub' });
  });

  it('project без event → форма создания', () => {
    expect(parseView('?project=alpha')).toEqual({
      name: 'form',
      project: 'alpha',
      eventId: null,
    });
  });

  it('project + event → форма редактирования', () => {
    expect(parseView('?project=alpha&event=42')).toEqual({
      name: 'form',
      project: 'alpha',
      eventId: 42,
    });
  });

  it('невалидный event → форма создания (eventId null)', () => {
    expect(parseView('?project=alpha&event=0')).toEqual({
      name: 'form',
      project: 'alpha',
      eventId: null,
    });
    expect(parseView('?project=alpha&event=abc')).toEqual({
      name: 'form',
      project: 'alpha',
      eventId: null,
    });
  });

  it('пустой project → хаб', () => {
    expect(parseView('?project=')).toEqual({ name: 'hub' });
  });

  it('project + attendance → экран корректировки явки', () => {
    expect(parseView('?project=alpha&attendance=42')).toEqual({
      name: 'attendance',
      project: 'alpha',
      eventId: 42,
    });
  });

  it('attendance имеет приоритет над event', () => {
    expect(parseView('?project=alpha&attendance=42&event=7')).toEqual({
      name: 'attendance',
      project: 'alpha',
      eventId: 42,
    });
  });

  it('невалидный attendance → форма', () => {
    expect(parseView('?project=alpha&attendance=0')).toEqual({
      name: 'form',
      project: 'alpha',
      eventId: null,
    });
  });
});

describe('parseStartParam', () => {
  it('<invite_payload>_<eventId> → экран мероприятия', () => {
    expect(parseStartParam('xY_9-z_42')).toEqual({
      name: 'event',
      project: 'xY_9-z',
      eventId: 42,
    });
  });

  it('режет по последнему подчёркиванию', () => {
    expect(parseStartParam('a_b_c_7')).toEqual({
      name: 'event',
      project: 'a_b_c',
      eventId: 7,
    });
  });

  it.each(['', undefined, 'noseparator', 'abc_', '_42', 'abc_x', 'abc_0'])(
    'битый формат %j → null',
    (value) => {
      expect(parseStartParam(value as string | undefined)).toBeNull();
    },
  );
});

describe('parseInitialStack', () => {
  it('startapp без ?project= → [хаб, экран мероприятия]', () => {
    expect(parseInitialStack('', 'alpha_42')).toEqual([
      { name: 'hub' },
      { name: 'event', project: 'alpha', eventId: 42 },
    ]);
  });

  it('есть ?project= в URL → startapp игнорируется', () => {
    expect(parseInitialStack('?project=alpha', 'beta_9')).toEqual([
      { name: 'form', project: 'alpha', eventId: null },
    ]);
  });

  it('без startapp → один экран из query-строки', () => {
    expect(parseInitialStack('?project=alpha&event=7', undefined)).toEqual([
      { name: 'form', project: 'alpha', eventId: 7 },
    ]);
  });
});

describe('viewUrl', () => {
  const base = '/app/';

  it('хаб → базовый путь без параметров', () => {
    expect(viewUrl({ name: 'hub' }, base)).toBe('/app/');
  });

  it('форма создания → ?project=', () => {
    expect(viewUrl({ name: 'form', project: 'alpha', eventId: null }, base)).toBe(
      '/app/?project=alpha',
    );
  });

  it('форма редактирования → ?project=&event=', () => {
    expect(viewUrl({ name: 'form', project: 'alpha', eventId: 42 }, base)).toBe(
      '/app/?project=alpha&event=42',
    );
  });

  it('экран мероприятия → ?project=&event= (нужен apiFetch, не точка входа)', () => {
    expect(viewUrl({ name: 'event', project: 'alpha', eventId: 42 }, base)).toBe(
      '/app/?project=alpha&event=42',
    );
  });

  it('экран корректировки явки → ?project=&attendance=', () => {
    expect(viewUrl({ name: 'attendance', project: 'alpha', eventId: 42 }, base)).toBe(
      '/app/?project=alpha&attendance=42',
    );
  });

  it('round-trip parseView(viewUrl) сохраняет экран (точки входа: хаб, форма, явка)', () => {
    for (const view of [
      { name: 'hub' as const },
      { name: 'form' as const, project: 'p', eventId: null },
      { name: 'form' as const, project: 'p', eventId: 7 },
      { name: 'attendance' as const, project: 'p', eventId: 7 },
    ]) {
      const url = viewUrl(view, '/app/');
      const search = url.includes('?') ? url.slice(url.indexOf('?')) : '';
      expect(parseView(search)).toEqual(view);
    }
  });
});
