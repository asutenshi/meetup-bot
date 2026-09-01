import {
  backButton,
  init,
  miniApp,
  openTelegramLink,
  themeParams,
  viewport,
} from '@tma.js/sdk';

let started = false;

/**
 * Инициализация Telegram SDK. Идемпотентна и безопасна вне Telegram: если
 * приложение открыто не как Mini App, init() бросит — мы это глотаем и
 * работаем в браузерном режиме на фолбэк-токенах (tokens.css). Остальные
 * вызовы защищены `.isAvailable()`.
 */
export function initTelegram(): void {
  if (started) {
    return;
  }
  started = true;

  try {
    init();
  } catch {
    return;
  }

  if (miniApp.mount.isAvailable()) {
    miniApp.mount();
  }

  if (themeParams.mount.isAvailable()) {
    themeParams.mount();
  }

  if (viewport.mount.isAvailable()) {
    void viewport.mount();
    if (viewport.expand.isAvailable()) {
      viewport.expand();
    }
  }

  // Кнопка «назад» Telegram — навигация между экранами хаба (задача 2.9.1).
  if (backButton.mount.isAvailable()) {
    backButton.mount();
  }

  // Снимает нативный лоадер Telegram — экран готов к показу.
  if (miniApp.ready.isAvailable()) {
    miniApp.ready();
  }
}

/**
 * Показать/скрыть кнопку «назад» Telegram. Вне Telegram и на клиентах без
 * поддержки — no-op.
 */
export function setBackButtonVisible(visible: boolean): void {
  try {
    if (visible) {
      if (backButton.show.isAvailable()) backButton.show();
    } else if (backButton.hide.isAvailable()) {
      backButton.hide();
    }
  } catch {
    // клиент не поддерживает кнопку «назад» — навигация остаётся на UI-кнопках
  }
}

/**
 * Подписка на нажатие кнопки «назад» Telegram. Возвращает функцию отписки
 * (пустую вне Telegram).
 */
export function onBackButtonClick(listener: () => void): () => void {
  try {
    if (backButton.onClick.isAvailable()) {
      return backButton.onClick(listener);
    }
  } catch {
    // no-op
  }
  return () => {};
}

/**
 * Закрыть Mini App (кнопка «Закрыть» на экране успеха). Вне Telegram — no-op.
 */
export function closeMiniApp(): void {
  if (miniApp.close.isAvailable()) {
    miniApp.close();
  }
}

/**
 * Открыть ссылку на Telegram (`t.me/…`) — переход к анонсу с экрана мероприятия.
 * Внутри Telegram это делает `openTelegramLink` (закрывает Mini App и открывает
 * чат), вне — обычное `window.open`.
 */
export function openTelegramLinkSafe(url: string): void {
  try {
    if (openTelegramLink.isAvailable()) {
      openTelegramLink(url);
      return;
    }
  } catch {
    // клиент не поддерживает — падаем на window.open ниже
  }
  window.open(url, '_blank', 'noopener');
}
