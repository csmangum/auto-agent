import { createContext } from 'react';
import type { RepairPortalSession } from '../api/repairPortalClient';

export interface RepairPortalContextValue {
  session: RepairPortalSession | null;
  isAuthenticated: boolean;
  login: (s: RepairPortalSession) => void;
  logout: () => void;
}

export const RepairPortalContext = createContext<RepairPortalContextValue | null>(null);
