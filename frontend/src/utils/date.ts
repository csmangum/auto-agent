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

export function formatDateTime(value: string | null | undefined): string | null {
  const date = parseApiDate(value);
  return date ? date.toLocaleString() : null;
}

export function formatDate(value: string | null | undefined): string | null {
  const date = parseApiDate(value);
  return date ? date.toLocaleDateString() : null;
}
