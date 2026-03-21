/** Calendar date only (e.g. compliance deadlines). Must not use UTC midnight parsing. */
const ISO_DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Format datetime string from API (SQLite "YYYY-MM-DD HH:MM:SS" or ISO 8601) for display.
 * SQLite stores in local time; do not append Z (UTC).
 */
function parseApiDate(value: string | null | undefined): Date | null {
  if (!value || typeof value !== 'string') return null;
  const normalized = value.includes('T') ? value : value.replace(' ', 'T');
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function parseLocalCalendarDate(value: string): Date | null {
  if (!ISO_DATE_ONLY.test(value)) return null;
  const [y, m, d] = value.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string | null {
  const date = parseApiDate(value);
  return date ? date.toLocaleString() : null;
}

export function formatDate(value: string | null | undefined): string | null {
  if (!value || typeof value !== 'string') return null;
  const date = parseLocalCalendarDate(value) ?? parseApiDate(value);
  return date ? date.toLocaleDateString() : null;
}
