import { useCallback, useEffect, useState } from 'react';

import { onBackButtonClick, setBackButtonVisible } from '../telegram/init';
import { parseView, viewUrl, type View } from './navigation';

/**
 * Стек экранов Web App (задача 2.9.1).
 *
 * - начальный экран — из `window.location` (кнопки бота кладут контекст в URL);
 * - `navigate` кладёт экран в стек, `back` снимает верхний; оба сразу же (синхронно,
 *   а не в `useEffect`) подтягивают адресную строку под новый экран
 *   (`history.replaceState`) — только чтобы `apiFetch` видел `project`, историю
 *   браузера не копим. Важно делать это синхронно: эффекты дочернего экрана (форма
 *   грузит контекст на маунте через `apiFetch`) в React выполняются раньше эффекта
 *   родителя, так что при обновлении URL в `useEffect` `apiFetch` успевал бы
 *   выстрелить со старым `location.search` (без `project` при переходе с хаба).
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
    window.history.replaceState(null, '', viewUrl(next));
    setStack((prev) => [...prev, next]);
  }, []);

  const back = useCallback(() => {
    setStack((prev) => {
      if (prev.length <= 1) return prev;
      const nextStack = prev.slice(0, -1);
      window.history.replaceState(null, '', viewUrl(nextStack[nextStack.length - 1]));
      return nextStack;
    });
  }, []);

  // Кнопка «назад» Telegram → тот же `back`. `back` стабилен (deps []).
  useEffect(() => onBackButtonClick(back), [back]);
  useEffect(() => {
    setBackButtonVisible(canGoBack);
  }, [canGoBack]);

  return { view, canGoBack, navigate, back };
}
