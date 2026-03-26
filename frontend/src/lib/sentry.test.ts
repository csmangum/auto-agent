import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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
});
