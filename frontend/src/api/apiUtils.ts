/**
 * Shared API utility functions.
 */

export function parseApiError(status: number, text: string): string {
  let msg = `API error ${status}: ${text.slice(0, 200)}`;
  try {
    const body = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> };
    if (typeof body?.detail === 'string') {
      msg = body.detail;
    } else if (Array.isArray(body?.detail)) {
      const parts = body.detail
        .map((d) => (typeof d === 'object' && d?.msg ? d.msg : null))
        .filter(Boolean);
      if (parts.length > 0) msg = parts.join('; ');
    }
  } catch {
    /* keep msg */
  }
  return msg;
}
