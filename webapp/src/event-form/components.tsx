import { useRef, type ReactNode } from 'react';

import type { EventFormMember } from '../api/events';
import { formatDate } from './datetime';

/** Иконки заголовков карточек (16–17 px, цвет — var(--accent) через CSS). */
const ICONS = {
  when: (
    <path d="M3 5h18v16H3zM3 10h18M8 3v4M16 3v4" />
  ),
  where: (
    <path d="M12 21s7-6.2 7-11a7 7 0 10-14 0c0 4.8 7 11 7 11zM12 12.6a2.6 2.6 0 100-5.2 2.6 2.6 0 000 5.2z" />
  ),
  about: (
    <path d="M5 4h14v16H5zM9 9h6M9 13h6M9 17h4" />
  ),
  money: (
    <path d="M3 6h18v13H3zM3 10h18M15 15h3" />
  ),
  people: (
    <path d="M9 11a3.2 3.2 0 100-6.4A3.2 3.2 0 009 11zM3.6 19c0-3 2.4-5 5.4-5s5.4 2 5.4 5M16 5.2a3 3 0 010 5.6M18.6 19c0-2.4-1.2-4.1-3.1-4.8" />
  ),
} as const;

export function Card({
  icon,
  title,
  children,
}: {
  icon: keyof typeof ICONS;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="ef-card">
      <div className="ef-card__head">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          {ICONS[icon]}
        </svg>
        {title}
      </div>
      {children}
    </section>
  );
}

export function Field({
  label,
  htmlFor,
  optional = false,
  error,
  children,
}: {
  label: string;
  htmlFor?: string;
  optional?: boolean;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="ef-field">
      <label className="ef-field__label" htmlFor={htmlFor}>
        {label}
        {optional && <span className="ef-badge">необязательно</span>}
      </label>
      {children}
      {error && <span className="ef-error">{error}</span>}
    </div>
  );
}

/**
 * Строка-пикер даты (PickerRow из WEBAPP_DESIGN.md): своя строка с
 * человекочитаемым значением и шевроном поверх нативного `<input type="date">`
 * (`opacity: 0`). Календарь остаётся нативным (ОС/браузер) — `input.showPicker()`
 * для `type="date"` открывает полноценный выбор и на десктопе тоже, — а внешний
 * вид по нашим токенам, так уходит слишком тёмный виджет при тёмном акценте.
 * Время вводится отдельным видимым `<input type="time">` (см. EventForm):
 * единый `datetime-local` для десктопа частично не редактируется — там
 * `showPicker()` открывает только календарь, а сегменты времени спрятаны.
 *
 * Реальный фокусируемый контрол и цель `<label>` — сам `<input>`; шеврон и
 * значение помечены `aria-hidden`.
 */
export function PickerRow({
  id,
  value,
  placeholder,
  min,
  invalid = false,
  onChange,
  onClear,
}: {
  id?: string;
  /** Значение в формате `YYYY-MM-DD`. */
  value: string;
  placeholder: string;
  min?: string;
  invalid?: boolean;
  onChange: (value: string) => void;
  /** Показать кнопку очистки (для необязательной даты). */
  onClear?: () => void;
}) {
  const nativeRef = useRef<HTMLInputElement>(null);

  function openPicker(): void {
    const el = nativeRef.current;
    if (el && typeof el.showPicker === 'function') {
      try {
        el.showPicker();
      } catch {
        // showPicker требует жеста пользователя / не поддержан — на телефоне
        // нативный виджет и так откроется по тапу на сам input.
      }
    }
  }

  const filled = value !== '';

  return (
    <div className={`ef-picker${invalid ? ' ef-picker--invalid' : ''}`}>
      <span
        className={`ef-picker__face${filled ? '' : ' ef-picker__face--empty'}`}
        aria-hidden="true"
      >
        {filled ? formatDate(value) : placeholder}
      </span>
      {onClear && filled && (
        <button
          type="button"
          className="ef-picker__clear"
          aria-label="Убрать дату"
          onClick={onClear}
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M5 5l10 10M15 5L5 15" />
          </svg>
        </button>
      )}
      <span className="ef-picker__chev" aria-hidden="true">
        <svg viewBox="0 0 20 20">
          <path d="M7.5 4l6 6-6 6" />
        </svg>
      </span>
      <input
        ref={nativeRef}
        id={id}
        className="ef-picker__native"
        type="date"
        value={value}
        min={min}
        onClick={openPicker}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

/**
 * Список участников проекта с чекбоксами — выбор со-организаторов. По умолчанию
 * отмечен создатель; в отличие от прочих форм выбора людей, он может снять
 * галочку и с себя (TZ §4.3 п. 2) — тогда мероприятие публикуется без
 * организатора.
 */
export function PeopleList({
  members,
  selected,
  onToggle,
}: {
  members: EventFormMember[];
  selected: ReadonlySet<number>;
  onToggle: (userId: number) => void;
}) {
  return (
    <div className="ef-people">
      {members.map((member) => (
        <label className="ef-person" key={member.user_id}>
          <input
            type="checkbox"
            checked={selected.has(member.user_id)}
            onChange={() => onToggle(member.user_id)}
          />
          <span className="ef-avatar" aria-hidden="true">
            {initials(member.name)}
          </span>
          <span className="ef-person__name">
            {member.name}
            {member.is_self && <span className="ef-person__me"> — вы</span>}
          </span>
          <span className="ef-check" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <path d="M4 10.5l4 4 8-9" />
            </svg>
          </span>
        </label>
      ))}
    </div>
  );
}
