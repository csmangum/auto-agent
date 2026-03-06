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
} from './types';

const BASE = '/api';

async function fetchJSON<T>(url: string, retries = 1): Promise<T> {
  const res = await fetch(`${BASE}${url}`);
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
