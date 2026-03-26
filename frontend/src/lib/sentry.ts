import * as Sentry from '@sentry/react';

/**
 * Initializes Sentry when VITE_SENTRY_DSN is set. No-op otherwise (e.g. CI without DSN).
 */
export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN?.trim();
  if (!dsn) {
    return;
  }

  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
  });
}
