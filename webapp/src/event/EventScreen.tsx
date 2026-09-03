import { useEffect, useState } from 'react';

import {
  ApiError,
  cancelEvent,
  fetchEventView,
  submitRsvp,
  type CancelEventResponse,
  type EventRsvpSummary,
  type EventView,
  type RsvpStatus,
} from '../api/events';
import { formatWhen } from '../hub/format';
import type { View } from '../nav/navigation';
import { closeMiniApp, openTelegramLinkSafe } from '../telegram/init';
import { Card } from '../ui/Card';
import { ScreenBar, type ScreenBarAction } from '../ui/ScreenBar';
import { ICONS } from '../event-form/components';
import './event.css';

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; event: EventView }
  | { kind: 'not-registered' }
  | { kind: 'not-found' }
  | { kind: 'error'; detail: string };

/** «14 сентября 2026, сб · 18:00», с окончанием — через « — ». */
function whenText(event: EventView): string {
  const start = formatWhen(event.starts_at);
  if (!event.ends_at) return start;
  return `${start} — ${formatWhen(event.ends_at)}`;
}

export function EventScreen({
  eventId,
  project,
  onBack,
  navigate,
}: {
  eventId: number;
  project: string;
  onBack: () => void;
  navigate: (view: View) => void;
}) {
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' });
  const [rsvp, setRsvp] = useState<EventRsvpSummary | null>(null);
  const [rsvpBusy, setRsvpBusy] = useState(false);
  const [rsvpError, setRsvpError] = useState<string | null>(null);
  // Отмена мероприятия из меню шапки (для can_manage): 'view' → 'confirm' →
  // экран результата (cancelDone).
  const [phase, setPhase] = useState<'view' | 'confirm'>('view');
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelDone, setCancelDone] = useState<CancelEventResponse | null>(null);

  useEffect(() => {
    let alive = true;
    fetchEventView(eventId)
      .then((event) => {
        if (!alive) return;
        setLoad({ kind: 'ready', event });
        setRsvp(event.rsvp);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiError && error.status === 403) {
          setLoad({ kind: 'not-registered' });
        } else if (error instanceof ApiError && error.status === 404) {
          setLoad({ kind: 'not-found' });
        } else {
          const detail = error instanceof ApiError ? error.detail : 'network';
          setLoad({ kind: 'error', detail });
        }
      });
    return () => {
      alive = false;
    };
  }, [eventId]);

  async function pick(status: RsvpStatus): Promise<void> {
    setRsvpBusy(true);
    setRsvpError(null);
    try {
      setRsvp(await submitRsvp(eventId, status));
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        setRsvpError('Сессия устарела — переоткройте Mini App.');
      } else if (error instanceof ApiError && error.status === 409) {
        setRsvpError('Отметиться уже нельзя — мероприятие отменено или прошло.');
      } else {
        const detail = error instanceof ApiError ? error.detail : 'network';
        setRsvpError(`Не удалось отметиться. Код: ${detail}`);
      }
    } finally {
      setRsvpBusy(false);
    }
  }

  async function runCancel(): Promise<void> {
    setCancelBusy(true);
    setCancelError(null);
    try {
      setCancelDone(await cancelEvent(eventId));
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        setCancelError('Сессия устарела — переоткройте Mini App.');
      } else if (error instanceof ApiError && error.status === 403) {
        setCancelError('Нет прав на отмену этого мероприятия.');
      } else if (
        error instanceof ApiError &&
        (error.status === 404 || error.status === 409)
      ) {
        setCancelError('Мероприятие уже нельзя отменить — отменено, прошло или удалено.');
      } else {
        const detail = error instanceof ApiError ? error.detail : 'network';
        setCancelError(`Не удалось отменить. Код: ${detail}`);
      }
    } finally {
      setCancelBusy(false);
    }
  }

  const actions: ScreenBarAction[] =
    load.kind === 'ready' && load.event.can_manage
      ? [
          {
            label: 'Редактировать',
            onClick: () => navigate({ name: 'form', project, eventId }),
          },
          {
            label: 'Отменить мероприятие',
            danger: true,
            onClick: () => {
              setCancelError(null);
              setPhase('confirm');
            },
          },
        ]
      : [];

  if (load.kind !== 'ready') {
    return (
      <div className="es-root">
        <ScreenBar onBack={onBack} />
        <div className="es-state">
          {load.kind === 'loading' && <p className="es-state__title">Загрузка…</p>}
          {load.kind === 'not-registered' && (
            <>
              <p className="es-state__title">Вы не участник этого проекта</p>
              <p className="es-state__text">
                Зарегистрируйтесь по ссылке из поста регистрации в вашем групповом чате.
              </p>
            </>
          )}
          {load.kind === 'not-found' && (
            <>
              <p className="es-state__title">Мероприятие не найдено</p>
              <p className="es-state__text">
                Возможно, его удалили. Вернитесь на хаб и обновите список.
              </p>
            </>
          )}
          {load.kind === 'error' && (
            <>
              <p className="es-state__title">Не удалось загрузить</p>
              <p className="es-state__text">
                Попробуйте переоткрыть Mini App. Код: {load.detail}
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  if (cancelDone) {
    return (
      <div className="es-root">
        <ScreenBar onBack={onBack} />
        <div className="es-state">
          <div className="es-state__badge">🚫</div>
          <p className="es-state__title">Мероприятие отменено</p>
          <p className="es-state__text">
            {cancelDone.notified > 0
              ? `Уведомление об отмене получили ${cancelDone.notified} чел. `
              : ''}
            {cancelDone.announcement_ok
              ? 'Анонс в чате помечен «отменено», RSVP-кнопки убраны.'
              : '⚠️ Анонс в чате обновить не удалось — пометьте отмену и уберите кнопки вручную.'}
          </p>
          <div className="es-cancel__actions">
            <button
              type="button"
              className="es-cancel__btn es-cancel__btn--primary"
              onClick={closeMiniApp}
            >
              Закрыть
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (phase === 'confirm') {
    return (
      <div className="es-root">
        <ScreenBar onBack={() => setPhase('view')} />
        <div className="es-state">
          <div className="es-state__badge">🚫</div>
          <p className="es-state__title">Отменить мероприятие?</p>
          <p className="es-state__text">
            Анонс в чате пометится «отменено», RSVP-кнопки уберутся, а подтвердившим
            участие уйдёт личное уведомление. Действие необратимо.
          </p>
          {cancelError && <p className="ui-error">{cancelError}</p>}
          <div className="es-cancel__actions">
            <button
              type="button"
              className="es-cancel__btn es-cancel__btn--danger"
              disabled={cancelBusy}
              onClick={() => void runCancel()}
            >
              {cancelBusy ? 'Отменяем…' : 'Да, отменить'}
            </button>
            <button
              type="button"
              className="es-cancel__btn"
              disabled={cancelBusy}
              onClick={() => setPhase('view')}
            >
              Назад
            </button>
          </div>
        </div>
      </div>
    );
  }

  const event = load.event;
  const summary = rsvp ?? event.rsvp;
  const cancelled = event.status === 'cancelled';
  const locked = cancelled || event.is_finalized;
  const seats = event.seats_limit;

  return (
    <div className="es-root">
      <ScreenBar onBack={onBack} actions={actions} />
      <div className="es-scroll">
        {event.title && <h1 className="es-title">{event.title}</h1>}

        {cancelled && (
          <p className="es-banner es-banner--danger">🚫 Мероприятие отменено</p>
        )}
        {!cancelled && event.is_finalized && (
          <p className="es-banner">Явка зафиксирована — отметиться уже нельзя.</p>
        )}

        <Card icon={ICONS.when} title="Когда">
          <p className="es-line">{whenText(event)}</p>
        </Card>

        <Card icon={ICONS.where} title="Где">
          <p className="es-line">{event.location}</p>
        </Card>

        <Card icon={ICONS.about} title="О чём">
          <p className="es-line es-line--pre">{event.description}</p>
        </Card>

        {event.details && (
          <Card icon={ICONS.about} title="Подробности">
            <p className="es-line es-line--pre">{event.details}</p>
          </Card>
        )}

        {(event.budget_per_person !== null || seats !== null) && (
          <Card icon={ICONS.money} title="Деньги и места">
            {event.budget_per_person !== null && (
              <p className="es-line">Бюджет с человека: {event.budget_per_person} ₽</p>
            )}
            {seats !== null && <p className="es-line">Мест: {seats}</p>}
          </Card>
        )}

        <Card icon={ICONS.people} title="Кто организует">
          {event.co_organizers.length > 0 ? (
            <ul className="es-people">
              {event.co_organizers.map((co) => (
                <li key={co.user_id}>{co.name}</li>
              ))}
            </ul>
          ) : (
            <p className="es-muted">Организатор не назначен.</p>
          )}
        </Card>

        <Card title="Кто идёт">
          <p className="es-counts">
            <span className="es-counts__going">✅ идут: {summary.going_count}</span>
            <span className="es-counts__no">❌ не идут: {summary.not_going_count}</span>
          </p>

          {locked ? (
            <p className="es-muted">
              {cancelled
                ? 'Мероприятие отменено — отметки больше не принимаются.'
                : 'Явка уже зафиксирована.'}
            </p>
          ) : (
            <div
              className="es-toggle"
              role="group"
              aria-label="Ваш ответ на мероприятие"
            >
              <button
                type="button"
                className={`es-toggle__btn${
                  summary.my_rsvp === 'going' ? ' es-toggle__btn--active' : ''
                }`}
                disabled={rsvpBusy}
                onClick={() => void pick('going')}
              >
                ✅ Участвую
              </button>
              <button
                type="button"
                className={`es-toggle__btn${
                  summary.my_rsvp === 'not_going' ? ' es-toggle__btn--active' : ''
                }`}
                disabled={rsvpBusy}
                onClick={() => void pick('not_going')}
              >
                ❌ Не участвую
              </button>
            </div>
          )}

          {rsvpError && <p className="ui-error">{rsvpError}</p>}
        </Card>

        {event.announcement_url && (
          <button
            type="button"
            className="es-link"
            onClick={() => openTelegramLinkSafe(event.announcement_url as string)}
          >
            🔗 Перейти к анонсу
          </button>
        )}
      </div>
    </div>
  );
}
