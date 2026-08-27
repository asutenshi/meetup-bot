import { useEffect, useState } from 'react';

import { AppRoot } from '@telegram-apps/telegram-ui';

import type { ApiPaths } from './api/client';
import './App.css';

type HealthState = 'checking' | 'ok' | 'error';

/** Тип ответа /health — из сгенерированной OpenAPI-схемы (make openapi). */
type HealthResponse =
  ApiPaths['/health']['get']['responses'][200]['content']['application/json'];

/**
 * Экран-заглушка каркаса (TASKS.md 2.1). Показывает, что собрано и связано:
 * Telegram SDK инициализирован, токены оформления берутся из themeParams,
 * фирменный акцент — сменяемый токен --accent, запрос к бэкенду проходит.
 * Реальные экраны (форма мероприятия и т.д.) — задачи 2.5+.
 */
export function App() {
  const [health, setHealth] = useState<HealthState>('checking');

  useEffect(() => {
    let alive = true;
    fetch('/health')
      .then((r) => r.json() as Promise<HealthResponse>)
      .then((data) => {
        if (alive) setHealth(data.status === 'ok' ? 'ok' : 'error');
      })
      .catch(() => {
        if (alive) setHealth('error');
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <AppRoot>
      <main className="screen">
        <section className="card">
          <h1 className="card__title">meetup-bot · Web App</h1>
          <p className="card__hint">
            Каркас Telegram Mini App. Поверхности и текст — из Telegram{' '}
            <code>themeParams</code>, фирменный акцент — сменяемый токен{' '}
            <code>--accent</code> (WEBAPP_DESIGN.md).
          </p>
          <div className="swatch">--accent</div>
        </section>

        <section className="card">
          <p className="card__hint">
            Бэкенд <code>/health</code>:{' '}
            <span className="status" data-state={health}>
              {health}
            </span>
          </p>
        </section>
      </main>
    </AppRoot>
  );
}
