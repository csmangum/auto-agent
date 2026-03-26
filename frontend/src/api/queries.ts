/**
 * React Query hooks for the Claims System API.
 */

import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query';
import {
  getClaimsStats,
  getClaims,
  getClaim,
  getClaimHistory,
  getClaimReserveHistory,
  getClaimReserveAdequacy,
  getClaimWorkflows,
  getClaimRepairStatus,
  patchClaimReserve,
  postClaimRepairStatus,
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
  getCostBreakdown,
  getReviewQueue,
  assignClaim,
  getClaimPayments,
  createPayment,
  issuePayment,
  clearPayment,
  voidPayment,
  getClaimDocuments,
  uploadClaimDocument,
  getDocumentRequests,
  createDocumentRequest,
  addClaimNote,
  getOverdueTasks,
  getComplianceTemplates,
  updateClaimDocument,
  createPartyRelationship,
  deletePartyRelationship,
  getFraudReportingCompliance,
  getCurrentUser,
  getNoteTemplates,
  createNoteTemplate,
  updateNoteTemplate,
  deleteNoteTemplate,
} from './client';
import type {
  CostBreakdown,
  CurrentUser,
  GetClaimsParams,
  GetReviewQueueParams,
  CreatePaymentPayload,
  PatchClaimReserveBody,
  PostClaimRepairStatusPayload,
  UpdateDocumentBody,
  CreatePartyRelationshipPayload,
  GetFraudReportingComplianceParams,
  NoteTemplateCreatePayload,
  NoteTemplateUpdatePayload,
} from './client';

export const queryKeys = {
  claimsStats: ['claims', 'stats'] as const,
  claims: (params: GetClaimsParams) => ['claims', 'list', params] as const,
  claim: (id: string) => ['claims', id] as const,
  claimHistory: (id: string) => ['claims', id, 'history'] as const,
  claimReserveHistory: (id: string) => ['claims', id, 'reserve-history'] as const,
  claimReserveAdequacy: (id: string) => ['claims', id, 'reserve-adequacy'] as const,
  claimWorkflows: (id: string) => ['claims', id, 'workflows'] as const,
  claimRepairStatus: (id: string) => ['claims', id, 'repair-status'] as const,
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
  costBreakdown: ['metrics', 'cost'] as const,
  reviewQueue: (params: GetReviewQueueParams) => ['claims', 'review-queue', params] as const,
  claimPayments: (id: string) => ['claims', id, 'payments'] as const,
  claimDocuments: (id: string, opts?: { groupBy?: 'storage_key' }) =>
    opts?.groupBy
      ? (['claims', id, 'documents', { groupBy: opts.groupBy }] as const)
      : (['claims', id, 'documents'] as const),
  documentRequests: (id: string) => ['claims', id, 'document-requests'] as const,
  overdueTasks: (limit: number) => ['tasks', 'overdue', limit] as const,
  complianceTemplates: (state?: string) => ['diary', 'templates', state ?? ''] as const,
  fraudReportingCompliance: (params: GetFraudReportingComplianceParams) =>
    ['compliance', 'fraud-reporting', params] as const,
  currentUser: ['auth', 'me'] as const,
  noteTemplates: ['note-templates'] as const,
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

export function useClaimRepairStatus(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.claimRepairStatus(id ?? ''),
    queryFn: () => getClaimRepairStatus(id!),
    enabled: !!id,
  });
}

export function usePostClaimRepairStatus(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PostClaimRepairStatusPayload) =>
      postClaimRepairStatus(claimId!, payload),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claimRepairStatus(claimId) });
      }
    },
  });
}

export function useClaimReserveHistory(id: string | undefined, limit = 50) {
  return useQuery<Awaited<ReturnType<typeof getClaimReserveHistory>>, Error>({
    queryKey: [...queryKeys.claimReserveHistory(id ?? ''), limit],
    queryFn: () => getClaimReserveHistory(id!, limit),
    enabled: !!id,
  });
}

export function useClaimReserveAdequacy(id: string | undefined) {
  return useQuery<Awaited<ReturnType<typeof getClaimReserveAdequacy>>, Error>({
    queryKey: queryKeys.claimReserveAdequacy(id ?? ''),
    queryFn: () => getClaimReserveAdequacy(id!),
    enabled: !!id,
  });
}

export function usePatchClaimReserve(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof patchClaimReserve>>,
    Error,
    PatchClaimReserveBody
  >({
    mutationFn: (body: PatchClaimReserveBody) => patchClaimReserve(claimId!, body),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.claimReserveHistory(claimId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.claimReserveAdequacy(claimId) });
      }
    },
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
export function useTaskStats(options?: { workbench?: boolean }) {
  return useQuery({
    queryKey: queryKeys.taskStats,
    queryFn: getTaskStats,
    ...(options?.workbench ? WORKBENCH_QUERY_OPTS : {}),
  });
}

/** LLM cost breakdown: by crew, by claim type, daily spend. */
export function useCostBreakdown() {
  return useQuery<CostBreakdown>({
    queryKey: queryKeys.costBreakdown,
    queryFn: getCostBreakdown,
  });
}

// ---------------------------------------------------------------------------
// Review Queue
// ---------------------------------------------------------------------------

const WORKBENCH_QUERY_OPTS = {
  refetchInterval: 60_000,
  refetchOnWindowFocus: true,
} as const;

export function useReviewQueue(
  params: GetReviewQueueParams = {},
  options?: { workbench?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.reviewQueue(params),
    queryFn: () => getReviewQueue(params),
    ...(options?.workbench ? WORKBENCH_QUERY_OPTS : {}),
  });
}

export function useAssignClaim() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, assignee }: { claimId: string; assignee: string }) =>
      assignClaim(claimId, assignee),
    onSuccess: (_, { claimId }) => {
      queryClient.invalidateQueries({ queryKey: ['claims'] });
      queryClient.invalidateQueries({ queryKey: ['claims', 'review-queue'] });
      queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
    },
  });
}

// ---------------------------------------------------------------------------
// Payments
// ---------------------------------------------------------------------------

export function useClaimPayments(claimId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.claimPayments(claimId ?? ''),
    queryFn: () => getClaimPayments(claimId!),
    enabled: !!claimId,
  });
}

export function useCreatePayment(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreatePaymentPayload) => createPayment(claimId!, payload),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claimPayments(claimId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

export function useIssuePayment(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ paymentId, checkNumber }: { paymentId: number; checkNumber?: string }) =>
      issuePayment(claimId!, paymentId, checkNumber ? { check_number: checkNumber } : undefined),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claimPayments(claimId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

export function useClearPayment(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (paymentId: number) => clearPayment(claimId!, paymentId),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claimPayments(claimId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

export function useVoidPayment(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ paymentId, reason }: { paymentId: number; reason?: string }) =>
      voidPayment(claimId!, paymentId, reason ? { reason } : undefined),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claimPayments(claimId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export function useClaimDocuments(
  claimId: string | undefined,
  opts?: { groupBy?: 'storage_key' }
) {
  return useQuery({
    queryKey: queryKeys.claimDocuments(claimId ?? '', opts),
    queryFn: () =>
      getClaimDocuments(claimId!, {
        group_by: opts?.groupBy,
      }),
    enabled: !!claimId,
  });
}

export function useUploadDocument(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, documentType, receivedFrom }: {
      file: File;
      documentType?: string;
      receivedFrom?: string;
    }) => uploadClaimDocument(claimId!, file, {
      document_type: documentType,
      received_from: receivedFrom,
    }),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claimDocuments(claimId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

export function useUpdateDocument(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ docId, body }: { docId: number; body: UpdateDocumentBody }) =>
      updateClaimDocument(claimId!, docId, body),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claimDocuments(claimId) });
      }
    },
  });
}

export function useDocumentRequests(claimId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.documentRequests(claimId ?? ''),
    queryFn: () => getDocumentRequests(claimId!),
    enabled: !!claimId,
  });
}

export function useCreateDocumentRequest(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { document_type: string; requested_from?: string }) =>
      createDocumentRequest(claimId!, body),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.documentRequests(claimId) });
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

export function useAddClaimNote(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ note, actorId }: { note: string; actorId: string }) =>
      addClaimNote(claimId!, note, actorId),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Overdue Tasks & Compliance Templates
// ---------------------------------------------------------------------------

export function useOverdueTasks(limit = 100, options?: { workbench?: boolean }) {
  return useQuery({
    queryKey: queryKeys.overdueTasks(limit),
    queryFn: () => getOverdueTasks(limit),
    ...(options?.workbench ? WORKBENCH_QUERY_OPTS : {}),
  });
}

export function useComplianceTemplates(state?: string) {
  return useQuery({
    queryKey: queryKeys.complianceTemplates(state),
    queryFn: () => getComplianceTemplates(state),
  });
}

// ---------------------------------------------------------------------------
// Party Relationships
// ---------------------------------------------------------------------------

export function useCreatePartyRelationship(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreatePartyRelationshipPayload) =>
      createPartyRelationship(claimId!, body),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

export function useDeletePartyRelationship(claimId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (relationshipId: number) =>
      deletePartyRelationship(claimId!, relationshipId),
    onSuccess: () => {
      if (claimId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Fraud Compliance
// ---------------------------------------------------------------------------

export function useFraudReportingCompliance(params: GetFraudReportingComplianceParams = {}) {
  return useQuery({
    queryKey: queryKeys.fraudReportingCompliance(params),
    queryFn: () => getFraudReportingCompliance(params),
  });
}

// ---------------------------------------------------------------------------
// Current User
// ---------------------------------------------------------------------------

export function useCurrentUser() {
  return useQuery<CurrentUser>({
    queryKey: queryKeys.currentUser,
    queryFn: getCurrentUser,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// Note Templates
// ---------------------------------------------------------------------------

export function useNoteTemplates() {
  return useQuery({
    queryKey: queryKeys.noteTemplates,
    queryFn: () => getNoteTemplates(),
    staleTime: 60 * 1000,
    select: (data) => data.templates,
  });
}

export function useActiveNoteTemplates() {
  return useQuery({
    queryKey: [...queryKeys.noteTemplates, 'active'],
    queryFn: () => getNoteTemplates({ activeOnly: true }),
    staleTime: 60 * 1000,
    select: (data) => data.templates,
  });
}

export function useCreateNoteTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: NoteTemplateCreatePayload) => createNoteTemplate(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.noteTemplates });
    },
  });
}

export function useUpdateNoteTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: NoteTemplateUpdatePayload & { id: number }) =>
      updateNoteTemplate(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.noteTemplates });
    },
  });
}

export function useDeleteNoteTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteNoteTemplate(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.noteTemplates });
    },
  });
}
