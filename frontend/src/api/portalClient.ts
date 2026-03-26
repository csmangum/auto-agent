/**
 * API client for the Claimant Self-Service Portal.
 * Sends verification headers (token, or policy+vin, or email) on each request.
 */

import { API_VERSION } from './config';

const BASE = `${API_VERSION}/portal`;

export interface PortalSession {
  token?: string;
  policyNumber?: string;
  vin?: string;
  email?: string;
}

const SESSION_KEY = 'portal_session';

export function getPortalSession(): PortalSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PortalSession;
  } catch {
    return null;
  }
}

export function setPortalSession(session: PortalSession): void {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearPortalSession(): void {
  sessionStorage.removeItem(SESSION_KEY);
}

function getPortalHeaders(): HeadersInit {
  const session = getPortalSession();
  const headers: Record<string, string> = {};
  if (!session) return headers;
  if (session.token) {
    headers['X-Claim-Access-Token'] = session.token;
  }
  if (session.policyNumber) headers['X-Policy-Number'] = session.policyNumber;
  if (session.vin) headers['X-Vin'] = session.vin;
  if (session.email) headers['X-Email'] = session.email;
  // HTTP headers are case-insensitive; backend uses lowercase lookup
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

async function fetchPortal<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers: { ...getPortalHeaders(), ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseApiError(res.status, text));
  }
  return res.json() as Promise<T>;
}

async function postPortalJSON<T>(url: string, body: unknown): Promise<T> {
  return fetchPortal<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const portalApi = {
  getClaims: (params?: { limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.limit != null) q.set('limit', String(params.limit));
    if (params?.offset != null) q.set('offset', String(params.offset));
    const suffix = q.toString() ? `?${q}` : '';
    return fetchPortal<{ claims: unknown[]; total: number }>(`/claims${suffix}`);
  },

  getClaim: (claimId: string) =>
    fetchPortal<Record<string, unknown>>(`/claims/${claimId}`),

  getClaimHistory: (claimId: string) =>
    fetchPortal<{ history: unknown[] }>(`/claims/${claimId}/history`),

  getDocuments: (claimId: string, params?: { document_type?: string }) => {
    const q = new URLSearchParams();
    if (params?.document_type) q.set('document_type', params.document_type);
    const suffix = q.toString() ? `?${q}` : '';
    return fetchPortal<{ documents: unknown[]; total: number }>(
      `/claims/${claimId}/documents${suffix}`
    );
  },

  uploadDocument: async (
    claimId: string,
    file: File,
    documentType?: string
  ): Promise<{ document_id: number; document: unknown }> => {
    const form = new FormData();
    form.append('file', file);
    const url = documentType
      ? `/claims/${claimId}/documents?document_type=${encodeURIComponent(documentType)}`
      : `/claims/${claimId}/documents`;
    const res = await fetch(`${BASE}${url}`, {
      method: 'POST',
      headers: getPortalHeaders(),
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(parseApiError(res.status, text));
    }
    return res.json();
  },

  getDocumentRequests: (claimId: string) =>
    fetchPortal<{ document_requests: unknown[]; total: number }>(
      `/claims/${claimId}/document-requests`
    ),

  getRepairStatus: (claimId: string) =>
    fetchPortal<{
      latest: unknown;
      history: unknown[];
      cycle_time_days: number | null;
    }>(`/claims/${claimId}/repair-status`),

  getPayments: (claimId: string) =>
    fetchPortal<{ payments: unknown[]; total: number }>(
      `/claims/${claimId}/payments`
    ),

  recordFollowUpResponse: (
    claimId: string,
    messageId: number,
    responseContent: string
  ) =>
    postPortalJSON<{ success: boolean }>(
      `/claims/${claimId}/follow-up/record-response`,
      { message_id: messageId, response_content: responseContent }
    ),

  fileDispute: (
    claimId: string,
    body: {
      dispute_type: string;
      dispute_description: string;
      policyholder_evidence?: string | null;
    }
  ) =>
    postPortalJSON<Record<string, unknown>>(
      `/claims/${claimId}/dispute`,
      body
    ),
};
