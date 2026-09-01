import { apiFetch } from './client';
import type { components } from './schema';

export type EventFormContext = components['schemas']['EventFormContext'];
export type EventFormMember = components['schemas']['EventFormMember'];
export type CreateEventRequest = components['schemas']['CreateEventRequest'];
export type CreateEventResponse = components['schemas']['CreateEventResponse'];
export type EditEventContext = components['schemas']['EditEventContext'];
export type EventFormData = components['schemas']['EventFormData'];
export type UpdateEventRequest = components['schemas']['UpdateEventRequest'];
export type UpdateEventResponse = components['schemas']['UpdateEventResponse'];
export type EventView = components['schemas']['EventView'];
export type EventRsvpSummary = components['schemas']['EventRsvpSummary'];
export type RsvpStatus = components['schemas']['RsvpRequest']['status'];

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

export async function readError(response: Response): Promise<ApiError> {
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

/** Поля мероприятия для предзаполнения формы редактирования (GET /api/events/{id}). */
export async function fetchEditEventContext(
  eventId: number,
): Promise<EditEventContext> {
  const response = await apiFetch(`/events/${eventId}`);
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as EditEventContext;
}

/** Сохранение изменений, обновление анонса и уведомление подтвердивших (PUT /api/events/{id}). */
export async function updateEvent(
  eventId: number,
  body: UpdateEventRequest,
): Promise<UpdateEventResponse> {
  const response = await apiFetch(`/events/${eventId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as UpdateEventResponse;
}

/** Мероприятие для экрана Web App: поля + RSVP-сводка + права (GET /api/events/{id}/view). */
export async function fetchEventView(eventId: number): Promise<EventView> {
  const response = await apiFetch(`/events/${eventId}/view`);
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as EventView;
}

/** Самоотметка «Участвую» / «Не участвую» с экрана мероприятия (POST /api/events/{id}/rsvp). */
export async function submitRsvp(
  eventId: number,
  status: RsvpStatus,
): Promise<EventRsvpSummary> {
  const response = await apiFetch(`/events/${eventId}/rsvp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as EventRsvpSummary;
}
