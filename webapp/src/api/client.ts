import { retrieveRawInitData } from '@tma.js/sdk';

import type { paths } from './schema';

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';

function rawInitData(): string | undefined {
  try {
    return retrieveRawInitData();
  } catch {
    return undefined;
  }
}

/**
 * Открыто ли приложение внутри Telegram — есть ли подписанная initData. Вне
 * Telegram (открыли ссылку в браузере напрямую) её нет, и любой запрос к API
 * бэкенд отклонит: экраны показывают об этом понятное предупреждение.
 */
export function hasInitData(): boolean {
  return rawInitData() !== undefined;
}

/**
 * Значение query-параметра `project` из URL Mini App. В личке бот подставляет
 * туда `invite_payload` проекта (TZ §3.8): формы Web App всегда открываются в
 * контексте конкретного проекта. Открыли приложение вне этого контекста — `null`.
 */
export function getProjectContext(): string | null {
  const value = new URLSearchParams(window.location.search).get('project');
  return value && value.trim() ? value : null;
}

function initDataHeader(): Record<string, string> {
  const raw = rawInitData();
  return raw ? { 'X-Telegram-Init-Data': raw } : {};
}

/**
 * fetch к бэкенду с автоматическим `X-Telegram-Init-Data` и параметром
 * `project` (бэкенд валидирует подпись и сверяет проект с `ProjectMembership`
 * пользователя — TZ §3.2). Вне Telegram заголовок не добавляется, вне
 * project-контекста параметр не добавляется — такие запросы бэкенд отклонит.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const project = getProjectContext();
  let url = `${API_BASE}${path}`;
  if (project && !/[?&]project=/.test(url)) {
    url += `${url.includes('?') ? '&' : '?'}project=${encodeURIComponent(project)}`;
  }
  return fetch(url, {
    ...init,
    headers: { ...initDataHeader(), ...init?.headers },
  });
}

/** Типы путей/схем API, сгенерированные из OpenAPI (make openapi). */
export type ApiPaths = paths;
