import { describe, expect, it } from 'vitest';

import { parseView, viewUrl } from './navigation';

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

  it('round-trip parseView(viewUrl) сохраняет экран (точки входа: хаб и форма)', () => {
    for (const view of [
      { name: 'hub' as const },
      { name: 'form' as const, project: 'p', eventId: null },
      { name: 'form' as const, project: 'p', eventId: 7 },
    ]) {
      const url = viewUrl(view, '/app/');
      const search = url.includes('?') ? url.slice(url.indexOf('?')) : '';
      expect(parseView(search)).toEqual(view);
    }
  });
});
