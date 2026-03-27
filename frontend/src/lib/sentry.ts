import * as Sentry from '@sentry/react';

/**
 * Allowed fields in Sentry events for this application:
 *
 * ALLOWED:
 *   - event.exception / event.message – exception type, file, line number, stack frames
 *     (string values are PII-scrubbed before sending)
 *   - event.request.url – page URL only
 *   - event.environment – from import.meta.env.MODE
 *   - event.release – from VITE_SENTRY_RELEASE
 *   - event.level, event.timestamp, event.sdk, event.platform
 *   - event.breadcrumbs – messages and data are PII-scrubbed
 *
 * NOT SENT (stripped by beforeSend):
 *   - event.user – stripped entirely; we never send user identifiers
 *   - request headers: Authorization, Cookie, X-Api-Key, X-Auth-Token → "[Filtered]"
 *   - request body (event.request.data) and cookies (event.request.cookies) – deleted
 *   - any string matching known PII patterns:
 *       • email addresses       → [REDACTED_EMAIL]
 *       • JWT tokens            → [REDACTED_TOKEN]
 *       • UUID-shaped claim IDs → [REDACTED_ID]
 */

/** Sensitive patterns to redact from string values in Sentry events. */
const REDACT_PATTERNS: Array<{ pattern: RegExp; replacement: string }> = [
  // Email addresses
  {
    pattern: /\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b/g,
    replacement: '[REDACTED_EMAIL]',
  },
  // JWT / Bearer tokens (base64url header.payload.signature)
  {
    pattern: /eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]*/g,
    replacement: '[REDACTED_TOKEN]',
  },
  // UUID-shaped claim / entity IDs
  {
    pattern: /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi,
    replacement: '[REDACTED_ID]',
  },
];

/** Request headers that must be filtered out before the event is sent. */
const SENSITIVE_HEADERS = new Set(['authorization', 'cookie', 'x-api-key', 'x-auth-token']);

/** Scrub PII patterns from a single string value. */
export function scrubString(value: string): string {
  let result = value;
  for (const { pattern, replacement } of REDACT_PATTERNS) {
    result = result.replace(pattern, replacement);
  }
  return result;
}

/** Recursively scrub PII from an arbitrary value (objects, arrays, strings). */
function scrubValue(value: unknown): unknown {
  if (typeof value === 'string') {
    return scrubString(value);
  }
  if (Array.isArray(value)) {
    return value.map(scrubValue);
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, scrubValue(v)]),
    );
  }
  return value;
}

/**
 * Strip PII from a Sentry event before it is sent.
 *
 * Exported for unit testing; also registered as the `beforeSend` callback in {@link initSentry}.
 */
export function beforeSend(event: Sentry.Event): Sentry.Event {
  // 1. Drop user context entirely – never send user identifiers.
  delete event.user;

  // 2. Strip sensitive request headers, body, and cookies.
  if (event.request) {
    if (event.request.headers) {
      const headers = event.request.headers as Record<string, string>;
      for (const key of Object.keys(headers)) {
        if (SENSITIVE_HEADERS.has(key.toLowerCase())) {
          headers[key] = '[Filtered]';
        }
      }
    }
    delete event.request.data;
    delete event.request.cookies;
  }

  // 3. Scrub PII patterns from exception values.
  if (event.exception?.values) {
    for (const ex of event.exception.values) {
      if (ex.value) {
        ex.value = scrubString(ex.value);
      }
    }
  }

  // 4. Scrub PII patterns from the top-level message.
  if (event.message) {
    event.message = scrubString(event.message);
  }

  // 5. Scrub breadcrumb messages and data.
  if (event.breadcrumbs) {
    for (const crumb of event.breadcrumbs) {
      if (crumb.message) {
        crumb.message = scrubString(crumb.message);
      }
      if (crumb.data) {
        crumb.data = scrubValue(crumb.data) as Record<string, unknown>;
      }
    }
  }

  return event;
}

/**
 * Initializes Sentry when VITE_SENTRY_DSN is set. No-op otherwise (e.g. CI without DSN).
 */
export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN?.trim();
  if (!dsn) {
    return;
  }

  const release = import.meta.env.VITE_SENTRY_RELEASE?.trim();

  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    tracesSampleRate: 0,
    ...(release ? { release } : {}),
    beforeSend,
  });
}
