import { useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  ApiError,
  SettingFieldError,
  fetchProjectSettings,
  saveProjectSettings,
  type ProjectSettingsResponse,
  type ProjectSettingsUpdate,
  type SettingField,
} from '../api/settings';
import { Card, Field } from '../ui/Card';
import { ScreenBar } from '../ui/ScreenBar';
import './settings.css';

/** Человекочитаемые подписи полей; описание из ответа идёт отдельной строкой. */
const LABELS: Record<string, string> = {
  reminder_days_threshold: 'Порог «давно не виделись», дней',
  missed_events_escalation_count: 'Пропусков подряд до эскалации',
  reminder_send_hour: 'Час рассылки напоминаний (0–23)',
  all_command_throttle_seconds: 'Троттлинг /all, секунд',
  timezone: 'Таймзона проекта (IANA)',
};

const ORDER: Array<keyof ProjectSettingsUpdate> = [
  'reminder_days_threshold',
  'missed_events_escalation_count',
  'reminder_send_hour',
  'all_command_throttle_seconds',
  'timezone',
];

type Loaded = {
  projectName: string;
  fields: SettingField[];
  values: Record<string, string>;
};

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: Loaded }
  | { kind: 'not-registered' }
  | { kind: 'not-admin' }
  | { kind: 'load-error'; detail: string };

function toValues(settings: ProjectSettingsResponse): Record<string, string> {
  return {
    reminder_days_threshold: String(settings.reminder_days_threshold),
    missed_events_escalation_count: String(settings.missed_events_escalation_count),
    reminder_send_hour: String(settings.reminder_send_hour),
    all_command_throttle_seconds: String(settings.all_command_throttle_seconds),
    timezone: settings.timezone,
  };
}

export function SettingsScreen({
  project,
  onBack,
}: {
  project: string;
  onBack: () => void;
}) {
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [fieldError, setFieldError] = useState<{ field: string; message: string } | null>(
    null,
  );
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchProjectSettings(project)
      .then((settings) => {
        if (!alive) return;
        setLoad({
          kind: 'ready',
          data: {
            projectName: settings.project_name,
            fields: settings.fields,
            values: toValues(settings),
          },
        });
      })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiError && error.status === 403) {
          setLoad(
            error.detail === 'not_registered'
              ? { kind: 'not-registered' }
              : { kind: 'not-admin' },
          );
        } else {
          const detail = error instanceof ApiError ? error.detail : 'network';
          setLoad({ kind: 'load-error', detail });
        }
      });
    return () => {
      alive = false;
    };
  }, [project]);

  const fieldByAttr = useMemo(() => {
    const map = new Map<string, SettingField>();
    if (load.kind === 'ready') {
      for (const f of load.data.fields) map.set(f.attr, f);
    }
    return map;
  }, [load]);

  function setValue(attr: string, value: string): void {
    setSaved(false);
    setFieldError((prev) => (prev && prev.field === attr ? null : prev));
    setLoad((prev) =>
      prev.kind === 'ready'
        ? { kind: 'ready', data: { ...prev.data, values: { ...prev.data.values, [attr]: value } } }
        : prev,
    );
  }

  async function submit(): Promise<void> {
    if (load.kind !== 'ready') return;
    const { values } = load.data;
    const body = {
      reminder_days_threshold: Number(values.reminder_days_threshold),
      missed_events_escalation_count: Number(values.missed_events_escalation_count),
      reminder_send_hour: Number(values.reminder_send_hour),
      all_command_throttle_seconds: Number(values.all_command_throttle_seconds),
      timezone: values.timezone.trim(),
    } satisfies ProjectSettingsUpdate;

    setSaving(true);
    setSaved(false);
    setFieldError(null);
    setSubmitError(null);
    try {
      const fresh = await saveProjectSettings(project, body);
      setLoad({
        kind: 'ready',
        data: {
          projectName: fresh.project_name,
          fields: fresh.fields,
          values: toValues(fresh),
        },
      });
      setSaved(true);
    } catch (error: unknown) {
      if (error instanceof SettingFieldError) {
        setFieldError({ field: error.field, message: error.message });
      } else if (error instanceof ApiError && error.status === 401) {
        setSubmitError('Сессия устарела — переоткройте Mini App.');
      } else if (error instanceof ApiError && error.status === 403) {
        setSubmitError('Настройки может менять только администратор проекта.');
      } else if (error instanceof ApiError && error.status === 422) {
        setSubmitError('Проверьте значения полей.');
      } else {
        const detail = error instanceof ApiError ? error.detail : 'network';
        setSubmitError(`Не удалось сохранить. Код: ${detail}`);
      }
    } finally {
      setSaving(false);
    }
  }

  if (load.kind === 'loading') {
    return <Shell onBack={onBack}><Centered title="Загрузка…" /></Shell>;
  }
  if (load.kind === 'not-registered') {
    return (
      <Shell onBack={onBack}>
        <Centered
          title="Вы не участник этого проекта"
          text="Зарегистрируйтесь по ссылке из поста регистрации в вашем групповом чате, потом откройте экран заново."
        />
      </Shell>
    );
  }
  if (load.kind === 'not-admin') {
    return (
      <Shell onBack={onBack}>
        <Centered
          title="Нет доступа к настройкам"
          text="Настройки проекта открывают его создатель и администраторы."
        />
      </Shell>
    );
  }
  if (load.kind === 'load-error') {
    return (
      <Shell onBack={onBack}>
        <Centered
          title="Не удалось открыть настройки"
          text={`Попробуйте переоткрыть Mini App. Код: ${load.detail}`}
        />
      </Shell>
    );
  }

  const { data } = load;
  return (
    <Shell onBack={onBack}>
      <div className="st-scroll">
        <p className="st-lead">
          Настройки проекта «{data.projectName}». Те же параметры правит команда{' '}
          <code>/settings</code> в чате проекта.
        </p>

        <Card title="Напоминания и эскалация">
          {ORDER.map((attr) => {
            const spec = fieldByAttr.get(attr);
            const value = data.values[attr] ?? '';
            const err = fieldError && fieldError.field === attr ? fieldError.message : undefined;
            const hint = spec
              ? spec.kind === 'int' && spec.min !== null && spec.max !== null
                ? `${spec.describe}. Допустимо ${spec.min}–${spec.max}.`
                : spec.describe
              : undefined;
            return (
              <Field key={attr} label={LABELS[attr] ?? attr} htmlFor={`st-${attr}`} error={err}>
                <input
                  id={`st-${attr}`}
                  className={`st-input${err ? ' st-input--invalid' : ''}`}
                  type={spec?.kind === 'int' ? 'number' : 'text'}
                  inputMode={spec?.kind === 'int' ? 'numeric' : 'text'}
                  min={spec?.kind === 'int' && spec.min !== null ? spec.min : undefined}
                  max={spec?.kind === 'int' && spec.max !== null ? spec.max : undefined}
                  value={value}
                  onChange={(e) => setValue(attr, e.target.value)}
                  placeholder={attr === 'timezone' ? 'Europe/Moscow' : undefined}
                />
                {hint && <span className="st-hint">{hint}</span>}
              </Field>
            );
          })}
        </Card>

        {saved && <p className="st-saved">Сохранено.</p>}
        {submitError && <p className="st-error">{submitError}</p>}
      </div>

      <div className="st-footer">
        <button
          type="button"
          className="st-submit"
          onClick={() => void submit()}
          disabled={saving}
        >
          {saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </div>
    </Shell>
  );
}

function Shell({ onBack, children }: { onBack: () => void; children: ReactNode }) {
  return (
    <div className="st-screen">
      <ScreenBar onBack={onBack} title="Настройки проекта" />
      {children}
    </div>
  );
}

function Centered({ title, text }: { title: string; text?: string }) {
  return (
    <div className="st-state">
      <h1 className="st-state__title">{title}</h1>
      {text && <p className="st-state__text">{text}</p>}
    </div>
  );
}
