import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

function sentryConnectSrcAllowance(dsn: string | undefined): string {
  const trimmed = dsn?.trim();
  if (!trimmed) {
    return '';
  }
  try {
    const u = new URL(trimmed);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') {
      return '';
    }
    return ` ${u.origin}`;
  } catch {
    return '';
  }
}

// Document-level CSP for the Vite dev server (and preview). Must match
// claim_agent.api.server._base_security_response_headers so the dashboard HTML
// gets the same policy as API hardening comments describe.
// connect-src includes the Sentry ingest origin parsed from VITE_SENTRY_DSN when set.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const sentryAllow = sentryConnectSrcAllowance(env.VITE_SENTRY_DSN);
  const documentCsp =
    "default-src 'self'; " +
    "script-src 'self'; " +
    "style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data: blob:; " +
    "font-src 'self' data:; " +
    `connect-src 'self'${sentryAllow}; ` +
    "object-src 'none'; " +
    "base-uri 'self'; " +
    "frame-ancestors 'none'";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      headers: {
        'Content-Security-Policy': documentCsp,
      },
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    preview: {
      headers: {
        'Content-Security-Policy': documentCsp,
      },
    },
  };
});
