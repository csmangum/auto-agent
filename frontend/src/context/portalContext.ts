import { createContext } from 'react';
import type { PortalSession } from '../api/portalClient';

export interface PortalContextValue {
  session: PortalSession | null;
  isAuthenticated: boolean;
  login: (s: PortalSession) => void;
  logout: () => void;
}

export const PortalContext = createContext<PortalContextValue | null>(null);
