import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {
  useClaimsStats,
  useClaims,
  useClaim,
  useClaimHistory,
  useClaimWorkflows,
  useClaimReserveHistory,
  useClaimReserveAdequacy,
  usePatchClaimReserve,
  useClaimRepairStatus,
  usePostClaimRepairStatus,
  useClaimDocuments,
  useUploadDocument,
  useUpdateDocument,
  useDocumentRequests,
  useCreateDocumentRequest,
  useAddClaimNote,
  useClaimPayments,
  useCreatePayment,
  useIssuePayment,
  useClearPayment,
  useVoidPayment,
  useOverdueTasks,
  useComplianceTemplates,
  useCreatePartyRelationship,
  useDeletePartyRelationship,
  useFraudReportingCompliance,
  useCurrentUser,
  useNoteTemplates,
  useActiveNoteTemplates,
  useCreateNoteTemplate,
  useUpdateNoteTemplate,
  useDeleteNoteTemplate,
  useCostBreakdown,
  useReviewQueue,
  useAssignClaim,
  useAllTasks,
  useTaskStats,
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

  describe('useClaimReserveHistory', () => {
    it('fetches reserve history with default limit', async () => {
      const mockData = { claim_id: 'c1', history: [], total: 0 };
      vi.mocked(client.getClaimReserveHistory).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useClaimReserveHistory('c1'), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getClaimReserveHistory).toHaveBeenCalledWith('c1', 50);
    });
  });

  describe('useClaimReserveAdequacy', () => {
    it('fetches reserve adequacy', async () => {
      const mockData = { adequate: true, reserve_amount: 5000 };
      vi.mocked(client.getClaimReserveAdequacy).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useClaimReserveAdequacy('c1'), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(client.getClaimReserveAdequacy).toHaveBeenCalledWith('c1');
    });
  });

  describe('usePatchClaimReserve', () => {
    it('calls patchClaimReserve on mutate', async () => {
      const mockResponse = { claim_id: 'c1', reserve_amount: 10000 };
      vi.mocked(client.patchClaimReserve).mockResolvedValue(mockResponse);
      const { result } = renderHook(() => usePatchClaimReserve('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ reserve_amount: 10000, reason: 'adjustment' });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.patchClaimReserve).toHaveBeenCalledWith('c1', {
        reserve_amount: 10000,
        reason: 'adjustment',
      });
    });
  });

  describe('useClaimRepairStatus', () => {
    it('fetches repair status', async () => {
      const mockData = { claim_id: 'c1', latest: null, history: [] };
      vi.mocked(client.getClaimRepairStatus).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useClaimRepairStatus('c1'), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(client.getClaimRepairStatus).toHaveBeenCalledWith('c1');
    });
  });

  describe('usePostClaimRepairStatus', () => {
    it('posts repair status on mutate', async () => {
      vi.mocked(client.postClaimRepairStatus).mockResolvedValue({
        ok: true,
        repair_status_id: 1,
      });
      const { result } = renderHook(() => usePostClaimRepairStatus('c1'), {
        wrapper: createWrapper(),
      });
      const payload = { status: 'in_progress', shop_id: 'SHOP1' };
      act(() => {
        result.current.mutate(payload);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.postClaimRepairStatus).toHaveBeenCalledWith('c1', payload);
    });
  });

  describe('useClaimDocuments', () => {
    it('fetches documents for claim', async () => {
      const mockData = { documents: [], total: 0 };
      vi.mocked(client.getClaimDocuments).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useClaimDocuments('c1'), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(client.getClaimDocuments).toHaveBeenCalledWith('c1', { group_by: undefined });
    });
  });

  describe('useUploadDocument', () => {
    it('uploads document on mutate', async () => {
      const mockFile = new File(['data'], 'test.pdf', { type: 'application/pdf' });
      vi.mocked(client.uploadClaimDocument).mockResolvedValue({
        claim_id: 'c1',
        document_id: 1,
        document: {},
      } as never);
      const { result } = renderHook(() => useUploadDocument('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ file: mockFile, documentType: 'photo' });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.uploadClaimDocument).toHaveBeenCalledWith('c1', mockFile, {
        document_type: 'photo',
        received_from: undefined,
      });
    });
  });

  describe('useUpdateDocument', () => {
    it('updates document on mutate', async () => {
      vi.mocked(client.updateClaimDocument).mockResolvedValue({
        claim_id: 'c1',
        document_id: 5,
        document: {},
      } as never);
      const { result } = renderHook(() => useUpdateDocument('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ docId: 5, body: { review_status: 'approved' } });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.updateClaimDocument).toHaveBeenCalledWith('c1', 5, {
        review_status: 'approved',
      });
    });
  });

  describe('useDocumentRequests', () => {
    it('fetches document requests', async () => {
      const mockData = { requests: [], total: 0 };
      vi.mocked(client.getDocumentRequests).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useDocumentRequests('c1'), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getDocumentRequests).toHaveBeenCalledWith('c1');
    });
  });

  describe('useCreateDocumentRequest', () => {
    it('creates document request on mutate', async () => {
      vi.mocked(client.createDocumentRequest).mockResolvedValue({
        claim_id: 'c1',
        request_id: 1,
        request: {},
      } as never);
      const { result } = renderHook(() => useCreateDocumentRequest('c1'), {
        wrapper: createWrapper(),
      });
      const body = { document_type: 'photo' };
      act(() => {
        result.current.mutate(body);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.createDocumentRequest).toHaveBeenCalledWith('c1', body);
    });
  });

  describe('useAddClaimNote', () => {
    it('adds note on mutate', async () => {
      vi.mocked(client.addClaimNote).mockResolvedValue({
        claim_id: 'c1',
        actor_id: 'user1',
      } as never);
      const { result } = renderHook(() => useAddClaimNote('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ note: 'Test note', actorId: 'user1' });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.addClaimNote).toHaveBeenCalledWith('c1', 'Test note', 'user1');
    });
  });

  describe('useClaimPayments', () => {
    it('fetches payments for claim', async () => {
      const mockData = { payments: [], total: 0 };
      vi.mocked(client.getClaimPayments).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useClaimPayments('c1'), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(client.getClaimPayments).toHaveBeenCalledWith('c1');
    });
  });

  describe('useCreatePayment', () => {
    it('creates payment on mutate', async () => {
      const payload = {
        claim_id: 'c1',
        amount: 500,
        payee: 'John',
        payee_type: 'claimant',
        payment_method: 'check',
      };
      vi.mocked(client.createPayment).mockResolvedValue({ id: 1, ...payload } as never);
      const { result } = renderHook(() => useCreatePayment('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate(payload);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.createPayment).toHaveBeenCalledWith('c1', payload);
    });
  });

  describe('useIssuePayment', () => {
    it('issues payment on mutate', async () => {
      vi.mocked(client.issuePayment).mockResolvedValue({ id: 10 } as never);
      const { result } = renderHook(() => useIssuePayment('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ paymentId: 10 });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.issuePayment).toHaveBeenCalledWith('c1', 10, undefined);
    });
  });

  describe('useClearPayment', () => {
    it('clears payment on mutate', async () => {
      vi.mocked(client.clearPayment).mockResolvedValue({ id: 10 } as never);
      const { result } = renderHook(() => useClearPayment('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate(10);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.clearPayment).toHaveBeenCalledWith('c1', 10);
    });
  });

  describe('useVoidPayment', () => {
    it('voids payment on mutate', async () => {
      vi.mocked(client.voidPayment).mockResolvedValue({ id: 10 } as never);
      const { result } = renderHook(() => useVoidPayment('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ paymentId: 10, reason: 'duplicate' });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.voidPayment).toHaveBeenCalledWith('c1', 10, { reason: 'duplicate' });
    });
  });

  describe('useOverdueTasks', () => {
    it('fetches overdue tasks', async () => {
      const mockData = { tasks: [], total: 0 };
      vi.mocked(client.getOverdueTasks).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useOverdueTasks(), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(client.getOverdueTasks).toHaveBeenCalledWith(100);
    });
  });

  describe('useComplianceTemplates', () => {
    it('fetches compliance templates', async () => {
      const mockData = { templates: [] };
      vi.mocked(client.getComplianceTemplates).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useComplianceTemplates('CA'), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getComplianceTemplates).toHaveBeenCalledWith('CA');
    });
  });

  describe('useCreatePartyRelationship', () => {
    it('creates party relationship on mutate', async () => {
      const body = { from_party_id: 1, to_party_id: 2, relationship_type: 'spouse' };
      vi.mocked(client.createPartyRelationship).mockResolvedValue({
        id: 1,
        claim_id: 'c1',
        ...body,
      } as never);
      const { result } = renderHook(() => useCreatePartyRelationship('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate(body);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.createPartyRelationship).toHaveBeenCalledWith('c1', body);
    });
  });

  describe('useDeletePartyRelationship', () => {
    it('deletes party relationship on mutate', async () => {
      vi.mocked(client.deletePartyRelationship).mockResolvedValue(undefined as never);
      const { result } = renderHook(() => useDeletePartyRelationship('c1'), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate(7);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.deletePartyRelationship).toHaveBeenCalledWith('c1', 7);
    });
  });

  describe('useFraudReportingCompliance', () => {
    it('fetches fraud reporting compliance', async () => {
      const mockData = { claims: [], total: 0 };
      vi.mocked(client.getFraudReportingCompliance).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useFraudReportingCompliance({ state: 'CA' }), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getFraudReportingCompliance).toHaveBeenCalledWith({ state: 'CA' });
    });
  });

  describe('useCurrentUser', () => {
    it('fetches current user', async () => {
      const mockUser = { identity: 'admin@test.com', role: 'admin' };
      vi.mocked(client.getCurrentUser).mockResolvedValue(mockUser);
      const { result } = renderHook(() => useCurrentUser(), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockUser);
    });
  });

  describe('useNoteTemplates', () => {
    it('fetches and selects templates array', async () => {
      const templates = [{ id: 1, label: 'T1', body: 'B1', is_active: true }];
      vi.mocked(client.getNoteTemplates).mockResolvedValue({ templates } as never);
      const { result } = renderHook(() => useNoteTemplates(), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(templates);
    });
  });

  describe('useActiveNoteTemplates', () => {
    it('fetches active templates only', async () => {
      const templates = [{ id: 2, label: 'Active', body: 'B', is_active: true }];
      vi.mocked(client.getNoteTemplates).mockResolvedValue({ templates } as never);
      const { result } = renderHook(() => useActiveNoteTemplates(), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(templates);
      expect(client.getNoteTemplates).toHaveBeenCalledWith({ activeOnly: true });
    });
  });

  describe('useCreateNoteTemplate', () => {
    it('creates note template on mutate', async () => {
      const payload = { label: 'New', body: 'Template body' };
      vi.mocked(client.createNoteTemplate).mockResolvedValue({
        id: 1,
        ...payload,
        is_active: true,
      } as never);
      const { result } = renderHook(() => useCreateNoteTemplate(), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate(payload);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.createNoteTemplate).toHaveBeenCalledWith(payload);
    });
  });

  describe('useUpdateNoteTemplate', () => {
    it('updates note template on mutate', async () => {
      vi.mocked(client.updateNoteTemplate).mockResolvedValue({
        id: 1,
        label: 'Updated',
        body: 'B',
        is_active: true,
      } as never);
      const { result } = renderHook(() => useUpdateNoteTemplate(), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ id: 1, label: 'Updated' });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.updateNoteTemplate).toHaveBeenCalledWith(1, { label: 'Updated' });
    });
  });

  describe('useDeleteNoteTemplate', () => {
    it('deletes note template on mutate', async () => {
      vi.mocked(client.deleteNoteTemplate).mockResolvedValue(undefined as never);
      const { result } = renderHook(() => useDeleteNoteTemplate(), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate(5);
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.deleteNoteTemplate).toHaveBeenCalledWith(5);
    });
  });

  describe('useCostBreakdown', () => {
    it('fetches cost breakdown', async () => {
      const mockData = { total_cost_usd: 100, total_tokens: 5000 };
      vi.mocked(client.getCostBreakdown).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useCostBreakdown(), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
    });
  });

  describe('useReviewQueue', () => {
    it('fetches review queue', async () => {
      const mockData = { claims: [], total: 0 };
      vi.mocked(client.getReviewQueue).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useReviewQueue({ priority: 'high' }), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.getReviewQueue).toHaveBeenCalledWith({ priority: 'high' });
    });
  });

  describe('useAssignClaim', () => {
    it('assigns claim on mutate', async () => {
      vi.mocked(client.assignClaim).mockResolvedValue({
        claim_id: 'c1',
        assignee: 'adj1',
      });
      const { result } = renderHook(() => useAssignClaim(), {
        wrapper: createWrapper(),
      });
      act(() => {
        result.current.mutate({ claimId: 'c1', assignee: 'adj1' });
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(client.assignClaim).toHaveBeenCalledWith('c1', 'adj1');
    });
  });

  describe('useAllTasks', () => {
    it('fetches all tasks with params', async () => {
      const mockData = { tasks: [], total: 0 };
      vi.mocked(client.getAllTasks).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useAllTasks({ status: 'open' }), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(client.getAllTasks).toHaveBeenCalledWith({ status: 'open' });
    });
  });

  describe('useTaskStats', () => {
    it('fetches task stats', async () => {
      const mockData = { total: 50, by_status: {}, by_type: {} };
      vi.mocked(client.getTaskStats).mockResolvedValue(mockData as never);
      const { result } = renderHook(() => useTaskStats(), {
        wrapper: createWrapper(),
      });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
    });
  });
});
