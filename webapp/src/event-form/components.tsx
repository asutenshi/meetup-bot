import type { ReactNode } from 'react';

import type { EventFormMember } from '../api/events';

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
