import { apiFetch } from './client';
import { readError } from './events';
import type { components } from './schema';

export type HomeResponse = components['schemas']['HomeResponse'];
export type HomeProject = components['schemas']['HomeProject'];
export type ProjectEventsResponse = components['schemas']['ProjectEventsResponse'];
export type EventCard = components['schemas']['EventCard'];

/** Кто пользователь и в каких он проектах (GET /api/home, без project-контекста). */
export async function fetchHome(): Promise<HomeResponse> {
  const response = await apiFetch('/home');
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as HomeResponse;
}

/** Мероприятия проекта для списка на хабе (GET /api/projects/{payload}/events). */
export async function fetchProjectEvents(payload: string): Promise<EventCard[]> {
  const response = await apiFetch(`/projects/${encodeURIComponent(payload)}/events`);
  if (!response.ok) {
    throw await readError(response);
  }
  return ((await response.json()) as ProjectEventsResponse).events;
}
