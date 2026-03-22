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
  ClaimReserveHistoryResponse,
  ClaimWorkflowsResponse,
  ReserveAdequacyResponse,
  DocsListResponse,
  DocContentResponse,
  SkillsListResponse,
  SkillDetailResponse,
  AgentsCatalogResponse,
  AuditEvent,
  WorkflowRun,
  SystemConfigData,
  SystemHealthData,
  ChatStreamEvent,
  ClaimTask,
  ClaimTasksResponse,
  AllTasksResponse,
  TaskStatsResponse,
  ClaimPayment,
  ClaimPaymentList,
  ClaimDocumentList,
  ClaimDocument,
  DocumentRequestList,
  DocumentRequest,
  ReviewQueueResponse,
  OverdueTasksResponse,
  ComplianceTemplatesResponse,
  FraudReportingComplianceResponse,
} from './types';

const BASE = '/api';

let _authToken: string | null = null;

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

function parseApiError(status: number, text: string): string {
  let msg = `API error ${status}: ${text.slice(0, 200)}`;
  try {
    const body = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> };
    if (typeof body?.detail === 'string') {
      msg = body.detail;
    } else if (Array.isArray(body?.detail)) {
      const parts = body.detail
        .map((d) => (typeof d === 'object' && d?.msg ? d.msg : null))
        .filter(Boolean);
      if (parts.length > 0) msg = parts.join('; ');
    }
  } catch {
    /* keep msg */
  }
  return msg;
}

async function fetchJSON<T>(url: string, retries = 1): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    const msg = parseApiError(res.status, text);
    if (res.status >= 500 && retries > 0) {
      await new Promise((r) => setTimeout(r, 500));
      return fetchJSON<T>(url, retries - 1);
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

async function postJSON<T>(url: string, body: unknown, retries = 1): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    method: 'POST',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    const msg = parseApiError(res.status, text);
    if (res.status >= 500 && retries > 0) {
      await new Promise((r) => setTimeout(r, 500));
      return postJSON<T>(url, body, retries - 1);
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

async function patchJSON<T>(url: string, body: unknown, retries = 1): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    method: 'PATCH',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    const msg = parseApiError(res.status, text);
    if (res.status >= 500 && retries > 0) {
      await new Promise((r) => setTimeout(r, 500));
      return patchJSON<T>(url, body, retries - 1);
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

async function deleteJSON(url: string, retries = 1): Promise<void> {
  const res = await fetch(`${BASE}${url}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    const msg = parseApiError(res.status, text);
    if (res.status >= 500 && retries > 0) {
      await new Promise((r) => setTimeout(r, 500));
      return deleteJSON(url, retries - 1);
    }
    throw new Error(msg);
  }
}

export const getClaimsStats = (): Promise<ClaimsStats> =>
  fetchJSON<ClaimsStats>('/claims/stats');

export interface GetClaimsParams {
  status?: string;
  claim_type?: string;
  include_archived?: boolean;
  include_purged?: boolean;
  limit?: number;
  offset?: number;
}

export const getClaims = (params: GetClaimsParams = {}): Promise<ClaimsListResponse> => {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.claim_type) qs.set('claim_type', params.claim_type);
  if (params.include_archived === true) qs.set('include_archived', 'true');
  if (params.include_purged === true) qs.set('include_purged', 'true');
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return fetchJSON<ClaimsListResponse>(`/claims${q ? '?' + q : ''}`);
};

export const getClaim = (id: string): Promise<Claim> =>
  fetchJSON<Claim>(`/claims/${id}`);

export const getClaimHistory = (id: string): Promise<ClaimHistoryResponse> =>
  fetchJSON<ClaimHistoryResponse>(`/claims/${id}/history`);

export const getClaimWorkflows = (id: string): Promise<ClaimWorkflowsResponse> =>
  fetchJSON<ClaimWorkflowsResponse>(`/claims/${id}/workflows`);

export const getClaimReserveHistory = (
  id: string,
  limit = 50
): Promise<ClaimReserveHistoryResponse> =>
  fetchJSON<ClaimReserveHistoryResponse>(`/claims/${id}/reserve-history?limit=${limit}`);

export const getClaimReserveAdequacy = (
  id: string
): Promise<ReserveAdequacyResponse> =>
  fetchJSON<ReserveAdequacyResponse>(`/claims/${id}/reserve/adequacy`);

export interface PatchClaimReserveBody {
  reserve_amount: number;
  reason?: string;
  /** Admin only: bypass reserve authority limits */
  skip_authority_check?: boolean;
}

export interface PatchClaimReserveResponse {
  claim_id: string;
  reserve_amount: number;
}

export const patchClaimReserve = (
  id: string,
  body: PatchClaimReserveBody
): Promise<PatchClaimReserveResponse> =>
  patchJSON<PatchClaimReserveResponse>(`/claims/${id}/reserve`, body);

export const getMetrics = (): Promise<unknown> => fetchJSON('/metrics');
export const getClaimMetrics = (id: string): Promise<unknown> =>
  fetchJSON(`/metrics/${id}`);

export interface CostBreakdown {
  global_stats: {
    total_claims: number;
    total_llm_calls: number;
    total_tokens: number;
    total_cost_usd: number;
    avg_cost_per_claim: number;
    avg_tokens_per_claim: number;
    by_crew: Record<string, { total_cost_usd: number; total_tokens: number; total_calls: number }>;
    by_claim_type: Record<string, { total_cost_usd: number; total_tokens: number; total_claims: number; total_calls: number }>;
  };
  by_crew: Record<string, { total_cost_usd: number; total_tokens: number; total_calls: number }>;
  by_claim_type: Record<string, { total_cost_usd: number; total_tokens: number; total_claims: number; total_calls: number }>;
  daily: Record<string, { total_cost_usd: number; total_tokens: number; claims: number }>;
  total_cost_usd: number;
  total_tokens: number;
}

export const getCostBreakdown = (): Promise<CostBreakdown> =>
  fetchJSON<CostBreakdown>('/metrics/cost');

export const getDocs = (): Promise<DocsListResponse> =>
  fetchJSON<DocsListResponse>('/docs');

export const getDoc = (slug: string): Promise<DocContentResponse> =>
  fetchJSON<DocContentResponse>(`/docs/${slug}`);

export const getSkills = (): Promise<SkillsListResponse> =>
  fetchJSON<SkillsListResponse>('/skills');

export const getSkill = (name: string): Promise<SkillDetailResponse> =>
  fetchJSON<SkillDetailResponse>(`/skills/${name}`);

export const getSystemConfig = (): Promise<SystemConfigData> =>
  fetchJSON<SystemConfigData>('/system/config');

export const getSystemHealth = (): Promise<SystemHealthData> =>
  fetchJSON<SystemHealthData>('/system/health');

export const getAgentsCatalog = (): Promise<AgentsCatalogResponse> =>
  fetchJSON<AgentsCatalogResponse>('/system/agents');

export interface PolicyVehicle {
  vin: string;
  vehicle_year: number;
  vehicle_make: string;
  vehicle_model: string;
}

export interface PolicyWithVehicles {
  policy_number: string;
  status: string;
  vehicle_count?: number;
  liability_limits?: { bi_per_accident?: number; pd_per_accident?: number };
  collision_deductible?: number;
  comprehensive_deductible?: number;
  vehicles: PolicyVehicle[];
}

export interface PoliciesListResponse {
  policies: PolicyWithVehicles[];
}

export const getPolicies = (): Promise<PoliciesListResponse> =>
  fetchJSON<PoliciesListResponse>('/system/policies');

export interface GenerateIncidentDetailsPayload {
  vehicle_year: number;
  vehicle_make: string;
  vehicle_model: string;
  prompt?: string;
}

export interface GenerateIncidentDetailsResponse {
  incident_date: string;
  incident_description: string;
  damage_description: string;
  estimated_damage: number | null;
}

export const generateIncidentDetails = (
  payload: GenerateIncidentDetailsPayload
): Promise<GenerateIncidentDetailsResponse> =>
  postJSON<GenerateIncidentDetailsResponse>(
    '/claims/generate-incident-details',
    payload
  );

// ---------------------------------------------------------------------------
// Simulation action helpers (dispute, supplemental)
// ---------------------------------------------------------------------------

export interface PostClaimDisputePayload {
  dispute_type: string;
  dispute_description: string;
  policyholder_evidence?: string | null;
}

export interface PostClaimDisputeResponse {
  resolution_type?: string;
  summary?: string;
  [key: string]: unknown;
}

export const postClaimDispute = (
  claimId: string,
  payload: PostClaimDisputePayload
): Promise<PostClaimDisputeResponse> =>
  postJSON<PostClaimDisputeResponse>(`/claims/${claimId}/dispute`, payload);

export interface PostClaimSupplementalPayload {
  supplemental_damage_description: string;
  reported_by: string;
}

export interface PostClaimSupplementalResponse {
  supplemental_amount?: number;
  summary?: string;
  [key: string]: unknown;
}

export const postClaimSupplemental = (
  claimId: string,
  payload: PostClaimSupplementalPayload
): Promise<PostClaimSupplementalResponse> =>
  postJSON<PostClaimSupplementalResponse>(`/claims/${claimId}/supplemental`, payload);

export interface RepairStatusRecord {
  id: number;
  claim_id: string;
  shop_id: string;
  authorization_id?: string;
  status: string;
  status_updated_at: string;
  notes?: string;
  paused_at?: string;
  pause_reason?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ClaimRepairStatusResponse {
  claim_id: string;
  latest: RepairStatusRecord | null;
  history: RepairStatusRecord[];
  cycle_time_days?: number | null;
}

export const getClaimRepairStatus = (claimId: string): Promise<ClaimRepairStatusResponse> =>
  fetchJSON<ClaimRepairStatusResponse>(`/claims/${claimId}/repair-status`);

export interface PostClaimRepairStatusPayload {
  status: string;
  shop_id?: string;
  authorization_id?: string;
  notes?: string;
}

export const postClaimRepairStatus = (
  claimId: string,
  payload: PostClaimRepairStatusPayload
): Promise<{ ok: boolean; repair_status_id: number }> =>
  postJSON<{ ok: boolean; repair_status_id: number }>(`/claims/${claimId}/repair-status`, payload);

export interface PostClaimFollowUpResponsePayload {
  message_id: number;
  response_content: string;
}

export interface PostClaimFollowUpResponseResponse {
  success: boolean;
  message?: string;
}

export const postClaimFollowUpResponse = (
  claimId: string,
  payload: PostClaimFollowUpResponsePayload
): Promise<PostClaimFollowUpResponseResponse> =>
  postJSON<PostClaimFollowUpResponseResponse>(
    `/claims/${claimId}/follow-up/record-response`,
    payload
  );

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
  /** Completed workflow stage keys for progress indicator */
  progress?: string[];
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
    const msg = parseApiError(res.status, text);
    throw new Error(msg);
  }
  return res.json() as Promise<ProcessClaimAsyncResponse>;
}

const MAX_STREAM_RETRIES = 3;
const STREAM_RETRY_DELAY_MS = 2000;

export function streamClaimUpdates(
  claimId: string,
  onUpdate: (data: ClaimStreamUpdate) => void,
  onError?: (err: Error) => void
): () => void {
  const controller = new AbortController();
  const abort = () => controller.abort();
  let receivedDone = false;
  let retries = 0;

  async function connect() {
    try {
      const res = await fetch(`${BASE}/claims/${claimId}/stream`, {
        signal: controller.signal,
        credentials: 'include',
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error(`Stream error ${res.status}`);
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';
      retries = 0;
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
              if (data.done) receivedDone = true;
            } catch {
              // ignore parse errors
            }
          }
        }
      }
      if (!receivedDone && !controller.signal.aborted && retries < MAX_STREAM_RETRIES) {
        retries++;
        await new Promise((r) => setTimeout(r, STREAM_RETRY_DELAY_MS * retries));
        return connect();
      }
      if (!receivedDone && !controller.signal.aborted) {
        onError?.(new Error('Stream ended unexpectedly. The claim may still be processing.'));
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof Error && err.name === 'AbortError') return;
      if (!receivedDone && retries < MAX_STREAM_RETRIES) {
        retries++;
        await new Promise((r) => setTimeout(r, STREAM_RETRY_DELAY_MS * retries));
        return connect();
      }
      onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  }

  connect();
  return abort;
}

// ---------------------------------------------------------------------------
// Chat Agent
// ---------------------------------------------------------------------------

export interface ChatRequestMessage {
  role: 'user' | 'assistant';
  content: string;
}

export function streamChat(
  messages: ChatRequestMessage[],
  onEvent: (event: ChatStreamEvent) => void,
  onError?: (err: Error) => void,
): () => void {
  const controller = new AbortController();
  const abort = () => controller.abort();
  let receivedDone = false;

  async function connect() {
    try {
      const res = await fetch(`${BASE}/chat`, {
        method: 'POST',
        signal: controller.signal,
        credentials: 'include',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ messages }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(parseApiError(res.status, text));
      }
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
              const data = JSON.parse(match[1]) as ChatStreamEvent;
              onEvent(data);
              if (data.type === 'done') receivedDone = true;
            } catch {
              // ignore parse errors
            }
          }
        }
      }
      if (!receivedDone && !controller.signal.aborted) {
      onError?.(new Error('Stream ended unexpectedly'));
    }
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof Error && err.name === 'AbortError') return;
      onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  }

  connect();
  return abort;
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

export interface CreateTaskPayload {
  title: string;
  task_type: string;
  description?: string;
  priority?: string;
  assigned_to?: string;
  due_date?: string;
}

export interface UpdateTaskPayload {
  title?: string;
  description?: string;
  status?: string;
  priority?: string;
  assigned_to?: string;
  due_date?: string;
  resolution_notes?: string;
}

export const getClaimTasks = (claimId: string): Promise<ClaimTasksResponse> =>
  fetchJSON<ClaimTasksResponse>(`/claims/${claimId}/tasks`);

export const createClaimTask = (
  claimId: string,
  payload: CreateTaskPayload
): Promise<ClaimTask> =>
  postJSON<ClaimTask>(`/claims/${claimId}/tasks`, payload);

export const getAllTasks = (params: {
  status?: string;
  task_type?: string;
  assigned_to?: string;
  due_date_from?: string;
  due_date_to?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<AllTasksResponse> => {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.task_type) qs.set('task_type', params.task_type);
  if (params.assigned_to) qs.set('assigned_to', params.assigned_to);
  if (params.due_date_from) qs.set('due_date_from', params.due_date_from);
  if (params.due_date_to) qs.set('due_date_to', params.due_date_to);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return fetchJSON<AllTasksResponse>(`/tasks${q ? '?' + q : ''}`);
};

export const getTaskStats = (): Promise<TaskStatsResponse> =>
  fetchJSON<TaskStatsResponse>('/tasks/stats');

export const getTask = (taskId: number): Promise<ClaimTask> =>
  fetchJSON<ClaimTask>(`/tasks/${taskId}`);

export const updateTask = (
  taskId: number,
  payload: UpdateTaskPayload
): Promise<ClaimTask> =>
  patchJSON<ClaimTask>(`/tasks/${taskId}`, payload);

// ---------------------------------------------------------------------------
// Review Queue
// ---------------------------------------------------------------------------

export interface GetReviewQueueParams {
  assignee?: string;
  priority?: string;
  older_than_hours?: number;
  limit?: number;
  offset?: number;
}

export const getReviewQueue = (params: GetReviewQueueParams = {}): Promise<ReviewQueueResponse> => {
  const qs = new URLSearchParams();
  if (params.assignee) qs.set('assignee', params.assignee);
  if (params.priority) qs.set('priority', params.priority);
  if (params.older_than_hours != null) qs.set('older_than_hours', String(params.older_than_hours));
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return fetchJSON<ReviewQueueResponse>(`/claims/review-queue${q ? '?' + q : ''}`);
};

export const assignClaim = (
  claimId: string,
  assignee: string
): Promise<{ claim_id: string; assignee: string }> =>
  patchJSON<{ claim_id: string; assignee: string }>(`/claims/${claimId}/assign`, { assignee });

// ---------------------------------------------------------------------------
// Payments
// ---------------------------------------------------------------------------

export interface CreatePaymentPayload {
  claim_id: string;
  amount: number;
  payee: string;
  payee_type: string;
  payment_method: string;
  check_number?: string;
  payee_secondary?: string;
  payee_secondary_type?: string;
}

export const getClaimPayments = (
  claimId: string,
  params: { status?: string; limit?: number; offset?: number } = {}
): Promise<ClaimPaymentList> => {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return fetchJSON<ClaimPaymentList>(`/claims/${claimId}/payments${q ? '?' + q : ''}`);
};

export const createPayment = (
  claimId: string,
  payload: CreatePaymentPayload
): Promise<ClaimPayment> =>
  postJSON<ClaimPayment>(`/claims/${claimId}/payments`, payload);

export const issuePayment = (
  claimId: string,
  paymentId: number,
  body?: { check_number?: string }
): Promise<ClaimPayment> =>
  postJSON<ClaimPayment>(`/claims/${claimId}/payments/${paymentId}/issue`, body ?? {});

export const clearPayment = (
  claimId: string,
  paymentId: number
): Promise<ClaimPayment> =>
  postJSON<ClaimPayment>(`/claims/${claimId}/payments/${paymentId}/clear`, {});

export const voidPayment = (
  claimId: string,
  paymentId: number,
  body?: { reason?: string }
): Promise<ClaimPayment> =>
  postJSON<ClaimPayment>(`/claims/${claimId}/payments/${paymentId}/void`, body ?? {});

// ---------------------------------------------------------------------------
// Documents (structured documents, not raw attachments)
// ---------------------------------------------------------------------------

export const getClaimDocuments = (
  claimId: string,
  params: {
    document_type?: string;
    review_status?: string;
    group_by?: 'storage_key';
    limit?: number;
    offset?: number;
  } = {}
): Promise<ClaimDocumentList> => {
  const qs = new URLSearchParams();
  if (params.document_type) qs.set('document_type', params.document_type);
  if (params.review_status) qs.set('review_status', params.review_status);
  if (params.group_by) qs.set('group_by', params.group_by);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return fetchJSON<ClaimDocumentList>(`/claims/${claimId}/documents${q ? '?' + q : ''}`);
};

const MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB, must match backend
const ALLOWED_DOCUMENT_EXTENSIONS = new Set([
  'pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'doc', 'docx', 'xls', 'xlsx',
]);

export async function uploadClaimDocument(
  claimId: string,
  file: File,
  params: { document_type?: string; received_from?: string } = {}
): Promise<{ claim_id: string; document_id: number; document: ClaimDocument }> {
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    throw new Error(`File exceeds maximum upload size of ${MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)} MB`);
  }
  const ext = (file.name.split('.').pop() ?? '').toLowerCase();
  if (!ext || !ALLOWED_DOCUMENT_EXTENSIONS.has(ext)) {
    throw new Error(
      `File type not allowed. Allowed: ${[...ALLOWED_DOCUMENT_EXTENSIONS].sort().join(', ')}`
    );
  }

  const qs = new URLSearchParams();
  if (params.document_type) qs.set('document_type', params.document_type);
  if (params.received_from) qs.set('received_from', params.received_from);
  const q = qs.toString();

  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${BASE}/claims/${claimId}/documents${q ? '?' + q : ''}`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const text = await res.text();
    const msg = parseApiError(res.status, text);
    throw new Error(msg);
  }
  return res.json() as Promise<{ claim_id: string; document_id: number; document: ClaimDocument }>;
}

export interface UpdateDocumentBody {
  review_status?: string;
  document_type?: string;
  privileged?: boolean;
  retention_date?: string;
}

export const updateClaimDocument = (
  claimId: string,
  docId: number,
  body: UpdateDocumentBody
): Promise<{ claim_id: string; document_id: number; document: ClaimDocument }> =>
  patchJSON<{ claim_id: string; document_id: number; document: ClaimDocument }>(
    `/claims/${claimId}/documents/${docId}`, body
  );

export const getDocumentRequests = (
  claimId: string,
  params: { status?: string; limit?: number; offset?: number } = {}
): Promise<DocumentRequestList> => {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return fetchJSON<DocumentRequestList>(`/claims/${claimId}/document-requests${q ? '?' + q : ''}`);
};

export const createDocumentRequest = (
  claimId: string,
  body: { document_type: string; requested_from?: string }
): Promise<{ claim_id: string; request_id: number; request: DocumentRequest }> =>
  postJSON<{ claim_id: string; request_id: number; request: DocumentRequest }>(
    `/claims/${claimId}/document-requests`, body
  );

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

export const addClaimNote = (
  claimId: string,
  note: string,
  actorId: string
): Promise<{ claim_id: string; actor_id: string }> =>
  postJSON<{ claim_id: string; actor_id: string }>(`/claims/${claimId}/notes`, {
    note,
    actor_id: actorId,
  });

// ---------------------------------------------------------------------------
// Overdue Tasks & Compliance Templates
// ---------------------------------------------------------------------------

export const getOverdueTasks = (limit = 100): Promise<OverdueTasksResponse> =>
  fetchJSON<OverdueTasksResponse>(`/tasks/overdue?limit=${limit}`);

export const getComplianceTemplates = (
  state?: string
): Promise<ComplianceTemplatesResponse> => {
  const qs = state ? `?state=${encodeURIComponent(state)}` : '';
  return fetchJSON<ComplianceTemplatesResponse>(`/diary/compliance-templates${qs}`);
};

// ---------------------------------------------------------------------------
// Party Relationships
// ---------------------------------------------------------------------------

export interface CreatePartyRelationshipPayload {
  from_party_id: number;
  to_party_id: number;
  relationship_type: string;
}

export interface CreatePartyRelationshipResponse {
  id: number;
  claim_id: string;
  from_party_id: number;
  to_party_id: number;
  relationship_type: string;
}

export const createPartyRelationship = (
  claimId: string,
  body: CreatePartyRelationshipPayload,
): Promise<CreatePartyRelationshipResponse> =>
  postJSON<CreatePartyRelationshipResponse>(
    `/claims/${claimId}/party-relationships`,
    body,
  );

export const deletePartyRelationship = (
  claimId: string,
  relationshipId: number,
): Promise<void> =>
  deleteJSON(`/claims/${claimId}/party-relationships/${relationshipId}`);

// ---------------------------------------------------------------------------
// Fraud Compliance
// ---------------------------------------------------------------------------

export interface GetFraudReportingComplianceParams {
  state?: string;
  limit?: number;
}

export const getFraudReportingCompliance = (
  params: GetFraudReportingComplianceParams = {},
): Promise<FraudReportingComplianceResponse> => {
  const qs = new URLSearchParams();
  if (params.state) qs.set('state', params.state);
  if (params.limit != null) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return fetchJSON<FraudReportingComplianceResponse>(`/compliance/fraud-reporting${q ? '?' + q : ''}`);
};
