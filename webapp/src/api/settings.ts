import { apiFetch } from './client';
import { ApiError, readError } from './events';
import type { components } from './schema';

export type ProjectSettingsResponse = components['schemas']['ProjectSettingsResponse'];
export type ProjectSettingsUpdate = components['schemas']['ProjectSettingsUpdate'];
export type SettingField = components['schemas']['SettingField'];

/**
 * Ошибка валидации одного поля формы: `PUT` при неверном значении отвечает `422`
 * с объектным `detail` `{error, field, message}` (см. `api/project_settings.py`).
 * Экран показывает `message` под полем `field`.
 */
export class SettingFieldError extends Error {
  readonly field: string;

  constructor(field: string, message: string) {
    super(message);
    this.name = 'SettingFieldError';
    this.field = field;
  }
}

/** Текущие значения настроек проекта + описание полей формы (GET). */
export async function fetchProjectSettings(
  payload: string,
): Promise<ProjectSettingsResponse> {
  const response = await apiFetch(`/projects/${encodeURIComponent(payload)}/settings`);
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as ProjectSettingsResponse;
}

/** Сохранить всю форму настроек (PUT). Бросает `SettingFieldError` при 422. */
export async function saveProjectSettings(
  payload: string,
  body: ProjectSettingsUpdate,
): Promise<ProjectSettingsResponse> {
  const response = await apiFetch(`/projects/${encodeURIComponent(payload)}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await readSaveError(response);
  }
  return (await response.json()) as ProjectSettingsResponse;
}

/** `{detail: {error, field, message}}` из тела ответа — иначе `null`. */
export function parseFieldError(data: unknown): SettingFieldError | null {
  if (!data || typeof data !== 'object') {
    return null;
  }
  const detail = (data as { detail?: unknown }).detail;
  if (
    detail &&
    typeof detail === 'object' &&
    'field' in detail &&
    'message' in detail &&
    typeof (detail as { field: unknown }).field === 'string' &&
    typeof (detail as { message: unknown }).message === 'string'
  ) {
    const { field, message } = detail as { field: string; message: string };
    return new SettingFieldError(field, message);
  }
  return null;
}

async function readSaveError(response: Response): Promise<Error> {
  if (response.status === 422) {
    try {
      const fieldError = parseFieldError(await response.clone().json());
      if (fieldError) {
        return fieldError;
      }
    } catch {
      // тело не JSON — уходим в общий разбор
    }
  }
  return readError(response);
}

export { ApiError };
