/**
 * API client for the Claims System backend.
 * All functions return parsed JSON responses.
 * Retries once on 5xx (transient) errors.
 */

import type {
  ClaimsStats,
  ClaimsListResponse,
  Claim,
  ClaimHistoryResponse,
  ClaimWorkflowsResponse,
  DocsListResponse,
  DocContentResponse,
  SkillsListResponse,
  SkillDetailResponse,
  AgentsCatalogResponse,
  AuditEvent,
  WorkflowRun,
} from './types';

const BASE = '/api';
const STORAGE_KEY = 'claims_api_token';

let _authToken: string | null =
  (typeof window !== 'undefined' && localStorage.getItem(STORAGE_KEY)) || null;

export function setAuthToken(token: string): void {
  _authToken = token;
}

export function clearAuthToken(): void {
  _authToken = null;
}

function getAuthHeaders(): HeadersInit {
  const headers: Record<string, string> = {};
  if (_authToken) {
    headers['Authorization'] = `Bearer ${_authToken}`;
  }
  return headers;
}

async function fetchJSON<T>(url: string, retries = 1): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    const msg = `API error ${res.status}: ${text.slice(0, 200)}`;
    if (res.status >= 500 && retries > 0) {
      await new Promise((r) => setTimeout(r, 500));
      return fetchJSON<T>(url, retries - 1);
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const getClaimsStats = (): Promise<ClaimsStats> =>
  fetchJSON<ClaimsStats>('/claims/stats');

export interface GetClaimsParams {
  status?: string;
  claim_type?: string;
  limit?: number;
  offset?: number;
}

export const getClaims = (params: GetClaimsParams = {}): Promise<ClaimsListResponse> => {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.claim_type) qs.set('claim_type', params.claim_type);
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.offset) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return fetchJSON<ClaimsListResponse>(`/claims${q ? '?' + q : ''}`);
};

export const getClaim = (id: string): Promise<Claim> =>
  fetchJSON<Claim>(`/claims/${id}`);

export const getClaimHistory = (id: string): Promise<ClaimHistoryResponse> =>
  fetchJSON<ClaimHistoryResponse>(`/claims/${id}/history`);

export const getClaimWorkflows = (id: string): Promise<ClaimWorkflowsResponse> =>
  fetchJSON<ClaimWorkflowsResponse>(`/claims/${id}/workflows`);

export const getMetrics = (): Promise<unknown> => fetchJSON('/metrics');
export const getClaimMetrics = (id: string): Promise<unknown> =>
  fetchJSON(`/metrics/${id}`);

export const getDocs = (): Promise<DocsListResponse> =>
  fetchJSON<DocsListResponse>('/docs');

export const getDoc = (slug: string): Promise<DocContentResponse> =>
  fetchJSON<DocContentResponse>(`/docs/${slug}`);

export const getSkills = (): Promise<SkillsListResponse> =>
  fetchJSON<SkillsListResponse>('/skills');

export const getSkill = (name: string): Promise<SkillDetailResponse> =>
  fetchJSON<SkillDetailResponse>(`/skills/${name}`);

export const getSystemConfig = (): Promise<unknown> =>
  fetchJSON('/system/config');

export const getSystemHealth = (): Promise<unknown> =>
  fetchJSON('/system/health');

export const getAgentsCatalog = (): Promise<AgentsCatalogResponse> =>
  fetchJSON<AgentsCatalogResponse>('/system/agents');

// ---------------------------------------------------------------------------
// Claim submission and realtime stream
// ---------------------------------------------------------------------------

export interface ProcessClaimPayload {
  policy_number: string;
  vin: string;
  vehicle_year: number;
  vehicle_make: string;
  vehicle_model: string;
  incident_date: string;
  incident_description: string;
  damage_description: string;
  estimated_damage?: number;
  attachments?: Array<{ url: string; type: string; description?: string }>;
}

export interface ProcessClaimAsyncResponse {
  claim_id: string;
}

export interface ClaimStreamUpdate {
  claim?: Claim;
  history?: AuditEvent[];
  workflows?: WorkflowRun[];
  done?: boolean;
  status?: string;
  error?: string;
}

export async function processClaimAsync(
  payload: ProcessClaimPayload,
  files?: File[]
): Promise<ProcessClaimAsyncResponse> {
  const formData = new FormData();
  formData.append('claim', JSON.stringify(payload));
  if (files) {
    for (const f of files) {
      formData.append('files', f);
    }
  }
  const res = await fetch(`${BASE}/claims/process/async`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json() as Promise<ProcessClaimAsyncResponse>;
}

export function streamClaimUpdates(
  claimId: string,
  onUpdate: (data: ClaimStreamUpdate) => void,
  onError?: (err: Error) => void
): () => void {
  const controller = new AbortController();
  const abort = () => controller.abort();

  fetch(`${BASE}/claims/${claimId}/stream`, {
    signal: controller.signal,
    credentials: 'include',
    headers: getAuthHeaders(),
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Stream error ${res.status}`);
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() ?? '';
        for (const block of lines) {
          const match = block.match(/^data: (.+)$/m);
          if (match) {
            try {
              const data = JSON.parse(match[1]) as ClaimStreamUpdate;
              onUpdate(data);
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    });

  return abort;
}
