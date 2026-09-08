import { describe, expect, it } from 'vitest';

import { isStaleSession, loadErrorText } from './events';

describe('isStaleSession', () => {
  it('распознаёт коды устаревшей initData', () => {
    expect(isStaleSession('expired')).toBe(true);
    expect(isStaleSession('clock_skew')).toBe(true);
  });

  it('прочие коды — не устаревшая сессия', () => {
    expect(isStaleSession('network')).toBe(false);
    expect(isStaleSession('http_500')).toBe(false);
    expect(isStaleSession('invalid_signature')).toBe(false);
  });
});

describe('loadErrorText', () => {
  it('для устаревшей сессии — инструкция закрыть Mini App, без кода', () => {
    const text = loadErrorText('expired');
    expect(text).toContain('Полностью закройте');
    expect(text).not.toContain('expired');
  });

  it('для clock_skew — тот же текст про закрытие', () => {
    expect(loadErrorText('clock_skew')).toBe(loadErrorText('expired'));
  });

  it('для сетевой/серверной ошибки — общий текст с кодом', () => {
    expect(loadErrorText('http_500')).toBe(
      'Попробуйте переоткрыть Mini App. Код: http_500',
    );
  });
});
