import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Event as SentryEvent } from '@sentry/react';

const mockInit = vi.fn();

vi.mock('@sentry/react', () => ({
  init: mockInit,
}));

describe('initSentry', () => {
  beforeEach(() => {
    vi.resetModules();
    mockInit.mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('does not call Sentry.init when VITE_SENTRY_DSN is unset', async () => {
    vi.stubEnv('VITE_SENTRY_DSN', '');
    const { initSentry } = await import('./sentry');
    initSentry();
    expect(mockInit).not.toHaveBeenCalled();
  });

  it('does not call Sentry.init when VITE_SENTRY_DSN is whitespace only', async () => {
    vi.stubEnv('VITE_SENTRY_DSN', '   ');
    const { initSentry } = await import('./sentry');
    initSentry();
    expect(mockInit).not.toHaveBeenCalled();
  });

  it('calls Sentry.init with trimmed dsn when VITE_SENTRY_DSN is set', async () => {
    const dsn = '  https://key@o1.ingest.sentry.io/1  ';
    vi.stubEnv('VITE_SENTRY_DSN', dsn);
    const { initSentry } = await import('./sentry');
    initSentry();
    expect(mockInit).toHaveBeenCalledOnce();
    expect(mockInit).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: 'https://key@o1.ingest.sentry.io/1',
        environment: 'test',
      }),
    );
  });

  it('registers beforeSend in Sentry.init options', async () => {
    vi.stubEnv('VITE_SENTRY_DSN', 'https://key@o1.ingest.sentry.io/1');
    const { initSentry } = await import('./sentry');
    initSentry();
    expect(mockInit).toHaveBeenCalledWith(
      expect.objectContaining({ beforeSend: expect.any(Function) }),
    );
  });
});

describe('scrubString', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('redacts email addresses', async () => {
    const { scrubString } = await import('./sentry');
    expect(scrubString('Contact user@example.com for details')).toBe(
      'Contact [REDACTED_EMAIL] for details',
    );
  });

  it('redacts JWT tokens', async () => {
    const { scrubString } = await import('./sentry');
    const jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    expect(scrubString(`Token: ${jwt}`)).toBe('Token: [REDACTED_TOKEN]');
  });

  it('redacts UUID-shaped claim IDs', async () => {
    const { scrubString } = await import('./sentry');
    expect(scrubString('Claim 550e8400-e29b-41d4-a716-446655440000 not found')).toBe(
      'Claim [REDACTED_ID] not found',
    );
  });

  it('handles strings with no PII unchanged', async () => {
    const { scrubString } = await import('./sentry');
    expect(scrubString('Something went wrong on line 42')).toBe(
      'Something went wrong on line 42',
    );
  });

  it('redacts multiple PII patterns in one string', async () => {
    const { scrubString } = await import('./sentry');
    const input = 'User user@example.com filed claim 550e8400-e29b-41d4-a716-446655440000';
    const output = scrubString(input);
    expect(output).toContain('[REDACTED_EMAIL]');
    expect(output).toContain('[REDACTED_ID]');
    expect(output).not.toContain('user@example.com');
    expect(output).not.toContain('550e8400-e29b-41d4-a716-446655440000');
  });
});

describe('beforeSend', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('strips user context from the event', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      user: { id: 'u1', email: 'user@example.com', username: 'alice' },
    };
    const result = beforeSend(event);
    expect(result.user).toBeUndefined();
  });

  it('filters Authorization header', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      request: { headers: { Authorization: 'Bearer secret', 'Content-Type': 'application/json' } },
    };
    const result = beforeSend(event);
    expect((result.request!.headers as Record<string, string>)['Authorization']).toBe('[Filtered]');
    expect((result.request!.headers as Record<string, string>)['Content-Type']).toBe(
      'application/json',
    );
  });

  it('filters Cookie header (case-insensitive)', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      request: { headers: { cookie: 'session=abc123' } },
    };
    const result = beforeSend(event);
    expect((result.request!.headers as Record<string, string>)['cookie']).toBe('[Filtered]');
  });

  it('filters X-Api-Key and X-Auth-Token headers', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      request: { headers: { 'X-Api-Key': 'secret', 'X-Auth-Token': 'tok' } },
    };
    const result = beforeSend(event);
    const headers = result.request!.headers as Record<string, string>;
    expect(headers['X-Api-Key']).toBe('[Filtered]');
    expect(headers['X-Auth-Token']).toBe('[Filtered]');
  });

  it('strips request data and cookies', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      request: { data: { password: 'secret' }, cookies: { session: 'abc' } },
    };
    const result = beforeSend(event);
    expect(result.request!.data).toBeUndefined();
    expect(result.request!.cookies).toBeUndefined();
  });

  it('scrubs PII from exception values', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      exception: {
        values: [{ value: 'Failed to fetch claim 550e8400-e29b-41d4-a716-446655440000' }],
      },
    };
    const result = beforeSend(event);
    expect(result.exception!.values![0].value).toBe('Failed to fetch claim [REDACTED_ID]');
  });

  it('scrubs PII from the top-level message', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = { message: 'Error for user@example.com' };
    const result = beforeSend(event);
    expect(result.message).toBe('Error for [REDACTED_EMAIL]');
  });

  it('scrubs PII from breadcrumb messages', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      breadcrumbs: {
        values: [{ message: 'Loaded claim 550e8400-e29b-41d4-a716-446655440000', timestamp: 0 }],
      },
    };
    const result = beforeSend(event);
    expect(result.breadcrumbs!.values![0].message).toBe('Loaded claim [REDACTED_ID]');
  });

  it('scrubs PII from breadcrumb data values', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      breadcrumbs: {
        values: [
          {
            message: 'API call',
            data: { userId: 'user@example.com', action: 'view' },
            timestamp: 0,
          },
        ],
      },
    };
    const result = beforeSend(event);
    expect(result.breadcrumbs!.values![0].data!['userId']).toBe('[REDACTED_EMAIL]');
    expect(result.breadcrumbs!.values![0].data!['action']).toBe('view');
  });

  it('leaves events without PII unchanged (except user)', async () => {
    const { beforeSend } = await import('./sentry');
    const event: SentryEvent = {
      message: 'Something went wrong on line 42',
      request: { url: 'https://app.example.com/claims', headers: { 'Content-Type': 'text/html' } },
    };
    const result = beforeSend(event);
    expect(result.message).toBe('Something went wrong on line 42');
    expect((result.request!.headers as Record<string, string>)['Content-Type']).toBe('text/html');
  });
});
