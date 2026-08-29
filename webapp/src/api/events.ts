import { apiFetch } from './client';
import type { components } from './schema';

export type EventFormContext = components['schemas']['EventFormContext'];
export type EventFormMember = components['schemas']['EventFormMember'];
export type CreateEventRequest = components['schemas']['CreateEventRequest'];
export type CreateEventResponse = components['schemas']['CreateEventResponse'];

/** Ошибка ответа бэкенда: `status` + машиночитаемый `detail` (TZ §3.2). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function readError(response: Response): Promise<ApiError> {
  let detail = `http_${response.status}`;
  try {
    const data: unknown = await response.json();
    if (
      data &&
      typeof data === 'object' &&
      'detail' in data &&
      typeof (data as { detail: unknown }).detail === 'string'
    ) {
      detail = (data as { detail: string }).detail;
    }
  } catch {
    // тело не JSON — оставляем http_<code>
  }
  return new ApiError(response.status, detail);
}

/** Название проекта + участники для выбора со-организаторов (GET /api/events/context). */
export async function fetchEventFormContext(): Promise<EventFormContext> {
  const response = await apiFetch('/events/context');
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as EventFormContext;
}

/** Создание мероприятия и публикация анонса (POST /api/events). */
export async function createEvent(
  body: CreateEventRequest,
): Promise<CreateEventResponse> {
  const response = await apiFetch('/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as CreateEventResponse;
}
