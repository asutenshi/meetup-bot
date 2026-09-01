import { AppRoot } from '@telegram-apps/telegram-ui';

import {
  getAttendanceContext,
  getEventContext,
  getProjectContext,
  hasInitData,
} from './api/client';
import { AttendanceScreen } from './attendance/AttendanceScreen';
import { EventForm } from './event-form/EventForm';
import './App.css';

/**
 * Точка входа Web App. Экраны различаются по query-параметрам URL кнопки бота:
 * `&attendance=<id>` — экран постфактум-корректировки RSVP (`/attendance`,
 * TASKS.md 3.1); `&event=<id>` — форма редактирования мероприятия
 * (`/edit_event`, 2.7); иначе — форма создания (`/new_event`). Параметры
 * взаимоисключающие; домашний экран-хаб и роутинг между экранами — задача 2.9.
 */
export function App() {
  const insideTelegram = hasInitData();
  const project = getProjectContext();
  const eventId = getEventContext();
  const attendanceEventId = getAttendanceContext();

  if (insideTelegram && project) {
    return (
      <AppRoot>
        {attendanceEventId !== null ? (
          <AttendanceScreen eventId={attendanceEventId} />
        ) : (
          <EventForm eventId={eventId} />
        )}
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
