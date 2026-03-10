/** API response types for the Claims System backend */

export interface Claim {
  id: string;
  policy_number: string;
  vin: string;
  vehicle_year?: number;
  vehicle_make?: string;
  vehicle_model?: string;
  incident_date?: string;
  incident_description?: string;
  damage_description?: string;
  estimated_damage?: number;
  claim_type?: string;
  status: string;
  payout_amount?: number;
  created_at?: string;
  updated_at?: string;
  /** Review queue fields */
  priority?: string; // critical | high | medium | low
  due_at?: string; // ISO datetime
  assignee?: string; // adjuster/user ID
  siu_case_id?: string; // SIU case ID when escalated
  review_started_at?: string; // ISO datetime when entered needs_review
}

export interface ClaimsStats {
  total_claims: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  earliest_claim?: string;
  latest_claim?: string;
  total_audit_events: number;
  total_workflow_runs: number;
}

export interface ClaimsListResponse {
  claims: Claim[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditEvent {
  id?: number;
  claim_id: string;
  action: string;
  old_status?: string;
  new_status?: string;
  details?: string;
  actor_id?: string;
  before_state?: string;
  after_state?: string;
  created_at?: string;
}

export interface ClaimHistoryResponse {
  claim_id: string;
  history: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface WorkflowRun {
  id?: number;
  claim_id: string;
  claim_type?: string;
  router_output?: string;
  workflow_output?: string;
  created_at?: string;
}

export interface ClaimWorkflowsResponse {
  claim_id: string;
  workflows: WorkflowRun[];
}

export interface DocPage {
  slug: string;
  title: string;
  available: boolean;
}

export interface DocsListResponse {
  pages: DocPage[];
}

export interface DocContentResponse {
  slug: string;
  title: string;
  content: string;
}

export interface SkillSummary {
  name: string;
  role: string;
  goal?: string;
}

export interface SkillsListResponse {
  groups: Record<string, SkillSummary[]>;
}

export interface SkillDetailResponse {
  name: string;
  role: string;
  goal?: string;
  backstory?: string;
  content: string;
}

export interface AgentInfo {
  name: string;
  skill: string;
  tools: string[];
  description: string;
}

export interface CrewInfo {
  name: string;
  description: string;
  module: string;
  agents: AgentInfo[];
}

export interface AgentsCatalogResponse {
  crews: CrewInfo[];
}
