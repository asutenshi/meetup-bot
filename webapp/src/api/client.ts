import { retrieveRawInitData } from '@telegram-apps/sdk';

import type { paths } from './schema';

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';

/**
 * Заголовок с подписанной строкой initData (TZ §3.2). Бэкенд валидирует её на
 * каждый запрос — это задача 2.2. Вне Telegram initData нет, заголовок не
 * добавляется (такие запросы бэкенд отклонит).
 */
function initDataHeader(): Record<string, string> {
  try {
    const raw = retrieveRawInitData();
    return raw ? { 'X-Telegram-Init-Data': raw } : {};
  } catch {
    return {};
  }
}

/** fetch к бэкенду с автоматическим X-Telegram-Init-Data. */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...initDataHeader(), ...init?.headers },
  });
}

/** Типы путей/схем API, сгенерированные из OpenAPI (make openapi). */
export type ApiPaths = paths;
