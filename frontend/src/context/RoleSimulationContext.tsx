/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

export type SimulationRole = 'adjuster' | 'customer' | 'repair_shop' | 'third_party';

export interface RoleDefinition {
  id: SimulationRole;
  label: string;
  description: string;
  accent: string;
  accentBg: string;
  accentRing: string;
  accentText: string;
  icon: string;
}

export const ROLE_DEFINITIONS: Record<SimulationRole, RoleDefinition> = {
  adjuster: {
    id: 'adjuster',
    label: 'Adjuster',
    description: 'Internal claims adjuster with full system access',
    accent: 'blue',
    accentBg: 'bg-blue-600',
    accentRing: 'ring-blue-500/20',
    accentText: 'text-blue-400',
    icon: '🛡️',
  },
  customer: {
    id: 'customer',
    label: 'Customer',
    description: 'Policyholder or claimant filing and tracking claims',
    accent: 'emerald',
    accentBg: 'bg-emerald-600',
    accentRing: 'ring-emerald-500/20',
    accentText: 'text-emerald-400',
    icon: '👤',
  },
  repair_shop: {
    id: 'repair_shop',
    label: 'Repair Shop',
    description: 'Body shop managing vehicle repairs and supplements',
    accent: 'amber',
    accentBg: 'bg-amber-600',
    accentRing: 'ring-amber-500/20',
    accentText: 'text-amber-400',
    icon: '🔧',
  },
  third_party: {
    id: 'third_party',
    label: 'Third Party',
    description: 'Other insurance company or third-party claimant',
    accent: 'purple',
    accentBg: 'bg-purple-600',
    accentRing: 'ring-purple-500/20',
    accentText: 'text-purple-400',
    icon: '🏢',
  },
};

const STORAGE_KEY = 'simulation_role' as const;

function getStoredRole(): SimulationRole {
  if (typeof window === 'undefined') return 'adjuster';
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && stored in ROLE_DEFINITIONS) return stored as SimulationRole;
  } catch { /* ignore */ }
  return 'adjuster';
}

interface RoleSimulationContextValue {
  role: SimulationRole;
  roleDef: RoleDefinition;
  isSimulating: boolean;
  setRole: (role: SimulationRole) => void;
  exitSimulation: () => void;
}

const RoleSimulationContext = createContext<RoleSimulationContextValue | null>(null);

export function RoleSimulationProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<SimulationRole>(getStoredRole);

  const setRole = useCallback((newRole: SimulationRole) => {
    setRoleState(newRole);
    try { localStorage.setItem(STORAGE_KEY, newRole); } catch { /* ignore */ }
  }, []);

  const exitSimulation = useCallback(() => {
    setRole('adjuster');
  }, [setRole]);

  const value: RoleSimulationContextValue = {
    role,
    roleDef: ROLE_DEFINITIONS[role],
    isSimulating: role !== 'adjuster',
    setRole,
    exitSimulation,
  };

  return (
    <RoleSimulationContext.Provider value={value}>
      {children}
    </RoleSimulationContext.Provider>
  );
}

export function useRoleSimulation(): RoleSimulationContextValue {
  const ctx = useContext(RoleSimulationContext);
  if (!ctx) throw new Error('useRoleSimulation must be used within RoleSimulationProvider');
  return ctx;
}
