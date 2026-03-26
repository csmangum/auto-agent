/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Sentry DSN. When set, error tracking is enabled. */
  readonly VITE_SENTRY_DSN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
