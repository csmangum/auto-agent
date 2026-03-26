import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Document-level CSP for the Vite dev server (and preview). Must match
// claim_agent.api.server._base_security_response_headers so the dashboard HTML
// gets the same policy as API hardening comments describe.
// https://*.ingest.sentry.io is added to connect-src to allow Sentry error
// reporting when VITE_SENTRY_DSN is configured.
const documentCsp =
  "default-src 'self'; " +
  "script-src 'self'; " +
  "style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob:; " +
  "font-src 'self' data:; " +
  "connect-src 'self' https://*.ingest.sentry.io; " +
  "object-src 'none'; " +
  "base-uri 'self'; " +
  "frame-ancestors 'none'";

export default defineConfig({
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
});
