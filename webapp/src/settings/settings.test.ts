import { describe, expect, it } from 'vitest';

import { parseFieldError, SettingFieldError } from '../api/settings';

describe('parseFieldError', () => {
  it('объектный detail → SettingFieldError с полем и сообщением', () => {
    const err = parseFieldError({
      detail: {
        error: 'invalid_setting',
        field: 'reminder_send_hour',
        message: 'reminder_send_hour: нужно целое число от 0 до 23.',
      },
    });
    expect(err).toBeInstanceOf(SettingFieldError);
    expect(err?.field).toBe('reminder_send_hour');
    expect(err?.message).toContain('от 0 до 23');
  });

  it('строковый detail (FastAPI 401/403) → null', () => {
    expect(parseFieldError({ detail: 'not_an_admin' })).toBeNull();
  });

  it('detail без field/message → null', () => {
    expect(parseFieldError({ detail: { error: 'oops' } })).toBeNull();
  });

  it('не объект → null', () => {
    expect(parseFieldError(null)).toBeNull();
    expect(parseFieldError('boom')).toBeNull();
  });
});
