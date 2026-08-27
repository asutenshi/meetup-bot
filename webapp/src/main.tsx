import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import '@telegram-apps/telegram-ui/dist/styles.css';
import './theme/tokens.css';
import './index.css';

import { App } from './App';
import { initTelegram } from './telegram/init';
import { bindThemeParamsToTokens } from './theme/applyThemeParams';

initTelegram();
bindThemeParamsToTokens();

// Опциональное переопределение фирменного акцента на этапе сборки:
//   VITE_ACCENT=#4a63e7 npm run build
// Значение по умолчанию живёт в одном месте — --accent в theme/tokens.css
// (WEBAPP_DESIGN.md, «Акцентный цвет — не выбран, держим сменяемым»).
const envAccent = import.meta.env.VITE_ACCENT;
if (envAccent) {
  document.documentElement.style.setProperty('--accent', envAccent);
}

const rootEl = document.getElementById('root');
if (!rootEl) {
  throw new Error('#root not found');
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
