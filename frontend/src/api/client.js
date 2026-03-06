/**
 * API client for the Claims System backend.
 * All functions return parsed JSON responses.
 */

const BASE = '/api';

async function fetchJSON(url) {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

// Claims
export const getClaimsStats = () => fetchJSON('/claims/stats');
export const getClaims = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.claim_type) qs.set('claim_type', params.claim_type);
  if (params.limit) qs.set('limit', params.limit);
  if (params.offset) qs.set('offset', params.offset);
  const q = qs.toString();
  return fetchJSON(`/claims${q ? '?' + q : ''}`);
};
export const getClaim = (id) => fetchJSON(`/claims/${id}`);
export const getClaimHistory = (id) => fetchJSON(`/claims/${id}/history`);
export const getClaimWorkflows = (id) => fetchJSON(`/claims/${id}/workflows`);

// Metrics
export const getMetrics = () => fetchJSON('/metrics');
export const getClaimMetrics = (id) => fetchJSON(`/metrics/${id}`);

// Documentation
export const getDocs = () => fetchJSON('/docs');
export const getDoc = (slug) => fetchJSON(`/docs/${slug}`);

// Skills
export const getSkills = () => fetchJSON('/skills');
export const getSkill = (name) => fetchJSON(`/skills/${name}`);

// System
export const getSystemConfig = () => fetchJSON('/system/config');
export const getSystemHealth = () => fetchJSON('/system/health');
export const getAgentsCatalog = () => fetchJSON('/system/agents');
