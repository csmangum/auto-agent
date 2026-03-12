import type { ComponentType } from 'react';
import type { SVGProps } from 'react';
import {
  AgentsIcon,
  ClaimsIcon,
  DashboardIcon,
  DocsIcon,
  EscalationIcon,
  FraudIcon,
  PartialLossIcon,
  PlusIcon,
  RouterIcon,
  SearchIcon,
  SettlementIcon,
  SkillsIcon,
  SubrogationIcon,
  SystemIcon,
  TotalLossIcon,
  WorkflowIcon,
} from './index';

export const NAV_ICONS = {
  dashboard: DashboardIcon,
  claims: ClaimsIcon,
  newClaim: PlusIcon,
  docs: DocsIcon,
  skills: SkillsIcon,
  agents: AgentsIcon,
  system: SystemIcon,
} as const;

export const SKILL_GROUP_ICONS: Record<string, ComponentType<SVGProps<SVGSVGElement>>> = {
  'Core Routing': RouterIcon,
  'New Claim Workflow': WorkflowIcon,
  'Duplicate Detection': SearchIcon,
  'Fraud Detection': FraudIcon,
  'Total Loss': TotalLossIcon,
  'Partial Loss': PartialLossIcon,
  'Settlement Workflow': SettlementIcon,
  Subrogation: SubrogationIcon,
  Escalation: EscalationIcon,
};

/** Icons for crew sections (cycle by index when crew name is dynamic) */
export const CREW_CYCLE_ICONS = [
  RouterIcon,
  WorkflowIcon,
  SearchIcon,
  FraudIcon,
  TotalLossIcon,
  PartialLossIcon,
  SettlementIcon,
  SubrogationIcon,
  EscalationIcon,
] as const;

export type NavIconKey = keyof typeof NAV_ICONS;
