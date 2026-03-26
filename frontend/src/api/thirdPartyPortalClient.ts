/**
 * Third-party self-service portal (counterparty magic link).
 * Sends X-Third-Party-Access-Token; claim id is in the URL path.
 */

import { API_VERSION } from './config';
import { parseApiError } from './apiUtils';

const BASE = `${API_VERSION}/third-party-portal`;

export interface ThirdPartyPortalSession {
  token: string;
  claimId: string;
}

const SESSION_KEY = 'third_party_portal_session';

export function getThirdPartyPortalSession(): ThirdPartyPortalSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ThirdPartyPortalSession;
  } catch {
    return null;
  }
}

export function setThirdPartyPortalSession(session: ThirdPartyPortalSession): void {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearThirdPartyPortalSession(): void {
  sessionStorage.removeItem(SESSION_KEY);
}

function getThirdPartyPortalHeaders(): HeadersInit {
  const session = getThirdPartyPortalSession();
  const headers: Record<string, string> = {};
  if (session?.token) {
    headers['X-Third-Party-Access-Token'] = session.token;
  }
  return headers;
}

async function fetchThirdPartyPortal<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers: { ...getThirdPartyPortalHeaders(), ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseApiError(res.status, text));
  }
  return res.json() as Promise<T>;
}

async function postThirdPartyPortalJSON<T>(url: string, body: unknown): Promise<T> {
  return fetchThirdPartyPortal<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const thirdPartyPortalApi = {
  getClaim: (claimId: string) =>
    fetchThirdPartyPortal<Record<string, unknown>>(`/claims/${claimId}`),

  getClaimHistory: (claimId: string) =>
    fetchThirdPartyPortal<{ claim_id: string; history: unknown[]; history_total: number }>(
      `/claims/${claimId}/history`
    ),

  recordFollowUpResponse: (
    claimId: string,
    messageId: number,
    responseContent: string
  ) =>
    postThirdPartyPortalJSON<{ success: boolean; message?: string }>(
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
    postThirdPartyPortalJSON<Record<string, unknown>>(
      `/claims/${claimId}/dispute`,
      body
    ),

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
      headers: getThirdPartyPortalHeaders(),
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(parseApiError(res.status, text));
    }
    return res.json();
  },
};
