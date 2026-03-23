/**
 * API client for the repair shop self-service portal.
 * Sends X-Repair-Shop-Access-Token on each request; claim id is in the URL path.
 */

const BASE = '/api/repair-portal';

export interface RepairPortalSession {
  token: string;
  claimId: string;
}

const SESSION_KEY = 'repair_portal_session';

export function getRepairPortalSession(): RepairPortalSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as RepairPortalSession;
  } catch {
    return null;
  }
}

export function setRepairPortalSession(session: RepairPortalSession): void {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearRepairPortalSession(): void {
  sessionStorage.removeItem(SESSION_KEY);
}

function getRepairPortalHeaders(): HeadersInit {
  const session = getRepairPortalSession();
  const headers: Record<string, string> = {};
  if (session?.token) {
    headers['X-Repair-Shop-Access-Token'] = session.token;
  }
  return headers;
}

function parseApiError(status: number, text: string): string {
  let msg = `API error ${status}: ${text.slice(0, 200)}`;
  try {
    const body = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> };
    if (typeof body?.detail === 'string') msg = body.detail;
    else if (Array.isArray(body?.detail)) {
      const parts = body.detail
        .map((d) => (typeof d === 'object' && d?.msg ? d.msg : null))
        .filter(Boolean);
      if (parts.length > 0) msg = (parts as string[]).join('; ');
    }
  } catch {
    /* keep msg */
  }
  return msg;
}

async function fetchRepairPortal<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers: { ...getRepairPortalHeaders(), ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseApiError(res.status, text));
  }
  return res.json() as Promise<T>;
}

async function postRepairPortalJSON<T>(url: string, body: unknown): Promise<T> {
  return fetchRepairPortal<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const repairPortalApi = {
  getClaim: (claimId: string) =>
    fetchRepairPortal<Record<string, unknown>>(`/claims/${claimId}`),

  getClaimHistory: (claimId: string) =>
    fetchRepairPortal<{ history: unknown[] }>(`/claims/${claimId}/history`),

  getRepairStatus: (claimId: string) =>
    fetchRepairPortal<{
      latest: Record<string, unknown> | null;
      history: unknown[];
      cycle_time_days: number | null;
    }>(`/claims/${claimId}/repair-status`),

  postRepairStatus: (
    claimId: string,
    body: { status: string; authorization_id?: string | null; notes?: string | null }
  ) =>
    postRepairPortalJSON<{ ok: boolean; repair_status_id: number }>(
      `/claims/${claimId}/repair-status`,
      body
    ),

  postSupplemental: (
    claimId: string,
    body: {
      supplemental_damage_description: string;
      reported_by?: 'shop' | 'adjuster' | 'policyholder' | null;
    }
  ) =>
    postRepairPortalJSON<{
      claim_id: string;
      status: string;
      supplemental_amount?: number | null;
      summary: string;
    }>(`/claims/${claimId}/supplemental`, body),
};
