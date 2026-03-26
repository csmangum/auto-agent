/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Sentry DSN. When set, error tracking is enabled. */
  readonly VITE_SENTRY_DSN?: string;
  /** Optional release string for Sentry (e.g. git SHA or semver from CI). */
  readonly VITE_SENTRY_RELEASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
