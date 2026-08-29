import { AppRoot } from '@telegram-apps/telegram-ui';

import { getProjectContext, hasInitData } from './api/client';
import { EventForm } from './event-form/EventForm';
import './App.css';

/**
 * Точка входа Web App. Пока единственный экран — форма создания мероприятия
 * (TASKS.md 2.5), открывается кнопкой из ответа бота на `/new_event` с
 * `?project=<invite_payload>` в URL. Домашний экран-хаб и роутинг между
 * экранами — задача 2.9.
 */
export function App() {
  const insideTelegram = hasInitData();
  const project = getProjectContext();

  if (insideTelegram && project) {
    return (
      <AppRoot>
        <EventForm />
      </AppRoot>
    );
  }

  return (
    <AppRoot>
      <main className="screen">
        <section className="card">
          <h1 className="card__title">meetup-bot · Web App</h1>
          {!insideTelegram ? (
            <p className="card__hint">
              Приложение открыто вне Telegram. Откройте форму через команду{' '}
              <code>/new_event</code> в личном чате с ботом — иначе бэкенд отклонит
              запросы (нет подписи <code>initData</code>).
            </p>
          ) : (
            <p className="card__hint">
              Не передан контекст проекта (<code>?project=…</code> в URL). Откройте
              приложение кнопкой из ответа бота на <code>/new_event</code>.
            </p>
          )}
        </section>
      </main>
    </AppRoot>
  );
}
