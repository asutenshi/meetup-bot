import { useCallback, useEffect, useState } from 'react';

import { onBackButtonClick, setBackButtonVisible } from '../telegram/init';
import { parseView, viewUrl, type View } from './navigation';

/**
 * Стек экранов Web App (задача 2.9.1).
 *
 * - начальный экран — из `window.location` (кнопки бота кладут контекст в URL);
 * - `navigate` кладёт экран в стек, `back` снимает верхний;
 * - адресная строка подтягивается под текущий экран (`history.replaceState`) —
 *   только чтобы `apiFetch` видел `project`; историю браузера не копим;
 * - кнопка «назад» Telegram (там, где она есть) дублирует `back`; на клиентах
 *   без неё навигация держится на своей строке «назад» (`BackBar`).
 */
export function useNavigation(): {
  view: View;
  /** Есть ли экран под текущим (кнопку «назад» показываем только тогда). */
  canGoBack: boolean;
  navigate: (view: View) => void;
  back: () => void;
} {
  const [stack, setStack] = useState<View[]>(() => [parseView(window.location.search)]);
  const view = stack[stack.length - 1];
  const canGoBack = stack.length > 1;

  const navigate = useCallback((next: View) => {
    setStack((prev) => [...prev, next]);
  }, []);

  const back = useCallback(() => {
    setStack((prev) => (prev.length > 1 ? prev.slice(0, -1) : prev));
  }, []);

  // Адресная строка = текущий экран (для чтения `project` в apiFetch).
  useEffect(() => {
    window.history.replaceState(null, '', viewUrl(view));
  }, [view]);

  // Кнопка «назад» Telegram → тот же `back`. `back` стабилен (deps []).
  useEffect(() => onBackButtonClick(back), [back]);
  useEffect(() => {
    setBackButtonVisible(canGoBack);
  }, [canGoBack]);

  return { view, canGoBack, navigate, back };
}
