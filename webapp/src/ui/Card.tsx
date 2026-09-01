import type { ReactNode } from 'react';

import './ui.css';

/**
 * Смысловой блок-карточка (WEBAPP_DESIGN.md, «Секции-карточки»): скруглённый
 * контейнер с тонкой рамкой и мягкой тенью, заголовок с опциональной иконкой
 * цвета `--accent`. Вынесен из `event-form/` в общий `src/ui/` — используется и
 * формой мероприятия, и домашним экраном-хабом (задача 2.9.1).
 *
 * `icon` — содержимое `<svg viewBox="0 0 24 24">` (набор `<path>`), а не готовый
 * `<svg>`: обёртка и размеры — на карточке.
 */
export function Card({
  icon,
  title,
  action,
  children,
}: {
  icon?: ReactNode;
  title: string;
  /** Необязательный контрол справа от заголовка (например, ссылка-действие). */
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="ui-card">
      {(title || action) && (
        <div className="ui-card__head">
          {icon && (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              {icon}
            </svg>
          )}
          <span className="ui-card__title">{title}</span>
          {action && <span className="ui-card__action">{action}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

/**
 * Обёртка «подпись сверху + контрол» (WEBAPP_DESIGN.md, `Field`). Бейдж
 * «необязательно» справа от подписи, строка ошибки снизу.
 */
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
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={htmlFor}>
        {label}
        {optional && <span className="ui-badge">необязательно</span>}
      </label>
      {children}
      {error && <span className="ui-error">{error}</span>}
    </div>
  );
}
