import { createContext } from 'react';
import type { ThirdPartyPortalSession } from '../api/thirdPartyPortalClient';

export interface ThirdPartyPortalContextValue {
  session: ThirdPartyPortalSession | null;
  isAuthenticated: boolean;
  login: (s: ThirdPartyPortalSession) => void;
  logout: () => void;
}

export const ThirdPartyPortalContext = createContext<ThirdPartyPortalContextValue | null>(null);
