import { init, themeParams, viewport } from '@telegram-apps/sdk';

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

  if (themeParams.mountSync.isAvailable()) {
    themeParams.mountSync();
  }

  if (viewport.mount.isAvailable()) {
    void viewport.mount();
    if (viewport.expand.isAvailable()) {
      viewport.expand();
    }
  }
}
