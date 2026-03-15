/**
 * React Query hooks for the Claims System API.
 */

import { useQuery } from '@tanstack/react-query';
import {
  getClaimsStats,
  getClaims,
  getClaim,
  getClaimHistory,
  getClaimWorkflows,
  getDocs,
  getDoc,
  getSkills,
  getSkill,
  getSystemConfig,
  getSystemHealth,
  getAgentsCatalog,
  getPolicies,
  getClaimTasks,
  getAllTasks,
  getTaskStats,
} from './client';
import type { GetClaimsParams } from './client';

export const queryKeys = {
  claimsStats: ['claims', 'stats'] as const,
  claims: (params: GetClaimsParams) => ['claims', 'list', params] as const,
  claim: (id: string) => ['claims', id] as const,
  claimHistory: (id: string) => ['claims', id, 'history'] as const,
  claimWorkflows: (id: string) => ['claims', id, 'workflows'] as const,
  docs: ['docs'] as const,
  doc: (slug: string) => ['docs', slug] as const,
  skills: ['skills'] as const,
  skill: (name: string) => ['skills', name] as const,
  systemConfig: ['system', 'config'] as const,
  systemHealth: ['system', 'health'] as const,
  agentsCatalog: ['system', 'agents'] as const,
  policies: ['system', 'policies'] as const,
  claimTasks: (id: string) => ['claims', id, 'tasks'] as const,
  allTasks: (params?: Record<string, unknown>) => ['tasks', 'list', params ?? {}] as const,
  taskStats: ['tasks', 'stats'] as const,
};

export function useClaimsStats() {
  return useQuery({
    queryKey: queryKeys.claimsStats,
    queryFn: getClaimsStats,
  });
}

export function useClaims(params: GetClaimsParams = {}) {
  return useQuery({
    queryKey: queryKeys.claims(params),
    queryFn: () => getClaims(params),
  });
}

export function useClaim(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.claim(id ?? ''),
    queryFn: () => getClaim(id!),
    enabled: !!id,
  });
}

export function useClaimHistory(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.claimHistory(id ?? ''),
    queryFn: () => getClaimHistory(id!),
    enabled: !!id,
  });
}

export function useClaimWorkflows(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.claimWorkflows(id ?? ''),
    queryFn: () => getClaimWorkflows(id!),
    enabled: !!id,
  });
}

export function useDocs() {
  return useQuery({
    queryKey: queryKeys.docs,
    queryFn: getDocs,
  });
}

export function useDoc(slug: string | undefined) {
  return useQuery({
    queryKey: queryKeys.doc(slug ?? ''),
    queryFn: () => getDoc(slug!),
    enabled: !!slug,
  });
}

export function useSkills() {
  return useQuery({
    queryKey: queryKeys.skills,
    queryFn: getSkills,
  });
}

export function useSkill(name: string | undefined) {
  return useQuery({
    queryKey: queryKeys.skill(name ?? ''),
    queryFn: () => getSkill(name!),
    enabled: !!name,
  });
}

export function useSystemConfig() {
  return useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: getSystemConfig,
  });
}

export function useSystemHealth() {
  return useQuery({
    queryKey: queryKeys.systemHealth,
    queryFn: getSystemHealth,
  });
}

export function useAgentsCatalog() {
  return useQuery({
    queryKey: queryKeys.agentsCatalog,
    queryFn: getAgentsCatalog,
  });
}

export function usePolicies() {
  return useQuery({
    queryKey: queryKeys.policies,
    queryFn: getPolicies,
  });
}

/** For fetching tasks separately from claim; TaskPanel uses claim.tasks from useClaim. */
export function useClaimTasks(claimId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.claimTasks(claimId ?? ''),
    queryFn: () => getClaimTasks(claimId!),
    enabled: !!claimId,
  });
}

/** For future All Tasks dashboard; not yet used in UI. */
export function useAllTasks(params: {
  status?: string;
  task_type?: string;
  assigned_to?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return useQuery({
    queryKey: queryKeys.allTasks(params),
    queryFn: () => getAllTasks(params),
  });
}

/** For future All Tasks dashboard; not yet used in UI. */
export function useTaskStats() {
  return useQuery({
    queryKey: queryKeys.taskStats,
    queryFn: getTaskStats,
  });
}
