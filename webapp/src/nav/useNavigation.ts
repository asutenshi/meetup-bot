import { useCallback, useEffect, useRef, useState } from 'react';

import { onBackButtonClick, setBackButtonVisible } from '../telegram/init';
import { isHistoryEntry, parseView, viewUrl, type HistoryEntry, type View } from './navigation';

/**
 * Стек экранов Web App поверх History API (задача 2.9.1).
 *
 * - начальный экран — из `window.location` (кнопки бота кладут контекст в URL);
 * - `navigate` кладёт запись через `history.pushState` и синхронизирует адресную
 *   строку (`apiFetch` читает `project` из неё);
 * - `popstate` (в т.ч. системная кнопка «назад» и кнопка «назад» Telegram, которую
 *   мы дергаем через `history.back()`) восстанавливает экран из записи;
 * - кнопка «назад» Telegram видна, пока в стеке есть куда возвращаться.
 */
export function useNavigation(): {
  view: View;
  navigate: (view: View) => void;
  back: () => void;
} {
  const [entry, setEntry] = useState<HistoryEntry>(() => {
    const current = window.history.state;
    if (isHistoryEntry(current)) {
      return current;
    }
    const initial: HistoryEntry = { view: parseView(window.location.search), depth: 0 };
    window.history.replaceState(initial, '');
    return initial;
  });

  const depthRef = useRef(entry.depth);
  depthRef.current = entry.depth;

  useEffect(() => {
    function onPopState(event: PopStateEvent): void {
      setEntry(
        isHistoryEntry(event.state)
          ? event.state
          : { view: parseView(window.location.search), depth: 0 },
      );
    }
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    const off = onBackButtonClick(() => window.history.back());
    return off;
  }, []);

  useEffect(() => {
    setBackButtonVisible(entry.depth > 0);
  }, [entry.depth]);

  const navigate = useCallback((view: View) => {
    const next: HistoryEntry = { view, depth: depthRef.current + 1 };
    window.history.pushState(next, '', viewUrl(view));
    setEntry(next);
  }, []);

  const back = useCallback(() => window.history.back(), []);

  return { view: entry.view, navigate, back };
}
