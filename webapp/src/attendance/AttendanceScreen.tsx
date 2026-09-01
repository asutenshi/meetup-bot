import { useEffect, useState } from 'react';

import { ApiError } from '../api/events';
import {
  fetchAttendanceContext,
  setAttendance,
  type AttendanceParticipant,
  type RsvpStatus,
} from '../api/attendance';
import { ParticipantRow } from './components';
import './attendance.css';

type Loaded = {
  projectName: string;
  eventLabel: string;
  finalized: boolean;
  countersLocked: boolean;
  participants: AttendanceParticipant[];
};

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: Loaded }
  | { kind: 'not-registered' }
  | { kind: 'no-access' }
  | { kind: 'not-found' }
  | { kind: 'load-error'; detail: string };

export function AttendanceScreen({ eventId }: { eventId: number }) {
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' });
  // user_id, по которым сейчас идёт запрос / последняя правка не удалась.
  const [pending, setPending] = useState<ReadonlySet<number>>(new Set());
  const [failed, setFailed] = useState<ReadonlySet<number>>(new Set());

  useEffect(() => {
    let alive = true;
    fetchAttendanceContext(eventId)
      .then((context) => {
        if (!alive) return;
        setLoad({
          kind: 'ready',
          data: {
            projectName: context.project_name,
            eventLabel: context.event_label,
            finalized: context.finalized,
            countersLocked: context.counters_locked,
            participants: context.participants,
          },
        });
      })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiError && error.status === 403) {
          setLoad(
            error.detail === 'not_registered'
              ? { kind: 'not-registered' }
              : { kind: 'no-access' },
          );
        } else if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
          setLoad({ kind: 'not-found' });
        } else {
          const detail = error instanceof ApiError ? error.detail : 'network';
          setLoad({ kind: 'load-error', detail });
        }
      });
    return () => {
      alive = false;
    };
  }, [eventId]);

  function patch(userId: number, status: RsvpStatus): void {
    setLoad((prev) =>
      prev.kind === 'ready'
        ? {
            kind: 'ready',
            data: {
              ...prev.data,
              participants: prev.data.participants.map((p) =>
                p.user_id === userId ? { ...p, status } : p,
              ),
            },
          }
        : prev,
    );
  }

  function withUser(
    set: ReadonlySet<number>,
    userId: number,
    present: boolean,
  ): ReadonlySet<number> {
    const next = new Set(set);
    if (present) next.add(userId);
    else next.delete(userId);
    return next;
  }

  async function pick(
    userId: number,
    previous: RsvpStatus,
    next: RsvpStatus,
  ): Promise<void> {
    patch(userId, next);
    setPending((s) => withUser(s, userId, true));
    setFailed((s) => withUser(s, userId, false));
    try {
      await setAttendance(eventId, { user_id: userId, status: next });
    } catch {
      patch(userId, previous);
      setFailed((s) => withUser(s, userId, true));
    } finally {
      setPending((s) => withUser(s, userId, false));
    }
  }

  if (load.kind === 'loading') {
    return <Centered title="Загрузка…" />;
  }
  if (load.kind === 'not-registered') {
    return (
      <Centered
        title="Вы не участник этого проекта"
        text="Зарегистрируйтесь по ссылке из поста регистрации в вашем групповом чате, потом откройте экран заново."
      />
    );
  }
  if (load.kind === 'no-access') {
    return (
      <Centered
        title="Нет доступа к корректировке"
        text="Экран открывают организаторы мероприятия, а если организатор не назначен — создатель и админы проекта."
      />
    );
  }
  if (load.kind === 'not-found') {
    return (
      <Centered
        title="Мероприятие недоступно"
        text="Оно отменено или удалено. Откройте список заново через /attendance."
      />
    );
  }
  if (load.kind === 'load-error') {
    return (
      <Centered
        title="Не удалось открыть экран"
        text={`Попробуйте переоткрыть Mini App. Код: ${load.detail}`}
      />
    );
  }

  const { data } = load;
  return (
    <div className="at-screen">
      <div className="at-scroll">
        <header className="at-head">
          <h1 className="at-head__title">Явка на мероприятие</h1>
          <p className="at-head__sub">
            {data.projectName} · {data.eventLabel}
          </p>
        </header>

        <p className="at-note">
          {data.finalized
            ? data.countersLocked
              ? 'Явка уже зафиксирована. Правки изменят состав в анонсе, но счётчики пропусков участников не пересчитываются — это не последнее финализированное мероприятие проекта.'
              : 'Явка уже зафиксирована. Каждая правка сразу пересчитывает счётчики пропусков этого участника.'
            : 'Мероприятие ещё не финализировано — правки просто меняют RSVP и обновляют анонс в чате.'}
        </p>

        <div className="at-list">
          {data.participants.map((p) => (
            <ParticipantRow
              key={p.user_id}
              name={p.name}
              value={p.status}
              pending={pending.has(p.user_id)}
              error={failed.has(p.user_id)}
              onPick={(next) => void pick(p.user_id, p.status, next)}
            />
          ))}
        </div>

        {failed.size > 0 && (
          <p className="at-error">
            Часть правок не сохранилась — статус вернули к прежнему. Проверьте связь
            и попробуйте снова.
          </p>
        )}
      </div>
    </div>
  );
}

function Centered({ title, text }: { title: string; text?: string }) {
  return (
    <div className="at-state">
      <h1 className="at-state__title">{title}</h1>
      {text && <p className="at-state__text">{text}</p>}
    </div>
  );
}
