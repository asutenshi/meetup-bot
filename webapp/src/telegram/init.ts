import { init, miniApp, themeParams, viewport } from '@tma.js/sdk';

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

  // Снимает нативный лоадер Telegram — экран готов к показу.
  if (miniApp.ready.isAvailable()) {
    miniApp.ready();
  }
}

/**
 * Закрыть Mini App (кнопка «Закрыть» на экране успеха). Вне Telegram — no-op.
 */
export function closeMiniApp(): void {
  if (miniApp.close.isAvailable()) {
    miniApp.close();
  }
}
