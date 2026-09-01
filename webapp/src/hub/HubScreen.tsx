import { useEffect, useState } from 'react';

import { ApiError } from '../api/events';
import { fetchHome, fetchProjectEvents, type EventCard, type HomeProject } from '../api/home';
import type { View } from '../nav/navigation';
import { Card } from '../ui/Card';
import { formatWhen } from './format';
import './hub.css';

type HomeState =
  | { kind: 'loading' }
  | { kind: 'ready'; userName: string; projects: HomeProject[] }
  | { kind: 'not-registered'; userName: string }
  | { kind: 'error'; detail: string };

const ROLE_LABEL: Record<string, string> = {
  owner: 'главный администратор',
  admin: 'администратор',
  member: 'участник',
};

const PLUS_ICON = <path d="M12 5v14M5 12h14" />;

export function HubScreen({ navigate }: { navigate: (view: View) => void }) {
  const [state, setState] = useState<HomeState>({ kind: 'loading' });

  useEffect(() => {
    let alive = true;
    fetchHome()
      .then((home) => {
        if (!alive) return;
        setState(
          home.projects.length === 0
            ? { kind: 'not-registered', userName: home.user_name }
            : { kind: 'ready', userName: home.user_name, projects: home.projects },
        );
      })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiError && error.status === 401) {
          setState({ kind: 'error', detail: 'session' });
        } else {
          const detail = error instanceof ApiError ? error.detail : 'network';
          setState({ kind: 'error', detail });
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  if (state.kind === 'loading') {
    return <div className="hub-state">Загрузка…</div>;
  }

  if (state.kind === 'error') {
    return (
      <div className="hub-state">
        <p className="hub-state__title">Не удалось загрузить</p>
        <p className="hub-state__text">
          {state.detail === 'session'
            ? 'Сессия устарела — закройте и откройте Mini App заново.'
            : `Попробуйте переоткрыть Mini App. Код: ${state.detail}`}
        </p>
      </div>
    );
  }

  return (
    <div className="hub-screen">
      <header className="hub-head">
        <p className="hub-head__hi">Привет, {state.userName}</p>
      </header>

      {state.kind === 'not-registered' ? (
        <Card title="Вы ещё не зарегистрированы">
          <p className="hub-note">
            Откройте пост регистрации в вашем групповом чате и перейдите по ссылке-приглашению.
            После этого вернитесь сюда — появятся ваши проекты и мероприятия.
          </p>
        </Card>
      ) : (
        state.projects.map((project) => (
          <ProjectSection key={project.payload} project={project} navigate={navigate} />
        ))
      )}
    </div>
  );
}

type EventsState =
  | { kind: 'loading' }
  | { kind: 'ready'; events: EventCard[] }
  | { kind: 'error' };

function ProjectSection({
  project,
  navigate,
}: {
  project: HomeProject;
  navigate: (view: View) => void;
}) {
  const [events, setEvents] = useState<EventsState>({ kind: 'loading' });

  useEffect(() => {
    let alive = true;
    fetchProjectEvents(project.payload)
      .then((list) => alive && setEvents({ kind: 'ready', events: list }))
      .catch(() => alive && setEvents({ kind: 'error' }));
    return () => {
      alive = false;
    };
  }, [project.payload]);

  return (
    <Card
      title={project.name}
      action={<span className="hub-role">{ROLE_LABEL[project.role] ?? project.role}</span>}
    >
      {events.kind === 'loading' && <p className="hub-note">Загружаем мероприятия…</p>}
      {events.kind === 'error' && (
        <p className="hub-note">Не удалось загрузить мероприятия этого проекта.</p>
      )}
      {events.kind === 'ready' &&
        (events.events.length === 0 ? (
          <p className="hub-note">Пока нет мероприятий.</p>
        ) : (
          <ul className="hub-events">
            {events.events.map((event) => (
              <EventRow
                key={event.id}
                event={event}
                onOpen={() =>
                  navigate({ name: 'event', project: project.payload, eventId: event.id })
                }
              />
            ))}
          </ul>
        ))}

      <button
        type="button"
        className="hub-create"
        onClick={() => navigate({ name: 'form', project: project.payload, eventId: null })}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          {PLUS_ICON}
        </svg>
        Создать мероприятие
      </button>
    </Card>
  );
}

function EventRow({ event, onOpen }: { event: EventCard; onOpen: () => void }) {
  const seats = event.seats_limit;
  const goalReached = seats !== null && event.going_count >= seats;
  return (
    <li>
      <button type="button" className="hub-event" onClick={onOpen}>
        <span className="hub-event__main">
          <span className="hub-event__when">{formatWhen(event.starts_at)}</span>
          <span className="hub-event__title">{event.title?.trim() || event.location}</span>
        </span>
        <span className="hub-event__meta">
          {event.is_finalized && <span className="hub-tag">прошло</span>}
          <span className="hub-event__going">
            идёт {event.going_count}
            {seats !== null ? `/${seats}` : ''}
            {goalReached ? ' 🎯' : ''}
          </span>
        </span>
        <svg className="hub-event__chev" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M9 6l6 6-6 6" />
        </svg>
      </button>
    </li>
  );
}
