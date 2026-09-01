import { apiFetch } from './client';
import { ApiError } from './events';
import type { components } from './schema';

export type AttendanceContext = components['schemas']['AttendanceContext'];
export type AttendanceParticipant = components['schemas']['AttendanceParticipant'];
export type SetAttendanceRequest = components['schemas']['SetAttendanceRequest'];
export type SetAttendanceResponse = components['schemas']['SetAttendanceResponse'];

/** `null` — участник не ответил на RSVP. */
export type RsvpStatus = AttendanceParticipant['status'];

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

/** Подпись мероприятия + участники с текущим RSVP (GET /api/events/{id}/attendance). */
export async function fetchAttendanceContext(
  eventId: number,
): Promise<AttendanceContext> {
  const response = await apiFetch(`/events/${eventId}/attendance`);
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as AttendanceContext;
}

/** Правка чужого RSVP по мероприятию (POST /api/events/{id}/attendance). */
export async function setAttendance(
  eventId: number,
  body: SetAttendanceRequest,
): Promise<SetAttendanceResponse> {
  const response = await apiFetch(`/events/${eventId}/attendance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as SetAttendanceResponse;
}
