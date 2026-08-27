/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Переопределение фирменного акцента на этапе сборки (см. main.tsx, WEBAPP_DESIGN.md). */
  readonly VITE_ACCENT?: string;
  /** База для запросов к API; по умолчанию '/api'. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
