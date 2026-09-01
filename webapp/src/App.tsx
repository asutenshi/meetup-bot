import { AppRoot } from '@telegram-apps/telegram-ui';

import { hasInitData } from './api/client';
import { EventForm } from './event-form/EventForm';
import { HubScreen } from './hub/HubScreen';
import { useNavigation } from './nav/useNavigation';
import './App.css';

/**
 * Точка входа Web App. Экран выбирается навигацией (`useNavigation`): кнопка-меню
 * бота открывает домашний экран-хаб (без контекста в URL), ответ на `/new_event`
 * / `/edit_event` — сразу форму мероприятия. С хаба можно перейти к созданию
 * мероприятия и вернуться кнопкой «назад» (задача 2.9.1).
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
  const { view, navigate } = useNavigation();

  if (view.name === 'form') {
    return <EventForm eventId={view.eventId} />;
  }
  return <HubScreen navigate={navigate} />;
}
