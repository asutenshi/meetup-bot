import { useEffect, useRef, useState } from 'react';

import './screenbar.css';

export type ScreenBarAction = {
  label: string;
  onClick: () => void;
  /** Помечает пункт как деструктивный (напр. «Отменить мероприятие»). */
  danger?: boolean;
};

/**
 * Своя шапка под-экрана (WEBAPP_DESIGN.md, `ScreenBar`, задача 2.9.2): «назад»
 * слева (синхронна с кнопкой «назад» Telegram — обе зовут один `onBack`), справа
 * — меню «⋯» с действиями организатора. Без действий меню не рисуется.
 *
 * «Назад» здесь обязательна: на клиентах без кнопки «назад» Telegram (десктоп)
 * это единственный путь обратно.
 */
export function ScreenBar({
  onBack,
  title,
  actions = [],
}: {
  onBack: () => void;
  title?: string;
  actions?: ScreenBarAction[];
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(event: MouseEvent): void {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  return (
    <div className="ui-screenbar">
      <button type="button" className="ui-screenbar__back" onClick={onBack}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M15 5l-7 7 7 7" />
        </svg>
        Назад
      </button>

      {title && <span className="ui-screenbar__title">{title}</span>}

      {actions.length > 0 && (
        <div className="ui-screenbar__menu" ref={menuRef}>
          <button
            type="button"
            className="ui-screenbar__more"
            aria-label="Действия"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="5" cy="12" r="1.6" />
              <circle cx="12" cy="12" r="1.6" />
              <circle cx="19" cy="12" r="1.6" />
            </svg>
          </button>
          {open && (
            <ul className="ui-screenbar__list" role="menu">
              {actions.map((action) => (
                <li key={action.label}>
                  <button
                    type="button"
                    role="menuitem"
                    className={`ui-screenbar__item${
                      action.danger ? ' ui-screenbar__item--danger' : ''
                    }`}
                    onClick={() => {
                      setOpen(false);
                      action.onClick();
                    }}
                  >
                    {action.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
