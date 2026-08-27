import { themeParams } from '@telegram-apps/sdk';

/**
 * Отображение ключей Telegram themeParams на семантические токены
 * WEBAPP_DESIGN.md. Компоненты знают только про токены слева, а не про то,
 * какой themeParams за ними стоит.
 */
function paramsToTokens(): Record<string, string | undefined> {
  const p = themeParams.state();
  return {
    '--tg-bg': p.secondaryBackgroundColor,
    '--tg-section': p.sectionBackgroundColor ?? p.backgroundColor,
    '--tg-text': p.textColor,
    '--tg-hint': p.hintColor,
    '--tg-sep': p.sectionSeparatorColor,
    '--tg-destructive': p.destructiveTextColor,
  };
}

function apply(): void {
  const root = document.documentElement;
  for (const [name, value] of Object.entries(paramsToTokens())) {
    if (value) {
      root.style.setProperty(name, value);
    }
  }
  root.dataset.theme = themeParams.isDark() ? 'dark' : 'light';
}

/**
 * Проставляет токены из themeParams и подписывается на их изменение (смена
 * темы клиента на лету). Вне Telegram (themeParams не смонтирован) — no-op,
 * UI остаётся на фолбэк-палитре из tokens.css. Возвращает функцию отписки.
 */
export function bindThemeParamsToTokens(): () => void {
  if (!themeParams.isMounted()) {
    return () => {};
  }
  apply();
  return themeParams.state.sub(apply);
}
