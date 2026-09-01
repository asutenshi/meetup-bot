import { AppRoot } from '@telegram-apps/telegram-ui';

import { hasInitData } from './api/client';
import { AttendanceScreen } from './attendance/AttendanceScreen';
import { EventForm } from './event-form/EventForm';
import { EventScreen } from './event/EventScreen';
import { HubScreen } from './hub/HubScreen';
import { SettingsScreen } from './settings/SettingsScreen';
import { useNavigation } from './nav/useNavigation';
import './App.css';

/**
 * Точка входа Web App. Экран выбирается навигацией (`useNavigation`): кнопка-меню
 * бота открывает домашний экран-хаб (без контекста в URL), ответ на `/new_event`
 * / `/edit_event` — сразу форму мероприятия, ответ на `/attendance` — экран
 * постфактум-корректировки RSVP (`?project=&attendance=<id>`, задача 3.1). С хаба
 * можно перейти к созданию мероприятия и вернуться кнопкой «назад» (задача 2.9.1),
 * а owner/admin — к экрану настроек проекта (задача 4.5).
 */
export function App() {
  if (!hasInitData()) {
    return (
      <AppRoot>
        <main className="screen">
          <section className="card">
            <h1 className="card__title">meetup-bot · Web App</h1>
            <p className="card__hint">
              Приложение открыто вне Telegram. Откройте его кнопкой-меню или командой{' '}
              <code>/new_event</code> в личном чате с ботом — иначе бэкенд отклонит
              запросы (нет подписи <code>initData</code>).
            </p>
          </section>
        </main>
      </AppRoot>
    );
  }

  return (
    <AppRoot>
      <Screens />
    </AppRoot>
  );
}

function Screens() {
  const { view, canGoBack, navigate, back } = useNavigation();

  if (view.name === 'form') {
    return <EventForm eventId={view.eventId} onBack={canGoBack ? back : undefined} />;
  }
  if (view.name === 'event') {
    return (
      <EventScreen
        eventId={view.eventId}
        project={view.project}
        onBack={back}
        navigate={navigate}
      />
    );
  }
  if (view.name === 'attendance') {
    return <AttendanceScreen eventId={view.eventId} />;
  }
  if (view.name === 'settings') {
    return <SettingsScreen project={view.project} onBack={back} />;
  }
  return <HubScreen navigate={navigate} />;
}
