import { useEffect, useMemo, useState } from 'react';

import {
  ApiError,
  createEvent,
  fetchEditEventContext,
  fetchEventFormContext,
  updateEvent,
  type CreateEventRequest,
  type EventFormMember,
} from '../api/events';
import { closeMiniApp } from '../telegram/init';
import { Card, Field, PeopleList } from './components';
import './form.css';

type Loaded = {
  members: EventFormMember[];
  projectName: string;
};

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: Loaded }
  | { kind: 'not-registered' }
  | { kind: 'no-access' }
  | { kind: 'not-editable' }
  | { kind: 'load-error'; detail: string };

type Errors = Partial<
  Record<'starts_at' | 'ends_at' | 'location' | 'description' | 'budget' | 'seats', string>
>;

/** `datetime-local` → ISO-строка с зоной устройства организатора. */
function toIso(value: string): string {
  return new Date(value).toISOString();
}

/** ISO-строка → значение `datetime-local` в зоне устройства (для предзаполнения). */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** «1250,5» → «1250.5»: запятую как десятичный разделитель приводим к точке. */
function normalizeNumber(value: string): string {
  return value.trim().replace(',', '.');
}

export function EventForm({ eventId }: { eventId: number | null }) {
  const editing = eventId !== null;
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' });

  const [startsAt, setStartsAt] = useState('');
  const [endsAt, setEndsAt] = useState('');
  const [location, setLocation] = useState('');
  const [description, setDescription] = useState('');
  const [budget, setBudget] = useState('');
  const [seats, setSeats] = useState('');
  const [coOrganizers, setCoOrganizers] = useState<Set<number>>(new Set());

  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState<{ notified: number } | null>(null);

  useEffect(() => {
    let alive = true;

    function fail(error: unknown): void {
      if (!alive) return;
      if (error instanceof ApiError && error.status === 403) {
        setLoad(
          error.detail === 'not_registered'
            ? { kind: 'not-registered' }
            : { kind: 'no-access' },
        );
      } else if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        setLoad({ kind: 'not-editable' });
      } else {
        const detail = error instanceof ApiError ? error.detail : 'network';
        setLoad({ kind: 'load-error', detail });
      }
    }

    if (eventId !== null) {
      fetchEditEventContext(eventId)
        .then((context) => {
          if (!alive) return;
          setLoad({
            kind: 'ready',
            data: { members: context.members, projectName: context.project_name },
          });
          setStartsAt(toLocalInput(context.event.starts_at));
          setEndsAt(context.event.ends_at ? toLocalInput(context.event.ends_at) : '');
          setLocation(context.event.location);
          setDescription(context.event.description);
          setBudget(context.event.budget_per_person ?? '');
          setSeats(
            context.event.seats_limit !== null ? String(context.event.seats_limit) : '',
          );
          setCoOrganizers(new Set(context.event.co_organizer_user_ids));
        })
        .catch(fail);
    } else {
      fetchEventFormContext()
        .then((context) => {
          if (!alive) return;
          setLoad({
            kind: 'ready',
            data: { members: context.members, projectName: context.project_name },
          });
          setCoOrganizers(
            new Set(context.members.filter((m) => m.is_self).map((m) => m.user_id)),
          );
        })
        .catch(fail);
    }

    return () => {
      alive = false;
    };
  }, [eventId]);

  const members = useMemo(
    () => (load.kind === 'ready' ? load.data.members : []),
    [load],
  );

  if (load.kind === 'loading') {
    return <CenteredState title="Загрузка…" />;
  }
  if (load.kind === 'not-registered') {
    return (
      <CenteredState
        title="Вы не участник этого проекта"
        text="Зарегистрируйтесь по ссылке из поста регистрации в вашем групповом чате, потом откройте форму заново."
      />
    );
  }
  if (load.kind === 'no-access') {
    return (
      <CenteredState
        title="Нет доступа к редактированию"
        text="Форму открывают организаторы мероприятия, а если организатор не назначен — создатель и админы проекта."
      />
    );
  }
  if (load.kind === 'not-editable') {
    return (
      <CenteredState
        title="Мероприятие нельзя изменить"
        text="Оно отменено, уже прошло или удалено. Откройте список заново через /edit_event."
      />
    );
  }
  if (load.kind === 'load-error') {
    return (
      <CenteredState
        title="Не удалось открыть форму"
        text={`Попробуйте переоткрыть Mini App. Код: ${load.detail}`}
      />
    );
  }
  if (done) {
    return (
      <CenteredState
        badge="✅"
        title={editing ? 'Изменения сохранены' : 'Анонс опубликован'}
        text={
          editing
            ? done.notified > 0
              ? `Анонс в чате обновлён, уведомления об изменениях получили ${done.notified} чел.`
              : 'Анонс в чате обновлён.'
            : 'Мероприятие создано, анонс с кнопками «Участвую» / «Не участвую» отправлен в чат проекта.'
        }
        action={{ label: 'Закрыть', onClick: closeMiniApp }}
      />
    );
  }

  function validate(): Errors {
    const next: Errors = {};
    if (!startsAt) next.starts_at = 'Укажите дату и время начала';
    if (endsAt && startsAt && new Date(endsAt) <= new Date(startsAt)) {
      next.ends_at = 'Окончание должно быть позже начала';
    }
    if (!location.trim()) next.location = 'Укажите место';
    if (!description.trim()) next.description = 'Добавьте описание';
    const budgetValue = Number(normalizeNumber(budget));
    if (budget.trim() && !(Number.isFinite(budgetValue) && budgetValue >= 0)) {
      next.budget = 'Число ≥ 0';
    }
    const seatsValue = Number(seats.trim());
    if (seats.trim() && !(Number.isInteger(seatsValue) && seatsValue >= 1)) {
      next.seats = 'Целое число ≥ 1';
    }
    return next;
  }

  async function submit(): Promise<void> {
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    const body: CreateEventRequest = {
      starts_at: toIso(startsAt),
      ends_at: endsAt ? toIso(endsAt) : null,
      location: location.trim(),
      description: description.trim(),
      budget_per_person: budget.trim() ? normalizeNumber(budget) : null,
      seats_limit: seats.trim() ? Number(seats.trim()) : null,
      co_organizer_user_ids: [...coOrganizers],
    };

    setSubmitting(true);
    setSubmitError(null);
    try {
      if (eventId !== null) {
        const result = await updateEvent(eventId, body);
        setDone({ notified: result.notified_going });
      } else {
        await createEvent(body);
        setDone({ notified: 0 });
      }
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        setSubmitError('Сессия устарела — переоткройте Mini App.');
      } else if (error instanceof ApiError && error.status === 403) {
        setSubmitError('Нет прав на изменение этого мероприятия.');
      } else if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        setSubmitError('Мероприятие уже нельзя изменить — отменено или прошло.');
      } else {
        const detail = error instanceof ApiError ? error.detail : 'network';
        setSubmitError(`Не удалось сохранить. Код: ${detail}`);
      }
    } finally {
      setSubmitting(false);
    }
  }

  function toggleCoOrganizer(userId: number): void {
    setCoOrganizers((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  }

  return (
    <div className="ef-screen">
      <div className="ef-scroll">
        {editing && (
          <p className="ef-hint ef-hint--lead">
            Редактирование мероприятия проекта «{load.data.projectName}». После сохранения
            анонс в чате обновится, а подтвердившим участие уйдёт личное уведомление.
          </p>
        )}

        <Card icon="when" title="Когда">
          <Field label="Начало" htmlFor="ef-starts" error={errors.starts_at}>
            <input
              id="ef-starts"
              className={`ef-input${errors.starts_at ? ' ef-input--invalid' : ''}`}
              type="datetime-local"
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
            />
          </Field>
          <Field label="Окончание" htmlFor="ef-ends" optional error={errors.ends_at}>
            <input
              id="ef-ends"
              className={`ef-input${errors.ends_at ? ' ef-input--invalid' : ''}`}
              type="datetime-local"
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
            />
          </Field>
        </Card>

        <Card icon="where" title="Где">
          <Field label="Место" htmlFor="ef-location" error={errors.location}>
            <input
              id="ef-location"
              className={`ef-input${errors.location ? ' ef-input--invalid' : ''}`}
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Например: Парк Горького, у главного входа"
            />
          </Field>
        </Card>

        <Card icon="about" title="О чём">
          <Field label="Описание" htmlFor="ef-description" error={errors.description}>
            <textarea
              id="ef-description"
              className={`ef-input${errors.description ? ' ef-input--invalid' : ''}`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Что за встреча, что взять с собой, детали"
            />
          </Field>
        </Card>

        <Card icon="money" title="Деньги и места">
          <div className="ef-two">
            <Field label="Бюджет, ₽" htmlFor="ef-budget" optional error={errors.budget}>
              <input
                id="ef-budget"
                className={`ef-input${errors.budget ? ' ef-input--invalid' : ''}`}
                type="text"
                inputMode="decimal"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="—"
              />
            </Field>
            <Field label="Мест" htmlFor="ef-seats" optional error={errors.seats}>
              <input
                id="ef-seats"
                className={`ef-input${errors.seats ? ' ef-input--invalid' : ''}`}
                type="text"
                inputMode="numeric"
                value={seats}
                onChange={(e) => setSeats(e.target.value)}
                placeholder="—"
              />
            </Field>
          </div>
        </Card>

        <Card icon="people" title="Кто организует">
          <PeopleList
            members={members}
            selected={coOrganizers}
            onToggle={toggleCoOrganizer}
          />
          <p className="ef-hint">
            Можно снять галочку и с себя — тогда мероприятие опубликуется без
            организатора.
          </p>
        </Card>

        {submitError && <p className="ef-error">{submitError}</p>}
      </div>

      <div className="ef-footer">
        <button
          className="ef-submit"
          type="button"
          onClick={() => void submit()}
          disabled={submitting}
        >
          {submitting
            ? editing
              ? 'Сохраняем…'
              : 'Публикуем…'
            : editing
              ? 'Сохранить изменения'
              : 'Опубликовать анонс'}
        </button>
      </div>
    </div>
  );
}

function CenteredState({
  badge,
  title,
  text,
  action,
}: {
  badge?: string;
  title: string;
  text?: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="ef-state">
      {badge && <div className="ef-state__badge">{badge}</div>}
      <h1 className="ef-state__title">{title}</h1>
      {text && <p className="ef-state__text">{text}</p>}
      {action && (
        <button className="ef-submit" type="button" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
}
