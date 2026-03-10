import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {
  useClaimsStats,
  useClaims,
  useClaim,
  useClaimHistory,
  useClaimWorkflows,
  useDocs,
  useDoc,
  useSkills,
  useSkill,
  useSystemConfig,
  useSystemHealth,
  useAgentsCatalog,
  queryKeys,
} from './queries';
import * as client from './client';

vi.mock('./client');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

describe('queries', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('queryKeys', () => {
    it('exports correct key shapes', () => {
      expect(queryKeys.claimsStats).toEqual(['claims', 'stats']);
      expect(queryKeys.claims({ limit: 10 })).toEqual(['claims', 'list', { limit: 10 }]);
      expect(queryKeys.claim('c1')).toEqual(['claims', 'c1']);
      expect(queryKeys.claimHistory('c1')).toEqual(['claims', 'c1', 'history']);
      expect(queryKeys.claimWorkflows('c1')).toEqual(['claims', 'c1', 'workflows']);
      expect(queryKeys.docs).toEqual(['docs']);
      expect(queryKeys.doc('slug')).toEqual(['docs', 'slug']);
      expect(queryKeys.skills).toEqual(['skills']);
      expect(queryKeys.skill('name')).toEqual(['skills', 'name']);
      expect(queryKeys.systemConfig).toEqual(['system', 'config']);
      expect(queryKeys.systemHealth).toEqual(['system', 'health']);
      expect(queryKeys.agentsCatalog).toEqual(['system', 'agents']);
    });
  });

  describe('useClaimsStats', () => {
    it('fetches and returns stats', async () => {
      const mockStats = {
        total_claims: 42,
        by_status: {},
        by_type: {},
        total_audit_events: 10,
        total_workflow_runs: 5,
      };
      vi.mocked(client.getClaimsStats).mockResolvedValue(mockStats);

      const { result } = renderHook(() => useClaimsStats(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockStats);
      expect(client.getClaimsStats).toHaveBeenCalled();
    });
  });

  describe('useClaims', () => {
    it('fetches claims with params', async () => {
      const mockData = { claims: [], total: 0, limit: 25, offset: 0 };
      vi.mocked(client.getClaims).mockResolvedValue(mockData);

      const { result } = renderHook(() => useClaims({ limit: 10, status: 'open' }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(client.getClaims).toHaveBeenCalledWith({ limit: 10, status: 'open' });
    });
  });

  describe('useClaim', () => {
    it('fetches claim when id provided', async () => {
      const mockClaim = {
        id: 'c1',
        policy_number: 'p1',
        vin: 'v1',
        status: 'open',
      };
      vi.mocked(client.getClaim).mockResolvedValue(mockClaim as never);

      const { result } = renderHook(() => useClaim('c1'), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockClaim);
      expect(client.getClaim).toHaveBeenCalledWith('c1');
    });

    it('does not fetch when id is undefined', () => {
      renderHook(() => useClaim(undefined), {
        wrapper: createWrapper(),
      });
      expect(client.getClaim).not.toHaveBeenCalled();
    });
  });

  describe('useClaimHistory', () => {
    it('fetches history when id provided', async () => {
      const mockHistory = { claim_id: 'c1', history: [], total: 0, limit: null, offset: 0 };
      vi.mocked(client.getClaimHistory).mockResolvedValue(mockHistory as never);

      const { result } = renderHook(() => useClaimHistory('c1'), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getClaimHistory).toHaveBeenCalledWith('c1');
    });
  });

  describe('useClaimWorkflows', () => {
    it('fetches workflows when id provided', async () => {
      const mockWorkflows = { claim_id: 'c1', workflows: [] };
      vi.mocked(client.getClaimWorkflows).mockResolvedValue(mockWorkflows as never);

      const { result } = renderHook(() => useClaimWorkflows('c1'), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getClaimWorkflows).toHaveBeenCalledWith('c1');
    });
  });

  describe('useDocs', () => {
    it('fetches docs list', async () => {
      const mockDocs = { pages: [] };
      vi.mocked(client.getDocs).mockResolvedValue(mockDocs as never);

      const { result } = renderHook(() => useDocs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getDocs).toHaveBeenCalled();
    });
  });

  describe('useDoc', () => {
    it('fetches doc when slug provided', async () => {
      const mockDoc = { slug: 'intro', title: 'Intro', content: 'Hello' };
      vi.mocked(client.getDoc).mockResolvedValue(mockDoc as never);

      const { result } = renderHook(() => useDoc('intro'), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getDoc).toHaveBeenCalledWith('intro');
    });
  });

  describe('useSkills', () => {
    it('fetches skills list', async () => {
      const mockSkills = { groups: {} };
      vi.mocked(client.getSkills).mockResolvedValue(mockSkills as never);

      const { result } = renderHook(() => useSkills(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getSkills).toHaveBeenCalled();
    });
  });

  describe('useSkill', () => {
    it('fetches skill when name provided', async () => {
      const mockSkill = { name: 'adjuster', role: 'Adjuster', content: '' };
      vi.mocked(client.getSkill).mockResolvedValue(mockSkill as never);

      const { result } = renderHook(() => useSkill('adjuster'), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getSkill).toHaveBeenCalledWith('adjuster');
    });
  });

  describe('useSystemConfig', () => {
    it('fetches system config', async () => {
      const mockConfig = {};
      vi.mocked(client.getSystemConfig).mockResolvedValue(mockConfig as never);

      const { result } = renderHook(() => useSystemConfig(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getSystemConfig).toHaveBeenCalled();
    });
  });

  describe('useSystemHealth', () => {
    it('fetches system health', async () => {
      const mockHealth = { status: 'ok', database: 'sqlite', total_claims: 0 };
      vi.mocked(client.getSystemHealth).mockResolvedValue(mockHealth as never);

      const { result } = renderHook(() => useSystemHealth(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getSystemHealth).toHaveBeenCalled();
    });
  });

  describe('useAgentsCatalog', () => {
    it('fetches agents catalog', async () => {
      const mockCatalog = { crews: [] };
      vi.mocked(client.getAgentsCatalog).mockResolvedValue(mockCatalog as never);

      const { result } = renderHook(() => useAgentsCatalog(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getAgentsCatalog).toHaveBeenCalled();
    });
  });
});
