import './backbar.css';

/**
 * Своя строка «назад» для под-экранов Web App (WEBAPP_DESIGN.md, `ScreenBar`).
 * Нужна, потому что кнопка «назад» Telegram есть не на всех клиентах (в
 * частности, на десктопе её может не быть) — на них навигация держится только на
 * этой строке. Показывается родителем лишь когда есть куда возвращаться.
 */
export function BackBar({
  onBack,
  title,
}: {
  onBack: () => void;
  title?: string;
}) {
  return (
    <div className="ui-backbar">
      <button type="button" className="ui-backbar__btn" onClick={onBack}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M15 5l-7 7 7 7" />
        </svg>
        Назад
      </button>
      {title && <span className="ui-backbar__title">{title}</span>}
    </div>
  );
}
